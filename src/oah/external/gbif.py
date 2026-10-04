"""GBIF: opportunistic species occurrence records in a fixed square around a site.

What the numbers are: records that people and institutions published to GBIF (many from citizen-science platforms,
museums and surveys), NOT monitoring of the site and NOT an inventory: no record in the square says nothing about the
absence of a species there. The search is a counter-clockwise WKT square of half side ``GBIF_HALF_SIDE_KM`` around the
rounded site point, limited to the taxon groups of ``oah.external.taxa`` (discovered GBIF backbone keys), present
records with coordinates and no geospatial issue. The counts per group are GBIF's own facet counts (not computed here).

Every record keeps its licence (CC0 1.0, CC BY 4.0 or CC BY-NC 4.0 are named; anything else is shown as given), its
dataset and publishing organisation keys and its institution code, and, when GBIF provides one, the dataset title and
citation text (one dataset call per distinct dataset, at most ``MAX_CITATION_DATASETS`` per response). The names of
individuals (``recordedBy`` and ``rightsHolder``, which can be a person's name or username) are deliberately not passed on,
and a record link is kept only when it is an https URL on gbif.org.
"""
from __future__ import annotations

import math
import re
import unicodedata
from datetime import date
from typing import Any
from urllib.parse import urlsplit
from uuid import UUID

from oah.external import coords
from oah.external.constants import (
    FLAG_CITATIONS_PARTIAL,
    FLAG_NON_COMMERCIAL_RECORDS,
    FLAG_TRUNCATED,
    GBIF_DATASET_PATH,
    GBIF_HALF_SIDE_KM,
    GBIF_HOST,
    GBIF_SEARCH_PATH,
    PROVIDER_GBIF,
    REASON_BAD_RESPONSE,
    STATUS_NO_DATA,
    STATUS_OK,
)
from oah.external.envelope import ExternalInputError, envelope, unavailable
from oah.external.http import ExternalError
from oah.external.runtime import ExternalRuntime
from oah.external.sites import LocatedSite
from oah.external.taxa import TaxonCatalogue, TaxonGroup, load_catalogue

DEFAULT_LIMIT = 50
MAX_LIMIT = 200
MAX_CITATION_DATASETS = 5
DATASET_TTL_SECONDS = 24 * 3600.0
SEARCH_MAX_BYTES = 4 * 1024 * 1024  # 200 records are about 1 MB; the cap leaves room without being unbounded
DATASET_MAX_BYTES = 2 * 1024 * 1024  # a dataset description of 120 KB was seen
EARLIEST_EVENT_DATE = date(1700, 1, 1)
LICENCE_CC0 = "CC0-1.0"
LICENCE_BY = "CC-BY-4.0"
LICENCE_BY_NC = "CC-BY-NC-4.0"
LICENCE_OTHER = "other-or-unspecified"
_LICENCES: tuple[tuple[re.Pattern[str], str], ...] = (
    (re.compile(r"publicdomain/zero/1\.0|^CC0_1_0$|^CC0-1\.0$", re.IGNORECASE), LICENCE_CC0),
    (re.compile(r"licenses/by-nc/4\.0|^CC_BY_NC_4_0$|^CC-BY-NC-4\.0$", re.IGNORECASE), LICENCE_BY_NC),
    (re.compile(r"licenses/by/4\.0|^CC_BY_4_0$|^CC-BY-4\.0$", re.IGNORECASE), LICENCE_BY),
)
_BASIS = re.compile(r"^[A-Z_]{3,40}$")
_ISSUE = re.compile(r"^[A-Z_]{3,60}$")
_DIGITS = re.compile(r"^\d{1,20}$")
_HTTPS_URL = re.compile(r"^https://[^\s<>\"']{1,300}$")
RECORD_HOST = "gbif.org"  # record links are kept only on this host (and its subdomains), over https
MAX_ISSUES = 8


def _clean(value: object, limit: int) -> str | None:
    """Text without control, format or private-use characters, markup brackets and runs of spaces; None when empty."""
    if not isinstance(value, str):
        return None
    kept = "".join(ch for ch in value if unicodedata.category(ch)[0] != "C" or ch in " ")
    text = " ".join(kept.replace("<", " ").replace(">", " ").split())[:limit]
    return text or None


def _uuid(value: object) -> str | None:
    if not isinstance(value, str):
        return None
    try:
        return str(UUID(value))
    except ValueError:
        return None


def licence_label(raw: object) -> str:
    """The short label of a GBIF licence value (a URL or an enumeration name); anything else is ``other-or-unspecified``."""
    text = _clean(raw, 200) or ""
    for pattern, label in _LICENCES:
        if pattern.search(text):
            return label
    return LICENCE_OTHER


def _gbif_record_url(value: object) -> str | None:
    """The record link when it is an https URL on gbif.org (or a subdomain), without credentials or an unusual port; else None.

    The ``references`` field of a record is written by the publisher, so any other host (an observation page on a
    third-party site, a tracking URL) is dropped rather than passed to a browser.
    """
    if not isinstance(value, str) or not _HTTPS_URL.fullmatch(value):
        return None
    try:
        parts = urlsplit(value)
        host, port = parts.hostname, parts.port
    except ValueError:
        return None
    if parts.scheme != "https" or parts.username is not None or parts.password is not None or port not in (None, 443):
        return None
    if host is None or not (host == RECORD_HOST or host.endswith("." + RECORD_HOST)):
        return None
    return value


def _float(value: object, low: float, high: float) -> float | None:
    if isinstance(value, bool) or not isinstance(value, (int, float)):
        return None
    number = float(value)
    return number if math.isfinite(number) and low <= number <= high else None


def _group_of(item: dict[str, Any], catalogue: TaxonCatalogue) -> str | None:
    keys = {item.get("orderKey"), item.get("familyKey")}
    for group in catalogue.groups:
        if group.usage_key in keys:
            return group.id
    return None


def parse_record(item: object, centre: tuple[float, float], catalogue: TaxonCatalogue) -> dict[str, Any] | None:
    """One occurrence as the API returns it, reduced to the documented fields; None when it is unusable."""
    if not isinstance(item, dict):
        return None
    key = item.get("key")
    lat, lon = _float(item.get("decimalLatitude"), -90.0, 90.0), _float(item.get("decimalLongitude"), -180.0, 180.0)
    name = _clean(item.get("scientificName"), 200)
    if isinstance(key, bool) or not isinstance(key, int) or key <= 0 or lat is None or lon is None or name is None:
        return None
    licence_raw = _clean(item.get("license"), 200)
    label = licence_label(licence_raw)
    basis = item.get("basisOfRecord")
    issues = item.get("issues")
    references = item.get("references")
    year = item.get("year")
    return {
        "gbif_id": str(key),
        "scientific_name": name,
        "taxon_rank": _clean(item.get("taxonRank"), 30),
        "group": _group_of(item, catalogue),
        "basis_of_record": basis if isinstance(basis, str) and _BASIS.fullmatch(basis) else None,
        "event_date": _clean(item.get("eventDate"), 40),
        "year": year if isinstance(year, int) and not isinstance(year, bool) and 1000 <= year <= 3000 else None,
        "latitude": round(lat, 4),
        "longitude": round(lon, 4),
        "coordinate_uncertainty_m": _float(item.get("coordinateUncertaintyInMeters"), 0.0, 1e7),
        "distance_km": round(coords.distance_km(centre[0], centre[1], lat, lon), 2),
        "licence": label,
        "licence_text": licence_raw if label == LICENCE_OTHER else None,
        "non_commercial_only": label == LICENCE_BY_NC,
        "dataset_key": _uuid(item.get("datasetKey")),
        "dataset_name": _clean(item.get("datasetName"), 160),
        "publishing_organization_key": _uuid(item.get("publishingOrgKey")),
        "institution_code": _clean(item.get("institutionCode"), 60),
        # ``rightsHolder`` (and ``recordedBy``) can be an individual's name or username: not passed on. The attribution
        # the licence needs is carried by the dataset title, the publisher keys, the licence and the citation text.
        "record_url": _gbif_record_url(references),
        "coordinate_issues": [x for x in issues if isinstance(x, str) and _ISSUE.fullmatch(x) and "COORDINATE" in x][:MAX_ISSUES]
        if isinstance(issues, list) else [],
        "citation": None,
    }


def _date_filter(date_from: date | None, date_to: date | None) -> str | None:
    if date_from is None and date_to is None:
        return None
    return f"{date_from.isoformat() if date_from else '*'},{date_to.isoformat() if date_to else '*'}"


def validate_filters(
    group: str | None, date_from: date | None, date_to: date | None, limit: int, catalogue: TaxonCatalogue
) -> tuple[TaxonGroup, ...]:
    """The groups to search; ``ExternalInputError`` for an unknown group, an inverted or implausible date, a bad limit."""
    if isinstance(limit, bool) or not isinstance(limit, int) or not 1 <= limit <= MAX_LIMIT:
        raise ExternalInputError(f"limit must be an integer from 1 to {MAX_LIMIT}.")
    if date_from is not None and date_to is not None and date_from > date_to:
        raise ExternalInputError("date_from must not be after date_to.")
    for value in (date_from, date_to):
        if value is not None and value < EARLIEST_EVENT_DATE:
            raise ExternalInputError(f"Dates before {EARLIEST_EVENT_DATE.isoformat()} are not accepted.")
    try:
        return catalogue.resolve(group)
    except KeyError as error:
        raise ExternalInputError(f"Unknown group; use one of: {', '.join(catalogue.selectable())}.") from error


def _facet_counts(payload: dict[str, Any]) -> dict[str, int]:
    """``{facet field + ':' + key: count}`` from the answer; a malformed facet block is ignored (counts then say 0)."""
    counts: dict[str, int] = {}
    facets = payload.get("facets")
    if not isinstance(facets, list):
        return counts
    for facet in facets:
        if not isinstance(facet, dict) or not isinstance(facet.get("field"), str) or not isinstance(facet.get("counts"), list):
            continue
        for entry in facet["counts"]:
            if isinstance(entry, dict) and isinstance(entry.get("name"), str) and isinstance(entry.get("count"), int):
                counts[f"{facet['field']}:{entry['name']}"] = max(0, entry["count"])
    return counts


def _search(
    runtime: ExternalRuntime, centre: tuple[float, float], groups: tuple[TaxonGroup, ...], date_filter: str | None, limit: int,
    catalogue: TaxonCatalogue,
) -> dict[str, Any]:
    params: list[tuple[str, str]] = [("geometry", coords.search_wkt(centre[0], centre[1]))]
    params.extend(("taxonKey", str(group.usage_key)) for group in groups)
    params.extend(
        [("occurrenceStatus", "PRESENT"), ("hasCoordinate", "true"), ("hasGeospatialIssue", "false")]
    )
    if date_filter is not None:
        params.append(("eventDate", date_filter))
    params.extend([("limit", str(limit)), ("offset", "0"), ("facet", "orderKey"), ("facet", "familyKey"), ("facetLimit", "100")])
    payload = runtime.call(PROVIDER_GBIF, GBIF_HOST, GBIF_SEARCH_PATH, params, units=1.0, max_bytes=SEARCH_MAX_BYTES)
    count, results = payload.get("count"), payload.get("results")
    if isinstance(count, bool) or not isinstance(count, int) or count < 0 or not isinstance(results, list):
        raise ExternalError(REASON_BAD_RESPONSE, "search answer without count or results")
    if len(results) > limit:
        raise ExternalError(REASON_BAD_RESPONSE, "more results than the limit")
    records = [rec for rec in (parse_record(item, centre, catalogue) for item in results) if rec is not None]
    facets = _facet_counts(payload)
    per_group = {
        group.id: facets.get(f"{group.facet}:{group.usage_key}", 0) for group in groups
    }
    return {"total": count, "skipped": len(results) - len(records), "records": records, "group_counts": per_group}


def _dataset(runtime: ExternalRuntime, key: str) -> dict[str, Any] | None:
    """Title and citation text of one dataset, as GBIF provides them; None when it cannot be had."""

    def produce() -> dict[str, Any]:
        payload = runtime.call(PROVIDER_GBIF, GBIF_HOST, f"{GBIF_DATASET_PATH}{key}", [], units=1.0, max_bytes=DATASET_MAX_BYTES)
        citation = payload.get("citation")
        text = _clean(citation.get("text"), 600) if isinstance(citation, dict) else None
        return {
            "dataset_key": key,
            "title": _clean(payload.get("title"), 200),
            "citation": text,
            "licence": licence_label(payload.get("license")),
        }

    try:
        value, _ = runtime.cached(("gbif-dataset", key), produce, DATASET_TTL_SECONDS)
    except ExternalError:
        return None
    return value


def species_context(
    runtime: ExternalRuntime,
    site: LocatedSite,
    group: str | None,
    date_from: date | None,
    date_to: date | None,
    limit: int = DEFAULT_LIMIT,
) -> dict[str, Any]:
    """GBIF occurrences of the chosen groups in the square around ``site``. Never raises for a provider problem."""
    catalogue = load_catalogue()
    groups = validate_filters(group, date_from, date_to, limit, catalogue)
    centre = coords.rounded(site.latitude, site.longitude)
    date_filter = _date_filter(date_from, date_to)
    try:
        wkt_check = coords.search_square(centre[0], centre[1])
    except coords.CoordinateError as error:
        raise ExternalInputError(f"No species search is possible at this site: {error}.") from error
    base: dict[str, Any] = {
        "search": {
            "shape": "square", "half_side_km": GBIF_HALF_SIDE_KM, "centre_latitude": centre[0], "centre_longitude": centre[1],
            "bounds": {"west": wkt_check[0], "south": wkt_check[1], "east": wkt_check[2], "north": wkt_check[3]},
        },
        "filters": {
            "group": group.strip().lower() if group else None,
            "groups_searched": [item.id for item in groups],
            "date_from": date_from.isoformat() if date_from else None,
            "date_to": date_to.isoformat() if date_to else None,
        },
        "limit": limit,
        "total_records": 0,
        "returned": 0,
        "group_counts": [],
        "records": [],
        "datasets": [],
        "licence_summary": {},
        "taxa_file": {"discovered_on": catalogue.discovered_on.isoformat(), "selection_note": catalogue.selection_note},
    }
    key = ("species", centre, tuple(item.id for item in groups), date_filter, limit)
    try:
        found, cached = runtime.cached(key, lambda: _search(runtime, centre, groups, date_filter, limit, catalogue))
    except ExternalError as error:
        return unavailable(PROVIDER_GBIF, error.reason, **base)
    records: list[dict[str, Any]] = [dict(item) for item in found["records"]]  # a copy: the cached value is shared
    flags: list[str] = []
    dataset_keys = list(dict.fromkeys(rec["dataset_key"] for rec in records if rec["dataset_key"]))
    datasets: list[dict[str, Any]] = []
    for dataset_key in dataset_keys[:MAX_CITATION_DATASETS]:
        found_dataset = _dataset(runtime, dataset_key)
        if found_dataset is not None:
            datasets.append(found_dataset)
    if len(datasets) < len(dataset_keys):
        flags.append(FLAG_CITATIONS_PARTIAL)
    by_key = {item["dataset_key"]: item for item in datasets}
    for rec in records:
        info = by_key.get(rec["dataset_key"])
        rec["citation"] = info["citation"] if info else None
    summary: dict[str, int] = {}
    for rec in records:
        summary[rec["licence"]] = summary.get(rec["licence"], 0) + 1
    if found["total"] > len(records) + found["skipped"]:
        flags.append(FLAG_TRUNCATED)
    if any(rec["non_commercial_only"] for rec in records):
        flags.append(FLAG_NON_COMMERCIAL_RECORDS)
    group_counts = [
        {"group": item.id, "name": item.name, "common_name": item.common_name, "rank": item.rank,
         "count": found["group_counts"].get(item.id, 0), "caveat": item.caveat}
        for item in groups
    ]
    fields = {
        **base, "total_records": found["total"], "returned": len(records), "group_counts": group_counts,
        "records": records, "datasets": datasets, "licence_summary": summary, "n_records_skipped": found["skipped"],
    }
    return envelope(
        PROVIDER_GBIF, STATUS_OK if found["total"] > 0 else STATUS_NO_DATA, flags=flags, cached=cached, **fields
    )
