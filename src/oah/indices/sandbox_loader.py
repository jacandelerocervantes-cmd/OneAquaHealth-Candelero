"""Generic sandbox-resource loading with freshness, snapshot fallback, and live retrieval.

Not CCME-specific: this loads any FHIR resource type from a local snapshot or the live public
sandbox. See ``oah.indices.apply_to_sandbox`` for the CCME WQI pipeline built on top of it, and
``oah.indices.water_parameter_limits`` for the pure objective-limit logic.
"""

from __future__ import annotations

import json
import logging
from typing import Any

import httpx

from oah.ingest.freshness import DataFreshness, make_freshness
from oah.ingest.sandbox_client import configured_client
from oah.paths import sandbox_snapshot_path
from oah.timeutil import utc_now

logger = logging.getLogger(__name__)


SNAPSHOT_MAX_AGE_SECONDS = 24 * 3600


class SandboxDataUnavailableError(RuntimeError):
    """Neither a readable snapshot nor the live sandbox produced the requested resources."""


def _read_snapshot(resource_type: str) -> list[dict[str, Any]] | None:
    """Return the snapshot's resources, or None when it is absent, unreadable or malformed."""
    snapshot_file = sandbox_snapshot_path(resource_type)
    if not snapshot_file.is_file():
        return None
    try:
        data = json.loads(snapshot_file.read_text(encoding="utf-8"))
    except (OSError, json.JSONDecodeError) as error:
        logger.warning("Ignoring unreadable %s snapshot: %s", resource_type, error)
        return None
    if not isinstance(data, list):
        logger.warning("Ignoring %s snapshot: expected a JSON list.", resource_type)
        return None
    return data


def _snapshot_age_seconds(resource_type: str) -> float:
    return max(0.0, utc_now().timestamp() - sandbox_snapshot_path(resource_type).stat().st_mtime)


def _snapshot_epoch(resource_type: str) -> float:
    return sandbox_snapshot_path(resource_type).stat().st_mtime


def load_sandbox_resources_with_freshness(
    resource_type: str, max_age_seconds: float = SNAPSHOT_MAX_AGE_SECONDS
) -> tuple[list[dict[str, Any]], DataFreshness]:
    """Return sandbox resources of one type together with where they came from and how old they are.

    Order: a FRESH snapshot (younger than ``max_age_seconds``), then the live sandbox, then a
    STALE snapshot as an offline last resort (logged loudly). If nothing is available a
    ``SandboxDataUnavailableError`` is raised instead of returning an empty list that would be
    mislabeled as real-sandbox data. The freshness status is ``snapshot`` for the first case,
    ``live`` for the second and ``snapshot-stale`` for the third.
    """
    snapshot = _read_snapshot(resource_type)
    if snapshot is not None and _snapshot_age_seconds(resource_type) <= max_age_seconds:
        return snapshot, make_freshness("snapshot", _snapshot_epoch(resource_type))
    try:
        client = configured_client()
        resources = [resource for page in client.pages(resource_type) for resource in page]
        return resources, make_freshness("live", utc_now().timestamp())
    except (httpx.HTTPError, RuntimeError, ValueError) as error:
        if snapshot is not None:
            logger.warning(
                "Live sandbox unavailable (%s); using a %.1f-hour-old %s snapshot.",
                error, _snapshot_age_seconds(resource_type) / 3600, resource_type,
            )
            return snapshot, make_freshness("snapshot-stale", _snapshot_epoch(resource_type))
        raise SandboxDataUnavailableError(
            f"Could not obtain {resource_type} resources from a snapshot or the live sandbox: {error}"
        ) from error


def load_sandbox_resources(resource_type: str, max_age_seconds: float = SNAPSHOT_MAX_AGE_SECONDS) -> list[dict[str, Any]]:
    """Return sandbox resources of one type (see ``load_sandbox_resources_with_freshness``)."""
    return load_sandbox_resources_with_freshness(resource_type, max_age_seconds)[0]


def fetch_sandbox_observations() -> list[dict[str, Any]]:
    """Fetch Observations from the snapshot fallback or the live sandbox client."""
    return load_sandbox_resources("Observation")


def fetch_sandbox_locations() -> list[dict[str, Any]]:
    """Fetch Location resources from the snapshot fallback or the live sandbox client."""
    return load_sandbox_resources("Location")
