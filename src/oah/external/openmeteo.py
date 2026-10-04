"""Open-Meteo: ERA5 weather (Historical Weather API) and GloFAS river discharge (Flood API), as MONTHLY aggregates.

What the numbers are (docs/external_context.md):

* weather: ERA5 reanalysis for the grid cell nearest the (rounded) site point, requested with ``models=era5`` and
  ``timezone=GMT`` so a day is a UTC day. Daily ``precipitation_sum`` (mm) and ``temperature_2m_mean`` (degrees C) are
  aggregated here into monthly values: the SUM of the daily precipitation and the MEAN of the daily mean temperature
  over the days that have a value, with ``n_days`` and ``coverage`` (days with a value over days of the month inside
  the requested period). MODELLED values, not measurements at the site.
* discharge: GloFAS v4 consolidated daily ``river_discharge`` (m3/s) of the nearest river cell, aggregated as the MEAN
  of the daily values per month. MODELLED, not a gauge; the nearest cell may be another river than the site's.

A day without a value (``null`` in the answer) is never filled: it lowers ``coverage``. Nothing is shifted or
extrapolated: a period outside what the provider holds is reported (``period-outside-data``), the real end of the data
is read from the nulls of the answer.
"""
from __future__ import annotations

import math
from dataclasses import dataclass
from datetime import date, timedelta
from typing import Any

from oah.external import coords
from oah.external.constants import (
    ARCHIVE_FIRST_DAY,
    ARCHIVE_HOST,
    ARCHIVE_PATH,
    DISCHARGE_MAX_M3S,
    DISCHARGE_MODEL,
    DISCHARGE_VARIABLES,
    ERA5_DELAY_DAYS,
    FLAG_BEYOND_DOCUMENTED_HISTORY,
    FLAG_ERA5_DELAY,
    FLAG_IMPLAUSIBLE_IGNORED,
    FLAG_NEAREST_CELL,
    FLAG_PARTIAL_MONTH,
    FLAG_PERIOD_END_CLIPPED,
    FLAG_PERIOD_OUTSIDE_DATA,
    FLAG_PERIOD_START_CLIPPED,
    FLAG_SITE_NOT_A_RIVER,
    FLOOD_DOCUMENTED_LAST_DAY,
    FLOOD_FIRST_DAY,
    FLOOD_HOST,
    FLOOD_PATH,
    MAX_SPAN_DAYS,
    PRECIPITATION_DAILY_MAX_MM,
    PROVIDER_DISCHARGE,
    PROVIDER_WEATHER,
    REASON_BAD_RESPONSE,
    STATUS_NO_DATA,
    STATUS_OK,
    TEMPERATURE_MAX_C,
    TEMPERATURE_MIN_C,
    WEATHER_MODEL,
    WEATHER_VARIABLES,
)
from oah.external.envelope import ExternalInputError, envelope, unavailable, validate_period
from oah.external.http import ExternalError
from oah.external.runtime import ExternalRuntime
from oah.external.sites import CATEGORY_RIVER, LocatedSite

MAX_SERIES_DAYS = MAX_SPAN_DAYS + 2


def request_units(days: int, variables: int) -> float:
    """Estimated call units of one request, after the provider's rule for long requests.

    The pricing page (read 2026-10-03) counts a request over more than 10 variables or more than 2 weeks as several calls
    and gives the examples 2 weeks with 15 variables = 1.5 calls and 4 weeks = 3.0 calls, which fit
    ``(days / 14) * (variables / 10)`` with a minimum of 1. The exact rule is UNVERIFIED; the estimate is what the budget
    of this project charges.
    """
    return max(1.0, days / 14.0) * max(1.0, variables / 10.0)


@dataclass(frozen=True)
class DailySeries:
    """The parsed daily answer: the cell used by the provider and ``None`` for a day without a usable value."""

    grid_latitude: float | None
    grid_longitude: float | None
    days: tuple[date, ...]
    values: dict[str, tuple[float | None, ...]]
    implausible: int  # values dropped because they were outside the sanity bounds


def _number(value: object) -> float | None:
    if isinstance(value, bool) or not isinstance(value, (int, float)):
        return None
    return float(value) if math.isfinite(float(value)) else None


def parse_daily(
    payload: dict[str, Any], variables: tuple[str, ...], start: date, end: date, bounds: dict[str, tuple[float, float]]
) -> DailySeries:
    """Validate and extract ``payload['daily']``; ``ExternalError`` (bad-response) when it does not fit the request."""
    if payload.get("error"):
        raise ExternalError(REASON_BAD_RESPONSE, "provider reported an error in a 200 answer")
    daily = payload.get("daily")
    if not isinstance(daily, dict):
        raise ExternalError(REASON_BAD_RESPONSE, "daily block missing")
    times = daily.get("time")
    if not isinstance(times, list) or not 0 < len(times) <= MAX_SERIES_DAYS:
        raise ExternalError(REASON_BAD_RESPONSE, "daily time axis missing or too long")
    try:
        days = tuple(date.fromisoformat(item) for item in times)
    except (TypeError, ValueError) as error:
        raise ExternalError(REASON_BAD_RESPONSE, "daily time axis has an invalid date") from error
    if any(later <= earlier for earlier, later in zip(days, days[1:], strict=False)) or days[0] < start or days[-1] > end:
        raise ExternalError(REASON_BAD_RESPONSE, "daily time axis is unordered or outside the request")
    values: dict[str, tuple[float | None, ...]] = {}
    implausible = 0
    for name in variables:
        raw = daily.get(name)
        if not isinstance(raw, list) or len(raw) != len(days):
            raise ExternalError(REASON_BAD_RESPONSE, f"variable {name} missing or of the wrong length")
        low, high = bounds[name]
        cleaned: list[float | None] = []
        for item in raw:
            number = _number(item)
            if item is not None and number is None:
                raise ExternalError(REASON_BAD_RESPONSE, f"variable {name} holds a non-number")
            if number is not None and not low <= number <= high:
                implausible += 1
                number = None
            cleaned.append(number)
        values[name] = tuple(cleaned)
    grid_lat, grid_lon = _number(payload.get("latitude")), _number(payload.get("longitude"))
    return DailySeries(grid_lat, grid_lon, days, values, implausible)


def month_key(day: date) -> str:
    return f"{day.year:04d}-{day.month:02d}"


def window_months(start: date, end: date) -> list[tuple[str, int]]:
    """``(YYYY-MM, days of that month inside [start, end])`` for every month the window touches, oldest first."""
    months: list[tuple[str, int]] = []
    day = start
    while day <= end:
        first_of_next = date(day.year + (day.month == 12), day.month % 12 + 1, 1)
        last = min(end, first_of_next - timedelta(days=1))
        months.append((month_key(day), (last - day).days + 1))
        day = first_of_next
    return months


def _collect(series: DailySeries, variable: str) -> dict[str, list[float]]:
    by_month: dict[str, list[float]] = {}
    for day, value in zip(series.days, series.values[variable], strict=True):
        if value is not None:
            by_month.setdefault(month_key(day), []).append(value)
    return by_month


def _coverage(n: int, expected: int) -> float:
    return round(n / expected, 3) if expected else 0.0


def _grid_block(series: DailySeries, lat: float, lon: float, resolution_note: str) -> dict[str, Any]:
    distance = None
    if series.grid_latitude is not None and series.grid_longitude is not None:
        distance = round(coords.distance_km(lat, lon, series.grid_latitude, series.grid_longitude), 1)
    return {
        "requested_latitude": lat, "requested_longitude": lon,
        "grid_latitude": series.grid_latitude, "grid_longitude": series.grid_longitude,
        "distance_km": distance, "resolution_note": resolution_note,
    }


def _clip(date_from: date, date_to: date, first_day: date, last_day: date) -> tuple[date, date, list[str]] | None:
    """The part of the period the provider can hold, with the clipping flags; None when nothing overlaps."""
    if date_to < first_day or date_from > last_day:
        return None
    flags: list[str] = []
    start, end = date_from, date_to
    if start < first_day:
        start = first_day
        flags.append(FLAG_PERIOD_START_CLIPPED)
    if end > last_day:
        end = last_day
        flags.append(FLAG_PERIOD_END_CLIPPED)
    return start, end, flags


# --- weather ----------------------------------------------------------------------------------------------------


def _weather_limits(today: date) -> dict[str, Any]:
    return {
        "first_day": ARCHIVE_FIRST_DAY.isoformat(),
        "last_day_requestable": today.isoformat(),
        "era5_delay_days": ERA5_DELAY_DAYS,
        "latest_day_expected_final": (today - timedelta(days=ERA5_DELAY_DAYS)).isoformat(),
        "model": WEATHER_MODEL,
        "day_boundary": "UTC",
    }


def weather_context(
    runtime: ExternalRuntime, site: LocatedSite, date_from: date, date_to: date, today: date
) -> dict[str, Any]:
    """Monthly ERA5 precipitation and temperature around ``site`` for the period. Never raises for a provider problem.

    ``ExternalInputError`` is raised for an inverted or too long period. ``today`` is the UTC date (injected for tests).
    """
    validate_period(date_from, date_to, MAX_SPAN_DAYS)
    lat, lon = coords.rounded(site.latitude, site.longitude)
    base: dict[str, Any] = {
        "dataset": "ERA5 reanalysis (ECMWF) through Open-Meteo, monthly aggregates of daily values",
        "period": {"date_from": date_from.isoformat(), "date_to": date_to.isoformat()},
        "data_limits": _weather_limits(today),
        "grid": None,
        "months": [],
        "n_days_expected": 0,
        "n_days_with_data": 0,
    }
    clipped = _clip(date_from, date_to, ARCHIVE_FIRST_DAY, today)
    if clipped is None:
        return envelope(PROVIDER_WEATHER, STATUS_NO_DATA, flags=[FLAG_PERIOD_OUTSIDE_DATA], **base)
    start, end, flags = clipped
    if end > today - timedelta(days=ERA5_DELAY_DAYS):
        flags.append(FLAG_ERA5_DELAY)
    days = (end - start).days + 1
    bounds = {
        "precipitation_sum": (0.0, PRECIPITATION_DAILY_MAX_MM),
        "temperature_2m_mean": (TEMPERATURE_MIN_C, TEMPERATURE_MAX_C),
    }

    def produce() -> DailySeries:
        params = [
            ("latitude", f"{lat:.2f}"), ("longitude", f"{lon:.2f}"),
            ("start_date", start.isoformat()), ("end_date", end.isoformat()),
            ("daily", ",".join(WEATHER_VARIABLES)), ("timezone", "GMT"), ("models", WEATHER_MODEL),
        ]
        payload = runtime.call(
            PROVIDER_WEATHER, ARCHIVE_HOST, ARCHIVE_PATH, params, units=request_units(days, len(WEATHER_VARIABLES))
        )
        return parse_daily(payload, WEATHER_VARIABLES, start, end, bounds)

    try:
        series, cached = runtime.cached(("weather", lat, lon, start, end), produce)
    except ExternalError as error:
        return _unavailable(PROVIDER_WEATHER, error.reason, base, flags)
    rain, temp = _collect(series, "precipitation_sum"), _collect(series, "temperature_2m_mean")
    months: list[dict[str, Any]] = []
    for month, expected in window_months(start, end):
        n_rain, n_temp = len(rain.get(month, [])), len(temp.get(month, []))
        entry_flags: list[str] = []
        if max(n_rain, n_temp) == 0:
            entry_flags.append(FLAG_PERIOD_OUTSIDE_DATA)
        elif min(n_rain, n_temp) < expected:
            entry_flags.append(FLAG_PARTIAL_MONTH)
        months.append(
            {
                "month": month,
                "days_in_window": expected,
                "precipitation_sum_mm": round(sum(rain[month]), 2) if n_rain else None,
                "precipitation_n_days": n_rain,
                "precipitation_coverage": _coverage(n_rain, expected),
                "temperature_mean_c": round(sum(temp[month]) / n_temp, 2) if n_temp else None,
                "temperature_n_days": n_temp,
                "temperature_coverage": _coverage(n_temp, expected),
                "flags": entry_flags,
            }
        )
    with_data = sum(1 for value in series.values["precipitation_sum"] if value is not None)
    if series.implausible:
        flags.append(FLAG_IMPLAUSIBLE_IGNORED)
    if with_data == 0 and not any(v is not None for v in series.values["temperature_2m_mean"]):
        flags.append(FLAG_PERIOD_OUTSIDE_DATA)
    status = STATUS_OK if FLAG_PERIOD_OUTSIDE_DATA not in flags else STATUS_NO_DATA
    fields = {**base, "grid": _grid_block(series, lat, lon, "ERA5 grid 0.25 degrees (about 25 km)"),
              "months": months, "n_days_expected": days, "n_days_with_data": with_data}
    return envelope(PROVIDER_WEATHER, status, flags=flags, cached=cached, **fields)


def _unavailable(provider: str, reason: str, base: dict[str, Any], flags: list[str]) -> dict[str, Any]:
    return unavailable(provider, reason, flags=flags, **base)


# --- river discharge ----------------------------------------------------------------------------------------------


def _discharge_limits(today: date) -> dict[str, Any]:
    return {
        "first_day": FLOOD_FIRST_DAY.isoformat(),
        "documented_history_end": FLOOD_DOCUMENTED_LAST_DAY.isoformat(),
        "documented_history_note": (
            "The provider documents the GloFAS reanalysis as 1984 to July 2022; later months are served if the provider "
            "holds them (see data_range of the answer), and are flagged."
        ),
        "last_day_requestable": today.isoformat(),
        "model": DISCHARGE_MODEL,
        "day_boundary": "UTC",
    }


def discharge_context(
    runtime: ExternalRuntime, site: LocatedSite, date_from: date, date_to: date, today: date
) -> dict[str, Any]:
    """Monthly mean GloFAS river discharge of the cell nearest ``site``. Never raises for a provider problem."""
    validate_period(date_from, date_to, MAX_SPAN_DAYS)
    lat, lon = coords.rounded(site.latitude, site.longitude)
    flags: list[str] = [FLAG_NEAREST_CELL]
    if site.water_category is not None and site.water_category != CATEGORY_RIVER:
        flags.append(FLAG_SITE_NOT_A_RIVER)
    base: dict[str, Any] = {
        "dataset": "GloFAS v4 consolidated river discharge through Open-Meteo, monthly means of daily values",
        "period": {"date_from": date_from.isoformat(), "date_to": date_to.isoformat()},
        "data_limits": _discharge_limits(today),
        "site_water_category": site.water_category,
        "grid": None,
        "data_range": None,
        "months": [],
        "n_days_expected": 0,
        "n_days_with_data": 0,
    }
    clipped = _clip(date_from, date_to, FLOOD_FIRST_DAY, today)
    if clipped is None:
        return envelope(PROVIDER_DISCHARGE, STATUS_NO_DATA, flags=[*flags, FLAG_PERIOD_OUTSIDE_DATA], **base)
    start, end, clip_flags = clipped
    flags.extend(clip_flags)
    days = (end - start).days + 1
    bounds = {"river_discharge": (0.0, DISCHARGE_MAX_M3S)}

    def produce() -> DailySeries:
        params = [
            ("latitude", f"{lat:.2f}"), ("longitude", f"{lon:.2f}"),
            ("start_date", start.isoformat()), ("end_date", end.isoformat()),
            ("daily", ",".join(DISCHARGE_VARIABLES)), ("models", DISCHARGE_MODEL),
        ]
        payload = runtime.call(
            PROVIDER_DISCHARGE, FLOOD_HOST, FLOOD_PATH, params, units=request_units(days, len(DISCHARGE_VARIABLES))
        )
        return parse_daily(payload, DISCHARGE_VARIABLES, start, end, bounds)

    try:
        series, cached = runtime.cached(("discharge", lat, lon, start, end), produce)
    except ExternalError as error:
        return _unavailable(PROVIDER_DISCHARGE, error.reason, base, flags)
    flow = _collect(series, "river_discharge")
    months: list[dict[str, Any]] = []
    for month, expected in window_months(start, end):
        n = len(flow.get(month, []))
        entry_flags: list[str] = []
        if n == 0:
            entry_flags.append(FLAG_PERIOD_OUTSIDE_DATA)
        else:
            if n < expected:
                entry_flags.append(FLAG_PARTIAL_MONTH)
            year, number = int(month[:4]), int(month[5:])
            if date(year, number, 1) > FLOOD_DOCUMENTED_LAST_DAY:
                entry_flags.append(FLAG_BEYOND_DOCUMENTED_HISTORY)
        months.append(
            {
                "month": month,
                "days_in_window": expected,
                "river_discharge_mean_m3s": round(sum(flow[month]) / n, 2) if n else None,
                "n_days": n,
                "coverage": _coverage(n, expected),
                "flags": entry_flags,
            }
        )
    with_data = [day for day, value in zip(series.days, series.values["river_discharge"], strict=True) if value is not None]
    if series.implausible:
        flags.append(FLAG_IMPLAUSIBLE_IGNORED)
    data_range = {"first_day": with_data[0].isoformat(), "last_day": with_data[-1].isoformat()} if with_data else None
    if not with_data:
        flags.append(FLAG_PERIOD_OUTSIDE_DATA)
    fields = {**base, "grid": _grid_block(series, lat, lon, "GloFAS grid 0.05 degrees (about 5 km)"), "months": months,
              "data_range": data_range, "n_days_expected": days, "n_days_with_data": len(with_data)}
    return envelope(PROVIDER_DISCHARGE, STATUS_OK if with_data else STATUS_NO_DATA, flags=flags, cached=cached, **fields)


__all__ = [
    "DailySeries", "ExternalInputError", "discharge_context", "month_key", "parse_daily", "request_units",
    "weather_context", "window_months",
]
