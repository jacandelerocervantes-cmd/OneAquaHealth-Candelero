"""Orchestration used by the routes: freshness-aware sandbox fetch+cache, and the reliability-campaign and FHIR-export
pipelines. The LLM orchestration (explanation budget, translation, chat) lives in ``oah.api.llm_services`` and is
re-exported here, so ``oah.api.services`` keeps every name it always had.

This module still adds NO new business logic of its own beyond sequencing and response assembly:
every step below calls an already-tested oah.* function. It exists so the routes (``oah.api.routes``) can stay a thin
routing layer.

Dependency-injection note: functions here that wrap a seam the tests monkeypatch on ``oah.api.deps``
(get_llm_client, get_llm_guard, export_path) take that seam as an explicit parameter, supplied by the route as
``deps.NAME`` looked up at call time. This keeps the monkeypatch targets on ``oah.api.deps`` without this module
importing it back (which would be circular).
"""

from __future__ import annotations

import json
import logging
import threading
from collections import OrderedDict
from typing import Any, Callable

from fastapi import HTTPException

from oah.api.llm_services import (  # noqa: F401  (re-exported: the former single module's names)
    EXPLANATION_DISCLAIMER,
    _chat_english,
    _chat_fields,
    _chat_with_budget,
    _explain_with_budget,
    _explanation_fields,
    _language_fields,
    _localise_explanation,
    _reserve_one_unit,
    _translated,
    resolve_language,
)
from oah.fhir.output.export import build_findings_bundle, build_indicators_bundle
from oah.api.swr_cache import RevalidatingCache
from oah.config import load_settings
from oah.indices.sandbox_loader import (
    SNAPSHOT_MAX_AGE_SECONDS,
    SandboxDataUnavailableError,
    load_sandbox_resources_with_freshness,
)
from oah.ingest.freshness import DataFreshness, Status, combine_freshness, make_freshness, unknown_freshness, worst_status
from oah.reliability import evaluate_reliability, majority_vote, recommend_method, run_dawid_skene
from oah.synthetic.campaign import generate_campaign
from oah.synthetic.fhir import build_synthetic_batch, rebuild_annotation_table
from oah.timeutil import format_utc, parse_fhir_time, utc_now

logger = logging.getLogger(__name__)

_freshness_by_type: dict[str, DataFreshness] = {}


def get_data_freshness() -> DataFreshness:
    """Least trustworthy freshness among the sandbox data behind the current responses, with a live age.

    A copy that is older than the cache TTL (served while a refresh runs, see ``oah.api.swr_cache``) is never labelled
    ``live``: its status is lowered to ``snapshot`` (a held copy, dated by ``as_of``) or, when it is older than a day,
    ``snapshot-stale``, the same meaning those words have for a file snapshot.
    """
    if not _freshness_by_type:
        return unknown_freshness()
    now = utc_now().timestamp()
    aged = [
        make_freshness(
            _status_for_held_copy(item["status"], resource_type),
            parse_fhir_time(item["as_of"]).start.timestamp() if item["as_of"] else None,
            now,
        )
        for resource_type, item in list(_freshness_by_type.items())
    ]
    return combine_freshness(aged)


def _status_for_held_copy(status: Status, resource_type: str) -> Status:
    """``status`` as recorded when the copy was fetched, lowered when the copy is now past the cache TTL."""
    cache = _caches.get(resource_type)
    if cache is None or not cache.is_past_ttl():
        return status
    age = cache.age_seconds() or 0.0
    return worst_status(status, "snapshot-stale" if age > SNAPSHOT_MAX_AGE_SECONDS else "snapshot")


def _load(resource_type: str) -> tuple[list[dict[str, Any]], DataFreshness]:
    """Fetch one resource type: live sandbox first, a local snapshot only if it is unreachable (503 if neither)."""
    try:
        return load_sandbox_resources_with_freshness(resource_type, max_age_seconds=0.0)
    except SandboxDataUnavailableError as error:
        logger.warning("Sandbox data unavailable: %s", error)  # the detail (URLs, TLS/DNS text) stays in the log
        raise HTTPException(status_code=503, detail="Sandbox data is unavailable (no live data and no usable snapshot).") from error


def _load_live_for_refresh(resource_type: str) -> tuple[list[dict[str, Any]], DataFreshness]:
    """A background refresh only replaces the held copy with LIVE data: falling back to an older snapshot would make it worse."""
    resources, freshness = _load(resource_type)
    if freshness["status"] != "live":
        raise RuntimeError(f"The live sandbox was not reachable for {resource_type}; keeping the held copy.")
    return resources, freshness


_sandbox_settings = load_settings()


def _new_cache(resource_type: str, **overrides: Any) -> RevalidatingCache:
    """The cache of one resource type; ``overrides`` (clock, thread starter, timings) exist for the tests."""
    options: dict[str, Any] = {
        "refresh_fetch": lambda: _load_live_for_refresh(resource_type),
        "on_store": lambda freshness: _freshness_by_type.__setitem__(resource_type, freshness),
        "ttl_seconds": _sandbox_settings.sandbox_cache_ttl_seconds,
        "max_stale_seconds": _sandbox_settings.sandbox_max_stale_seconds,
    }
    options.update(overrides)
    return RevalidatingCache(lambda: _load(resource_type), **options)


_observations_cache = _new_cache("Observation")
_locations_cache = _new_cache("Location")
_caches = {"Observation": _observations_cache, "Location": _locations_cache}


def get_cached_observations() -> list[dict[str, Any]]:
    """Return the cached sandbox Observations, exposed so tests can monkeypatch it."""
    return _observations_cache.get()


def get_cached_locations() -> list[dict[str, Any]]:
    """Return the cached sandbox Locations, exposed so tests can monkeypatch it."""
    return _locations_cache.get()


def start_sandbox_warmup() -> list[threading.Thread]:
    """Fill both sandbox caches in background threads (one per cache, run in parallel) and return the started threads.

    Called once at start-up so the first visitor normally finds a warm cache. It returns at once (the start-up and the
    health check are not delayed) and a failed warm-up is only logged: the first request then fetches as before.
    """
    threads = [
        threading.Thread(target=cache.warm, name=f"oah-sandbox-warmup-{resource_type.lower()}", daemon=True)
        for resource_type, cache in _caches.items()
    ]
    for thread in threads:
        thread.start()
    return threads


CAMPAIGN_CACHE_SIZE = 32  # distinct (seed, sizes) results held; the campaign is deterministic, so a hit is exact
_campaign_cache: OrderedDict[tuple[Any, ...], dict[str, Any]] = OrderedDict()
_campaign_cache_lock = threading.Lock()


def run_reliability_campaign(params: Any, site_labels: tuple[str, ...]) -> dict[str, Any]:
    """Run a synthetic citizen-science campaign through Dawid-Skene and majority vote.

    Every number in this response measures the simulator, not real ecology. The result is a pure function of the
    bounded parameters and the site labels, so the last ``CAMPAIGN_CACHE_SIZE`` results are kept (least recently used out)
    and an identical request costs no CPU.
    """
    key = (params.seed, params.observer_count, params.specimens_per_site, params.annotators_per_specimen, tuple(site_labels))
    with _campaign_cache_lock:
        held = _campaign_cache.get(key)
        if held is not None:
            _campaign_cache.move_to_end(key)
            return dict(held)
    result = _compute_reliability_campaign(params, site_labels)
    with _campaign_cache_lock:
        _campaign_cache[key] = result
        while len(_campaign_cache) > CAMPAIGN_CACHE_SIZE:
            _campaign_cache.popitem(last=False)
    return dict(result)


def _compute_reliability_campaign(params: Any, site_labels: tuple[str, ...]) -> dict[str, Any]:
    campaign = generate_campaign(
        seed=params.seed,
        site_ids=site_labels,
        observer_count=params.observer_count,
        specimens_per_site=params.specimens_per_site,
        annotators_per_specimen=params.annotators_per_specimen,
    )
    batch = build_synthetic_batch(campaign)
    annotations = rebuild_annotation_table(batch.records)

    recommended, diagnostics = recommend_method(annotations)
    mv_labels = majority_vote(annotations, campaign.taxa_families)
    ds_result = run_dawid_skene(annotations, campaign.taxa_families)
    metrics = evaluate_reliability(campaign, ds_result, mv_labels)

    return {
        "origin": "synthetic",
        "seed": params.seed,
        "recommended_method": recommended,
        "recommendation_diagnostics": diagnostics,
        "parameters": {
            "observer_count": params.observer_count,
            "specimens_per_site": params.specimens_per_site,
            "annotators_per_specimen": params.annotators_per_specimen,
        },
        "majority_vote_accuracy": metrics["mv_accuracy"],
        "dawid_skene_accuracy": metrics["ds_accuracy"],
        "majority_vote_macro_f1": metrics["mv_macro_f1"],
        "dawid_skene_macro_f1": metrics["ds_macro_f1"],
        "dawid_skene_log_loss": metrics["log_loss"],
    }


def export_findings_bundle(
    observations: list[dict[str, Any]], sandbox_url_value: str, export_path_fn: Callable[[str], Any]
) -> dict[str, Any]:
    """Export real-sandbox QC findings as a deterministic FHIR Bundle with Provenance.

    ``export_path_fn`` is supplied by the caller (the route's ``deps.export_path``), so tests
    that monkeypatch it there keep working.
    """
    retrieval_date = format_utc(utc_now())
    bundle = build_findings_bundle(observations, retrieval_date, sandbox_url_value, default_origin="real-sandbox")

    resources = [entry["resource"] for entry in bundle["entry"]]
    issue_count = sum(resource["resourceType"] == "DetectedIssue" for resource in resources)

    target = export_path_fn("findings-bundle.json")
    _write_atomic(target, json.dumps(bundle, indent=2, sort_keys=True) + "\n")

    return {
        "origin": "real-sandbox",
        "observations_processed": len(observations),
        "detected_issue_count": issue_count,
        "bundle_id": bundle["id"],
        # Relative to the data directory, never the absolute filesystem path: an absolute
        # path would leak the local username/home-directory layout to any API caller.
        "written_to": target.name,
    }


def _write_atomic(target: Any, text: str) -> None:
    """Write through a temporary file and rename, so a crash never leaves a truncated bundle."""
    target.parent.mkdir(parents=True, exist_ok=True)
    temporary = target.with_name(target.name + ".tmp")
    temporary.write_text(text, encoding="utf-8")
    temporary.replace(target)


def export_indicators_bundle(
    result: dict[str, Any], sandbox_url_value: str, export_path_fn: Callable[[str], Any]
) -> dict[str, Any]:
    """Export a real-sandbox CCME WQI result as OAH-indicators Observations with Provenance.

    ``export_path_fn`` is supplied by the caller (the route's ``deps.export_path``), so tests
    that monkeypatch it there keep working.
    """
    bundle = build_indicators_bundle(result, format_utc(utc_now()), sandbox_url_value)
    target = export_path_fn("indicators-bundle.json")
    _write_atomic(target, json.dumps(bundle, indent=2, sort_keys=True) + "\n")
    return {
        "origin": "real-sandbox",
        "observations_exported": result["evaluated_locations_count"],
        "locations_without_observation": result["skipped_locations_count"],
        "bundle_id": bundle["id"],
        "written_to": target.name,
    }
