"""SQLite user-defined aggregates and the read guard shared by the country-scope comparisons (Waterbase and bathing samples).

Both stores aggregate INSIDE SQLite (one row per site and window reaches Python). This module holds the three small pieces
that make it exact and bounded:

* ``ExactSum``: the correctly rounded exact sum of its arguments (Shewchuk partials, as ``math.fsum``). SQLite's own ``SUM``
  rounds differently from ``math.fsum`` (and differently from one SQLite version to the next), so it cannot reproduce the
  row path bit for bit;
* ``MonthMask``: the bit mask of the months with data (bit ``value`` set), so the union over sites is an OR;
* ``ReadGuard``: a hard cap on the rows scanned and a wall-clock cap; when either trips the running statement fails and
  ``ReadGuard.reason`` says why (the caller raises ``oah.indices.scope_guard.ScopeTooLarge``).
"""
from __future__ import annotations

import math
import sqlite3
import time

PROGRESS_STEPS = 20_000  # SQLite virtual-machine instructions between two clock checks


class ReadGuard:
    """Counts the rows scanned and the elapsed time of one read; trips through an SQLite error, leaving ``reason``."""

    def __init__(self, row_cap: int, seconds: float) -> None:
        self.row_cap, self.rows = row_cap, 0
        self.deadline = time.monotonic() + seconds
        self.reason = ""

    def count_row(self) -> None:
        self.rows += 1
        if self.rows > self.row_cap:
            self.reason = f"the comparison would scan more than {self.row_cap:,} rows"
            raise RuntimeError(self.reason)

    def progress(self) -> int:
        if time.monotonic() > self.deadline:
            self.reason = "the comparison ran longer than the allowed time"
            return 1  # a non-zero value interrupts the running statement
        return 0


class ExactSum:
    """Aggregate: the correctly rounded exact sum of the non-NULL arguments; NULL when there are none."""

    guard: ReadGuard | None = None  # set on the subclass ``register`` creates

    def __init__(self) -> None:
        self.partials: list[float] = []
        self.any = False

    def step(self, value: float | None) -> None:
        if self.guard is not None:
            self.guard.count_row()
        if value is None:
            return
        self.any = True
        x = float(value)
        i = 0
        for y in self.partials:
            if abs(x) < abs(y):
                x, y = y, x
            high = x + y
            low = y - (high - x)
            if low:
                self.partials[i] = low
                i += 1
            x = high
        self.partials[i:] = [x]

    def finalize(self) -> float | None:
        return math.fsum(self.partials) if self.any else None


class MonthMask:
    """Aggregate: the bit mask of the non-NULL, non-negative integer arguments, as little-endian bytes; NULL when empty."""

    def __init__(self) -> None:
        self.mask = 0

    def step(self, value: int | None) -> None:
        if value is not None and value >= 0:
            self.mask |= 1 << int(value)

    def finalize(self) -> bytes | None:
        return self.mask.to_bytes((self.mask.bit_length() + 7) // 8, "little") if self.mask else None


def register(connection: sqlite3.Connection, guard: ReadGuard) -> None:
    """Install ``oah_fsum``, ``oah_months`` and the guard's clock on a connection (one read; closing the connection ends it)."""
    connection.create_aggregate("oah_fsum", 1, type("GuardedExactSum", (ExactSum,), {"guard": guard}))
    connection.create_aggregate("oah_months", 1, MonthMask)  # type: ignore[arg-type]
    connection.set_progress_handler(guard.progress, PROGRESS_STEPS)


def mask_value(blob: bytes | None) -> int:
    """The integer of a ``MonthMask`` result (0 for NULL)."""
    return int.from_bytes(blob, "little") if blob else 0
