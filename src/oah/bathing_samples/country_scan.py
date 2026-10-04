"""The country-scope read of the samples store: ONE sequential pass per indicator, exact, bounded.

A country comparison needs, per bathing water and per period, the number of quantified samples, their sum, minimum and
maximum, the calendar months that have a value, and the exact median. Earlier versions asked SQLite for each of those in a
separate pass over the whole table (about twelve passes in all, 61 s for Italy). Here the partial index
``idx_samples_<indicator>_quantified`` (country, bathing water, value, date; only kinds Q and C) is read once, bathing water
by bathing water, and a small user-defined aggregate (``WindowScan``) collects the values of each period. Nothing is
approximated: the values are integers, so sum, minimum and maximum are exact; the median is taken on the sorted integers of
one bathing water exactly as ``statistics.median`` does (the middle value, or the mean of the two middle ones).

Memory is the values of ONE bathing water at a time (the aggregate frees them when the group ends); only one record per
bathing water reaches the caller.
"""
from __future__ import annotations

import json
import sqlite3
from collections.abc import Sequence

from oah.indices.sqlite_aggregates import PROGRESS_STEPS, ReadGuard


def month_start(position: int) -> str:
    return f"{position // 12:04d}-{position % 12 + 1:02d}-01"


def month_end(position: int) -> str:
    return f"{position // 12:04d}-{position % 12 + 1:02d}-31"  # every day of the month sorts at or before the 31st


def _median(sorted_values: list[int]) -> float:
    middle = len(sorted_values) // 2
    if len(sorted_values) % 2:
        return float(sorted_values[middle])
    return (sorted_values[middle - 1] + sorted_values[middle]) / 2  # the mean of two integers, as statistics.median


def register(connection: sqlite3.Connection, guard: ReadGuard, windows: Sequence[tuple[int, int]]) -> None:
    """Install ``oah_window_scan(value, day)`` for ``windows`` (month positions, inclusive) and the guard's clock."""
    bounds = tuple((month_start(first), month_end(last), first) for first, last in windows)

    class WindowScan:
        """Aggregate over (value, sample date): per window the sorted values and the months seen; the result is JSON text,
        a list with one entry per window, ``null`` when no value fell inside it, else
        ``[n, sum, min, max, month mask, median]``."""

        def __init__(self) -> None:
            self.values: list[list[int]] = [[] for _ in bounds]
            self.months: list[set[str]] = [set() for _ in bounds]

        def step(self, value: int | None, day: str | None) -> None:
            if value is None or day is None:
                return
            found = False
            for index, (start, end, _first) in enumerate(bounds):
                if start <= day <= end:
                    self.values[index].append(value)
                    self.months[index].add(day[:7])
                    found = True
            if found:
                guard.count_row()

        def finalize(self) -> str:
            result: list[list[float | int] | None] = []
            for index, (_start, _end, first) in enumerate(bounds):
                values = sorted(self.values[index])
                if not values:
                    result.append(None)
                    continue
                mask = 0
                for month in self.months[index]:
                    mask |= 1 << (int(month[:4]) * 12 + int(month[5:7]) - 1 - first)
                result.append([len(values), sum(values), values[0], values[-1], mask, _median(values)])
            return json.dumps(result)

    connection.create_aggregate("oah_window_scan", 2, WindowScan)  # type: ignore[arg-type]
    connection.set_progress_handler(guard.progress, PROGRESS_STEPS)


def span(windows: Sequence[tuple[int, int]]) -> tuple[str, str]:
    """The first and last date string that any window can contain (the index range the scan reads)."""
    return min(month_start(first) for first, _last in windows), max(month_end(last) for _first, last in windows)


def parse(text: str) -> list[list[float] | None]:
    """The decoded result of one bathing water (see ``WindowScan``)."""
    decoded: list[list[float] | None] = json.loads(text)
    return decoded
