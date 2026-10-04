"""Where a batch of sandbox data came from and how old it is.

A response labelled ``real-sandbox`` may be built from a local snapshot when the live sandbox is
unreachable. The reader must be able to tell, so every real-data response carries this record.
"""
from __future__ import annotations

from collections.abc import Iterable
from typing import Literal, TypedDict
from oah.timeutil import format_utc, from_epoch_seconds, utc_now

Status = Literal["live", "snapshot", "snapshot-stale", "unknown"]

# Worst last: combining several sources reports the least trustworthy one.
_RANK: dict[str, int] = {"live": 0, "snapshot": 1, "snapshot-stale": 2, "unknown": 3}


class DataFreshness(TypedDict):
    status: Status
    as_of: str | None
    age_seconds: float | None


def make_freshness(status: Status, as_of_epoch: float | None, now_epoch: float | None = None) -> DataFreshness:
    """Build a freshness record from the epoch time the data was obtained."""
    if as_of_epoch is None:
        return {"status": status, "as_of": None, "age_seconds": None}
    now = utc_now().timestamp() if now_epoch is None else now_epoch
    return {
        "status": status,
        "as_of": format_utc(from_epoch_seconds(as_of_epoch)),
        "age_seconds": round(max(0.0, now - as_of_epoch), 1),
    }


def worst_status(first: Status, second: Status) -> Status:
    """The less trustworthy of two statuses (the order of ``combine_freshness``)."""
    return first if _RANK[first] >= _RANK[second] else second


def unknown_freshness() -> DataFreshness:
    return {"status": "unknown", "as_of": None, "age_seconds": None}


def combine_freshness(items: Iterable[DataFreshness]) -> DataFreshness:
    """Least trustworthy status and oldest ``as_of`` among ``items``; unknown when there are none."""
    records = list(items)
    if not records:
        return unknown_freshness()
    status = max((record["status"] for record in records), key=lambda value: _RANK[value])
    dated = [record for record in records if record["as_of"] is not None]
    oldest = min(dated, key=lambda record: record["as_of"] or "") if dated else None
    return {
        "status": status,
        "as_of": oldest["as_of"] if oldest else None,
        "age_seconds": oldest["age_seconds"] if oldest else None,
    }
