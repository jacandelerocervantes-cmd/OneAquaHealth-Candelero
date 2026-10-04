"""A scripted fake HTTP layer and payload builders for the external-context tests. No test reaches the network."""
from __future__ import annotations

import json
from collections.abc import Callable
from datetime import date, timedelta
from typing import Any

import httpx

from oah.external.constants import ARCHIVE_HOST, FLOOD_HOST, GBIF_HOST
from oah.external.http import ExternalHttp
from oah.external.runtime import ExternalRuntime
from oah.external.settings import ExternalSettings
from oah.external.sites import SiteLocator

Handler = Callable[[httpx.Request], httpx.Response]


class FakeClock:
    def __init__(self, start: float = 1000.0) -> None:
        self.now = start

    def __call__(self) -> float:
        return self.now

    def advance(self, seconds: float) -> None:
        self.now += seconds


class Router:
    """Routes a request to a scripted handler by host; every request is recorded (host, path, params, headers)."""

    def __init__(self) -> None:
        self.handlers: dict[str, Handler] = {}
        self.requests: list[httpx.Request] = []

    def on(self, host: str, handler: Handler) -> None:
        self.handlers[host] = handler

    def __call__(self, request: httpx.Request) -> httpx.Response:
        self.requests.append(request)
        handler = self.handlers.get(request.url.host)
        if handler is None:
            raise AssertionError(f"unscripted host {request.url.host}")
        return handler(request)

    def params(self, index: int = -1) -> dict[str, list[str]]:
        query = self.requests[index].url.params
        return {key: query.get_list(key) for key in dict.fromkeys(query.keys())}

    def count(self, host: str | None = None) -> int:
        return sum(1 for r in self.requests if host is None or r.url.host == host)


def json_response(payload: Any, status: int = 200, headers: dict[str, str] | None = None) -> httpx.Response:
    return httpx.Response(
        status, content=json.dumps(payload).encode("utf-8"),
        headers={"content-type": "application/json", **(headers or {})},
    )


def make_http(router: Router, retries: int = 2, sleeps: list[float] | None = None) -> ExternalHttp:
    return ExternalHttp(
        "OneAquaHealth/0.1 (test)", 5.0, retries,
        client_factory=lambda: httpx.Client(transport=httpx.MockTransport(router)),
        sleep=(sleeps.append if sleeps is not None else (lambda seconds: None)),
    )


def make_runtime(
    router: Router | None = None, settings: ExternalSettings | None = None, clock: FakeClock | None = None,
    retries: int = 0,
) -> tuple[ExternalRuntime, Router, FakeClock]:
    routed = router or Router()
    fake_clock = clock or FakeClock()
    config = settings or ExternalSettings(max_retries=retries)
    runtime = ExternalRuntime(config, make_http(routed, retries=config.max_retries), fake_clock)
    return runtime, routed, fake_clock


# --- payload builders (shapes copied from real answers seen on 2026-10-03) ------------------------------------------


def days_between(start: date, end: date) -> list[date]:
    return [start + timedelta(days=offset) for offset in range((end - start).days + 1)]


def daily_payload(
    start: date, end: date, variables: dict[str, Callable[[date], float | None]],
    grid: tuple[float, float] = (45.0, 7.75),
) -> dict[str, Any]:
    days = days_between(start, end)
    return {
        "latitude": grid[0], "longitude": grid[1], "generationtime_ms": 0.1, "utc_offset_seconds": 0,
        "timezone": "GMT", "timezone_abbreviation": "GMT", "elevation": 241.0,
        "daily_units": {"time": "iso8601", **{name: "x" for name in variables}},
        "daily": {"time": [day.isoformat() for day in days], **{name: [fn(day) for day in days] for name, fn in variables.items()}},
    }


def archive_handler(
    rain: Callable[[date], float | None] = lambda day: 1.0,
    temp: Callable[[date], float | None] = lambda day: 10.0,
    grid: tuple[float, float] = (45.0, 7.75),
) -> Handler:
    def handle(request: httpx.Request) -> httpx.Response:
        q = request.url.params
        start, end = date.fromisoformat(q["start_date"]), date.fromisoformat(q["end_date"])
        return json_response(
            daily_payload(start, end, {"precipitation_sum": rain, "temperature_2m_mean": temp}, grid)
        )

    return handle


def flood_handler(
    flow: Callable[[date], float | None] = lambda day: 50.0, grid: tuple[float, float] = (45.075, 7.675)
) -> Handler:
    def handle(request: httpx.Request) -> httpx.Response:
        q = request.url.params
        start, end = date.fromisoformat(q["start_date"]), date.fromisoformat(q["end_date"])
        return json_response(daily_payload(start, end, {"river_discharge": flow}, grid))

    return handle


GBIF_PUBLISHER = "28eb1a3f-1c15-4a95-931a-4af90ecb574d"
GBIF_DATASET = "50c9509d-22c7-4a22-a47d-8c48425ef4a7"
GBIF_DATASET_2 = "7a3679ef-5582-4aaa-81f0-8c2545cafc81"


def occurrence(key: int = 1, order_key: int = 1003, family_key: int = 4395, **overrides: Any) -> dict[str, Any]:
    record: dict[str, Any] = {
        "key": key, "datasetKey": GBIF_DATASET, "publishingOrgKey": GBIF_PUBLISHER, "basisOfRecord": "HUMAN_OBSERVATION",
        "occurrenceStatus": "PRESENT", "orderKey": order_key, "familyKey": family_key, "taxonRank": "SPECIES",
        "scientificName": "Mystacides azureus (Linnaeus, 1761)", "decimalLatitude": 45.0931, "decimalLongitude": 7.7255,
        "coordinateUncertaintyInMeters": 37.0, "year": 2026, "eventDate": "2026-05-01T10:47:34",
        "license": "http://creativecommons.org/licenses/by-nc/4.0/legalcode", "datasetName": "iNaturalist research-grade observations",
        "institutionCode": "iNaturalist", "rightsHolder": "an observer", "recordedBy": "Observer Name",
        "references": "https://www.inaturalist.org/observations/357121084", "issues": ["COORDINATE_ROUNDED", "TAXON_ID_NOT_FOUND"],
    }
    record.update(overrides)
    return record


def search_payload(records: list[Any], count: int | None = None, facets: list[Any] | None = None) -> dict[str, Any]:
    return {
        "offset": 0, "limit": len(records), "endOfRecords": True, "count": len(records) if count is None else count,
        "results": records,
        "facets": facets if facets is not None else [
            {"field": "ORDER_KEY", "counts": [{"name": "1003", "count": len(records)}]}
        ],
    }


def dataset_payload(title: str = "iNaturalist Research-grade Observations", citation: str | None = "iNaturalist contributors (2026). Test citation.") -> dict[str, Any]:
    payload: dict[str, Any] = {"key": GBIF_DATASET, "title": title, "license": "http://creativecommons.org/licenses/by-nc/4.0/legalcode"}
    if citation is not None:
        payload["citation"] = {"text": citation, "citationProvidedBySource": False}
    return payload


def gbif_handler(search: Callable[[httpx.Request], httpx.Response], dataset: Callable[[str], dict[str, Any]] | None = None) -> Handler:
    def handle(request: httpx.Request) -> httpx.Response:
        if request.url.path == "/v1/occurrence/search":
            return search(request)
        if request.url.path.startswith("/v1/dataset/"):
            key = request.url.path.rsplit("/", 1)[1]
            return json_response((dataset or (lambda k: dataset_payload()))(key))
        raise AssertionError(f"unscripted path {request.url.path}")

    return handle


def fake_locator() -> SiteLocator:
    waterbase: dict[str, dict[str, Any]] = {
        "ITRIVER1": {"id": "ITRIVER1", "name": "PO - TEST", "latitude": 45.07, "longitude": 7.69, "limit_country": "IT",
                     "water_category": "river", "source": "real-eea-waterbase"},
        "ITLAKE1": {"id": "ITLAKE1", "name": "LAKE TEST", "latitude": 45.5, "longitude": 9.2, "limit_country": "IT",
                    "water_category": "lake", "source": "real-eea-waterbase"},
        "ITNOLOC": {"id": "ITNOLOC", "name": "NO LOCATION", "latitude": None, "longitude": None, "limit_country": "IT",
                    "water_category": "river", "source": "real-eea-waterbase"},
    }
    sandbox: list[dict[str, Any]] = [{"id": "Loc-Almyros", "name": "Almyros", "latitude": 35.3, "longitude": 24.4, "limit_country": "GR", "source": "real-sandbox"}]
    bathing: dict[str, dict[str, Any]] = {
        "IT001001050001": {"id": "IT001001050001", "name": "LIDO", "country": "IT", "type": "lakeBathingWater",
                           "latitude": 45.3197, "longitude": 7.9005, "source": "real-eea-bathing-water"},
        "GRCOAST": {"id": "GRCOAST", "name": "COAST", "country": "GR", "type": "coastalBathingWater", "latitude": 37.9, "longitude": 23.7},
    }
    return SiteLocator(
        waterbase=lambda site_id: waterbase.get(site_id), sandbox=lambda: sandbox, bathing=lambda site_id: bathing.get(site_id)
    )


__all__ = [
    "ARCHIVE_HOST", "FLOOD_HOST", "GBIF_HOST", "FakeClock", "Router", "archive_handler", "dataset_payload",
    "fake_locator", "flood_handler", "gbif_handler", "json_response", "make_http", "make_runtime", "occurrence",
    "search_payload",
]
