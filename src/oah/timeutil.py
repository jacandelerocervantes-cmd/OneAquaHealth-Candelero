"""One time policy for the whole project (see docs/time_policy.md).

Rules:
- Internally every instant is a timezone-aware ``datetime`` in UTC. A naive datetime is never accepted
  as an instant.
- One serialisation: ``format_utc`` (ISO 8601 with the ``+00:00`` offset).
- Elapsed time is computed between UTC instants only. Wall-clock subtraction is wrong across a daylight
  saving change (a local day is 23 or 25 hours long twice a year).
- External FHIR timestamps are parsed with ``parse_fhir_time``, which keeps their precision (a year, a
  month, a day or a second) and returns the UTC interval they denote. A time of day without an offset is
  interpreted only in a timezone the caller names, never guessed, and a local time that does not exist or
  occurs twice at a clock change is reported, not silently resolved.
"""
from __future__ import annotations

import re
from dataclasses import dataclass
from datetime import UTC, date, datetime, timedelta, timezone
from typing import Literal
from zoneinfo import ZoneInfo, ZoneInfoNotFoundError

Precision = Literal["year", "month", "day", "second"]
TzSource = Literal["explicit", "site", "none"]
OnAmbiguous = Literal["raise", "earliest", "latest"]
OnGap = Literal["raise", "shift-forward"]

# Pilot countries only. Greece appears as "EL" (EU convention) or "GR" (ISO); no other country is guessed.
PILOT_TIMEZONES: dict[str, str] = {"EL": "Europe/Athens", "GR": "Europe/Athens", "IT": "Europe/Rome"}

_FHIR_TIME = re.compile(
    r"^(?P<year>\d{4})(?:-(?P<month>\d{2})(?:-(?P<day>\d{2})"
    r"(?:T(?P<hour>\d{2}):(?P<minute>\d{2}):(?P<second>\d{2})(?:\.(?P<fraction>\d+))?"
    r"(?P<offset>Z|[+-]\d{2}:\d{2})?)?)?)?$"
)


_SECOND = timedelta(seconds=1)


class TimeError(ValueError):
    """A timestamp cannot be interpreted under the project's time policy."""


class AmbiguousLocalTime(TimeError):
    """The local time occurs twice because the clocks went back."""


class NonexistentLocalTime(TimeError):
    """The local time does not exist because the clocks went forward."""


@dataclass(frozen=True)
class ParsedTime:
    """The UTC interval ``[start, end)`` a FHIR timestamp denotes, with its original precision."""

    precision: Precision
    start: datetime
    end: datetime
    tz_source: TzSource

    @property
    def instant(self) -> datetime | None:
        """The exact instant, only for second precision."""
        return self.start if self.precision == "second" else None


def utc_now() -> datetime:
    """The current instant, timezone-aware in UTC (the single clock, easy to replace in tests)."""
    return datetime.now(UTC)


def require_aware(value: datetime) -> datetime:
    if value.tzinfo is None or value.utcoffset() is None:
        raise TimeError(f"A naive datetime is not an instant; attach a timezone: {value!r}.")
    return value


def to_utc(value: datetime) -> datetime:
    return require_aware(value).astimezone(UTC)


def format_utc(value: datetime) -> str:
    """The one canonical text form of an instant."""
    return to_utc(value).isoformat()


def from_epoch_seconds(seconds: float) -> datetime:
    return datetime.fromtimestamp(seconds, UTC)


def from_epoch_millis(millis: float) -> datetime:
    """Epoch milliseconds are a distinct input; the unit is never guessed from the magnitude."""
    return datetime.fromtimestamp(millis / 1000.0, UTC)


def zone(name: str) -> ZoneInfo:
    try:
        return ZoneInfo(name)
    except (ZoneInfoNotFoundError, ValueError) as error:
        raise TimeError(f"Unknown timezone {name!r} (is the tzdata package installed?).") from error


def site_timezone(country_code: str) -> str:
    """Timezone name of a pilot country; any other country is refused rather than guessed."""
    try:
        return PILOT_TIMEZONES[country_code.upper()]
    except KeyError as error:
        raise TimeError(f"No timezone is defined for country {country_code!r}; add it explicitly.") from error


def to_local(value: datetime, tz_name: str) -> datetime:
    """Show an instant on a zone's wall clock (display only; keep computing in UTC)."""
    return to_utc(value).astimezone(zone(tz_name))


def elapsed(start: datetime, end: datetime) -> timedelta:
    """True elapsed time between two instants, correct across daylight saving changes."""
    return to_utc(end) - to_utc(start)


def add_local_days(value: datetime, days: int) -> datetime:
    """Add calendar days on the wall clock of ``value``'s own zone (the local hour is kept).

    Adding 24 hours of elapsed time is a different operation; use ``value + timedelta(hours=24)`` for that.
    """
    require_aware(value)
    tz = value.tzinfo
    naive = value.replace(tzinfo=None) + timedelta(days=days)
    return _localize(naive, tz, "raise", "raise") if tz is not None else naive


def _localize(naive: datetime, tz, on_ambiguous: OnAmbiguous, on_gap: OnGap) -> datetime:
    first, second = naive.replace(tzinfo=tz, fold=0), naive.replace(tzinfo=tz, fold=1)
    if first.utcoffset() == second.utcoffset():
        return first

    def survives(candidate: datetime) -> bool:
        return candidate.astimezone(UTC).astimezone(tz).replace(tzinfo=None) == naive

    if survives(first) and survives(second):
        if on_ambiguous == "earliest":
            return first
        if on_ambiguous == "latest":
            return second
        raise AmbiguousLocalTime(f"{naive.isoformat()} occurs twice in {tz}; say which occurrence you mean.")
    if on_gap == "shift-forward":
        return first.astimezone(UTC).astimezone(tz)
    raise NonexistentLocalTime(f"{naive.isoformat()} does not exist in {tz} (clocks went forward).")


def _day_interval(day: date, tz: ZoneInfo | None) -> tuple[datetime, datetime]:
    """[local midnight, next local midnight) in UTC; a day on a clock-change date is 23 or 25 hours."""
    if tz is None:
        start = datetime(day.year, day.month, day.day, tzinfo=UTC)
        return start, start + timedelta(days=1)
    midnight = datetime(day.year, day.month, day.day)
    following = midnight + timedelta(days=1)
    start = _localize(midnight, tz, "earliest", "shift-forward")
    end = _localize(following, tz, "earliest", "shift-forward")
    return start.astimezone(UTC), end.astimezone(UTC)


def parse_fhir_time(
    value: str,
    *,
    site_tz: str | None = None,
    on_ambiguous: OnAmbiguous = "raise",
    on_gap: OnGap = "raise",
) -> ParsedTime:
    """Parse a FHIR ``date``, ``dateTime`` or ``instant`` string into the UTC interval it denotes.

    A year, month or day is an interval on the site's calendar when ``site_tz`` is given, otherwise on the
    UTC calendar (``tz_source == "none"``, an approximation the caller can see). A time of day carries
    its own offset, or needs ``site_tz``; without either the value is rejected.
    """
    match = _FHIR_TIME.match(value.strip())
    if match is None:
        raise TimeError(f"Not a FHIR date or dateTime: {value!r}.")
    parts = match.groupdict()
    tz = zone(site_tz) if site_tz else None
    year, month, day = int(parts["year"]), parts["month"], parts["day"]
    try:
        if parts["hour"] is None:
            if month is None:
                first, last = date(year, 1, 1), date(year + 1, 1, 1)
                precision: Precision = "year"
            elif day is None:
                first = date(year, int(month), 1)
                last = date(year + (int(month) == 12), int(month) % 12 + 1, 1)
                precision = "month"
            else:
                first = date(year, int(month), int(day))
                last = first + timedelta(days=1)
                precision = "day"
            start = _day_interval(first, tz)[0]
            end = _day_interval(last, tz)[0]
            return ParsedTime(precision, start, end, "site" if tz else "none")
        microsecond = int(((parts["fraction"] or "") + "000000")[:6])
        naive = datetime(
            year, int(month), int(day), int(parts["hour"]), int(parts["minute"]), int(parts["second"]), microsecond
        )
    except ValueError as error:
        raise TimeError(f"Not a valid calendar value: {value!r}.") from error
    offset = parts["offset"]
    if offset is not None:
        if offset == "Z":
            aware = naive.replace(tzinfo=UTC)
        else:
            sign = 1 if offset[0] == "+" else -1
            aware = naive.replace(tzinfo=timezone(sign * timedelta(hours=int(offset[1:3]), minutes=int(offset[4:6]))))
        instant = aware.astimezone(UTC)
        return ParsedTime("second", instant, instant + _SECOND, "explicit")
    if tz is None:
        raise TimeError(f"{value!r} has a time of day but no offset; pass site_tz to interpret it.")
    instant = _localize(naive, tz, on_ambiguous, on_gap).astimezone(UTC)
    return ParsedTime("second", instant, instant + _SECOND, "site")
