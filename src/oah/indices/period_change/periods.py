"""Inputs of the period comparison: months, periods, monthly cells and the site and parameter contexts. Pure."""
from __future__ import annotations

import re
from dataclasses import dataclass
from typing import Literal


MIN_YEAR = 1900  # accepted year-month range (a sanity bound for input, not a property of the data)
MAX_YEAR = 2100
MAX_PERIOD_MONTHS = 1200  # longest period accepted (100 years)


Resolution = Literal["monthly", "annual-only"]
_YEAR_MONTH = re.compile(r"([0-9]{4})-(0[1-9]|1[0-2])")  # ASCII digits only (no look-alike numerals)


class PeriodError(ValueError):
    """A period is malformed, inverted or out of range (the API turns it into a 422)."""


# --- months and periods ---------------------------------------------------------------------------------------------


def month_position(year: int, month: int) -> int:
    """The month as one integer, ``year * 12 + month - 1`` (consecutive months differ by one)."""
    return year * 12 + month - 1


def month_text(position: int) -> str:
    """``YYYY-MM`` of a month position."""
    return f"{position // 12:04d}-{position % 12 + 1:02d}"


def parse_year_month(text: object, name: str = "month") -> int:
    """The month position of ``YYYY-MM`` (years 1900 to 2100); raises ``PeriodError`` otherwise."""
    match = _YEAR_MONTH.fullmatch(text.strip()) if isinstance(text, str) else None
    if match is None or not MIN_YEAR <= int(match.group(1)) <= MAX_YEAR:
        raise PeriodError(f"{name} must be a month written YYYY-MM between {MIN_YEAR}-01 and {MAX_YEAR}-12.")
    return month_position(int(match.group(1)), int(match.group(2)))


@dataclass(frozen=True)
class Period:
    """Calendar months ``first`` to ``last`` inclusive, as month positions."""

    first: int
    last: int

    @property
    def months(self) -> int:
        return self.last - self.first + 1

    @property
    def start(self) -> str:
        return month_text(self.first)

    @property
    def end(self) -> str:
        return month_text(self.last)

    @staticmethod
    def parse(start: object, end: object, name: str) -> Period:
        """A period from two ``YYYY-MM`` texts; ``PeriodError`` when either is malformed, the period is inverted or longer than 100 years."""
        first, last = parse_year_month(start, f"{name}_from"), parse_year_month(end, f"{name}_to")
        if first > last:
            raise PeriodError(f"{name}_from must not be after {name}_to.")
        if last - first + 1 > MAX_PERIOD_MONTHS:
            raise PeriodError(f"A period may span at most {MAX_PERIOD_MONTHS} months.")
        return Period(first, last)

    def intersects(self, first: int, last: int) -> bool:
        return first <= self.last and last >= self.first

    def contains(self, first: int, last: int) -> bool:
        return self.first <= first and last <= self.last


# --- inputs ---------------------------------------------------------------------------------------------------------


@dataclass(frozen=True)
class Cell:
    """What one site holds for one parameter in one month, already in the parameter's unit.

    ``total`` is the sum of the ``n`` quantified values. A cell of an annual-only source (a sandbox aggregate) covers
    ``first_month`` to ``last_month`` and has ``n = 1`` (one aggregate record) and ``total`` its value.
    """

    site_id: str
    first_month: int
    last_month: int
    n: int
    total: float
    low: float | None
    high: float | None
    n_below_loq: int = 0
    n_lower_reliability: int = 0


def monthly_cell(
    site_id: str, month: int, n: int, total: float, low: float | None, high: float | None,
    n_below_loq: int = 0, n_lower_reliability: int = 0,
) -> Cell:
    """A cell of one calendar month (``month`` is a month position)."""
    return Cell(site_id, month, month, n, total, low, high, n_below_loq, n_lower_reliability)


@dataclass(frozen=True)
class SiteContext:
    """What the limit machinery needs to know about a site."""

    site_id: str
    country: str | None
    regime: str  # ``surface`` (a river), ``drinking`` or ``no-limit-regime`` (a lake)
    name: str | None = None


@dataclass(frozen=True)
class ParameterContext:
    """The parameter as listed to the reader, and how it may be compared with a limit."""

    name: str  # the listed name (the closed project name when there is one, else the label)
    unit: str
    group: str
    closed_name: str | None  # key of PARAMETER_UNITS when the project has a limit for it, else None
    measurement_only: bool = False
    resolution: Resolution = "monthly"
    source: str = ""
    unmapped_reason: str = ""  # why no limit exists when the parameter has no closed name (shown with the values)

    @property
    def n_unit(self) -> str:
        return "aggregate-records" if self.resolution == "annual-only" else "samples"
