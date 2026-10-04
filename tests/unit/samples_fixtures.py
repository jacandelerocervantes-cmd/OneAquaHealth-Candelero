"""SYNTHETIC fixtures for the bathing-water SAMPLES tests: a scripted fake of the Discodata endpoint and tiny stores built
through the real build code. Every identifier, date and value here is invented; nothing is read from the network or from the
real EEA data. The fake understands only the two query shapes the build sends (the keyset page and the count) and records
every query it receives, so a test can assert what was asked.
"""

from __future__ import annotations

import json
import re
import urllib.parse
from collections.abc import Callable, Sequence
from pathlib import Path
from typing import Any

from oah.bathing_samples.build import build_store
from oah.bathing_samples.client import DiscodataClient, TransientFetchError

PAGE_RE = re.compile(r"SELECT TOP (\d+) .* LIKE '([A-Z]{2})%' AND UID > (\d+) ORDER BY UID$")
COUNT_RE = re.compile(r"SELECT COUNT\(\*\) AS n FROM .* LIKE '([A-Z]{2})%'$")


def raw_row(
    uid: int, bw_id: str, day: str, ec: tuple[Any, str | None] = (None, None), ie: tuple[Any, str | None] = (None, None),
    *, season: int | None = None, sample_status: str | None = None, obs: str | None = "A", remarks: int = 0,
) -> dict[str, Any]:
    """One row as the service returns it (the column names are the real ones)."""
    return {
        "UID": uid, "season": season if season is not None else int(day[:4]), "bathingWaterIdentifier": bw_id, "sampleDate": day,
        "escherichiaColiValue": ec[0], "intestinalEnterococciValue": ie[0], "escherichiaColiStatus": ec[1],
        "intestinalEnterococciStatus": ie[1], "sampleStatus": sample_status, "metadata_observationStatus": obs, "hasRemarks": remarks,
    }


class FakeDiscodata:
    """A scripted HTTP layer: ``fetch(url, timeout)`` answers from in-memory rows, optionally failing first.

    ``script`` is a list consumed one entry per PAGE request (count requests are never scripted): an exception instance is
    raised, ``bytes`` are returned as the reply body, ``None`` means "answer normally". ``cap`` limits the rows of a reply
    (a service-side row cap).
    """

    def __init__(self, rows: Sequence[dict[str, Any]], script: list[Any] | None = None, cap: int | None = None) -> None:
        self.rows = sorted(rows, key=lambda row: row["UID"])
        self.script = list(script or [])
        self.cap = cap
        self.queries: list[str] = []
        self.urls: list[str] = []
        self.counts_override: dict[str, int] = {}

    def _prefix_rows(self, prefix: str) -> list[dict[str, Any]]:
        return [row for row in self.rows if str(row["bathingWaterIdentifier"]).upper().startswith(prefix)]

    def __call__(self, url: str, timeout: float) -> bytes:
        self.urls.append(url)
        query = urllib.parse.parse_qs(urllib.parse.urlparse(url).query)["query"][0]
        self.queries.append(query)
        count = COUNT_RE.match(query)
        if count:
            prefix = count.group(1)
            return json.dumps({"results": [{"n": self.counts_override.get(prefix, len(self._prefix_rows(prefix)))}]}).encode()
        page = PAGE_RE.match(query)
        if page is None:
            return json.dumps({"errors": [{"error": "Your query is not allowed execution...", "errorcode": 10002}]}).encode()
        if self.script:
            step = self.script.pop(0)
            if isinstance(step, BaseException):
                raise step
            if isinstance(step, bytes):
                return step
        size, prefix, after = int(page.group(1)), page.group(2), int(page.group(3))
        found = [row for row in self._prefix_rows(prefix) if row["UID"] > after][: min(size, self.cap or size)]
        return json.dumps({"results": found}).encode()


def make_client(service: Callable[[str, float], bytes], sleeps: list[float] | None = None, **kwargs: Any) -> DiscodataClient:
    """A client with no real waiting: the sleeps are recorded (or dropped) and the clock never advances."""
    record = sleeps if sleeps is not None else []
    return DiscodataClient(fetch=service, sleep=record.append, clock=lambda: 0.0, min_interval=kwargs.pop("min_interval", 0.0), **kwargs)


def transient(message: str = "HTTP 503", retry_after: float | None = None) -> TransientFetchError:
    return TransientFetchError(message, retry_after)


def dataset() -> list[dict[str, Any]]:
    """Greece (prefix EL) and Italy (prefix IT) rows built so that every hand computation in the tests is small.

    ITSYN001: period A (2020-05..2020-08) E. coli 10,20,30,40 and enterococci 1,2,3,4; a May 2021 sample (7, 7); period B
    (2022-05..2022-08) E. coli 100,200,300 plus a limit-of-detection row (number 1), a missing row (placeholder 0) and a
    confirmed high value 900; enterococci 5,6,7,8,9. ITSYN002 has samples in A only, ITSYN003 has 4 in A and 2 in B,
    ITSYN004 has 3 in each period (E. coli 50,60,70 then 5,6,7).
    """
    rows: list[dict[str, Any]] = []
    uid = 1000

    def add(bw_id: str, day: str, ec: tuple[Any, str | None], ie: tuple[Any, str | None], **extra: Any) -> None:
        nonlocal uid
        uid += 1
        rows.append(raw_row(uid, bw_id, day, ec, ie, **extra))

    for index, day in enumerate(("2020-05-10", "2020-06-10", "2020-07-10", "2020-08-10"), start=1):
        add("ITSYN001", day, (index * 10, None), (index, None))
    add("ITSYN001", "2021-05-15", (7, None), (7, None))
    add("ITSYN001", "2022-05-10", (100, None), (5, None))
    add("ITSYN001", "2022-06-10", (200, None), (6, None))
    add("ITSYN001", "2022-07-10", (300, None), (7, None))
    add("ITSYN001", "2022-08-10", (1, "limitOfDetectionValue"), (8, None))
    add("ITSYN001", "2022-08-20", (0, "missingValue"), (0, "missingValue"), sample_status="missingSample")
    add("ITSYN001", "2022-08-25", (900, "confirmedValue"), (9, None), sample_status="confirmationSample", remarks=1)
    for day in ("2020-05-12", "2020-06-12", "2020-07-12", "2020-08-12"):
        add("ITSYN002", day, (15, None), (3, None))
    for day in ("2020-05-14", "2020-06-14", "2020-07-14", "2020-08-14"):
        add("ITSYN003", day, (11, None), (2, None))
    for day in ("2022-06-14", "2022-07-14"):
        add("ITSYN003", day, (12, None), (2, None))
    for ec, day in ((50, "2020-06-01"), (60, "2020-07-01"), (70, "2020-08-01")):
        add("ITSYN004", day, (ec, None), (ec // 10, None))
    for ec, day in ((5, "2022-06-01"), (6, "2022-07-01"), (7, "2022-08-01")):
        add("ITSYN004", day, (ec, None), (ec, None))
    # Greece (written EL in the identifier): stored as GR.
    for day, ec in (("2023-05-05", 20), ("2023-06-05", 22), ("2023-07-05", 24)):
        add("ELSYN001", day, (ec, None), (ec // 2, None), sample_status="preSeasonSample" if day == "2023-05-05" else None)
    add("ELSYN001", "2023-08-05", (9, "limitOfDetectionValue"), (4, "limitOfDetectionValue"))
    add("ELSYN002", "2023-06-15", (31, None), (None, None))  # a value that is absent without a status
    add("ELSYN002", "2023-07-15", (-3, None), (5, "weirdStatus"))  # a negative number, and a status the project has not seen
    return rows


def build_fixture_store(
    tmp_path: Path, rows: Sequence[dict[str, Any]] | None = None, name: str = "samples.sqlite", **kwargs: Any
) -> Path:
    """Build a store from the SYNTHETIC rows through the real build code (a scripted fake service, no waiting)."""
    target = tmp_path / name
    service = FakeDiscodata(dataset() if rows is None else rows)
    build_store(make_client(service), target, tmp_path / (name + ".work"), page_size=kwargs.pop("page_size", 5), build_date="2026-10-03T00:00:00Z", **kwargs)
    return target
