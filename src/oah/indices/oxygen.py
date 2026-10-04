"""Dissolved oxygen as percent saturation, for national classifications that score it that way.

Italy (DM 260/2010, LIMeco) scores oxygen as ``|100 - % saturation|``. The sandbox reports mg/L, so the
saturation is derived from the measured concentration and the water temperature of the same site and
period. Pure module: no I/O.

Formula (Benson and Krause 1984, as in Standard Methods 4500-O G): equilibrium oxygen concentration of
fresh water at 1 atm, ``ln(DO_sat) = -139.34411 + 1.575701e5/T - 6.642308e7/T^2 + 1.243800e10/T^3
- 8.621949e11/T^4`` with ``DO_sat`` in mg/L and ``T`` in kelvin. Pressure (altitude) and salinity are NOT
corrected: the sandbox carries neither, so sites at altitude or in brackish water are approximated.
"""

from __future__ import annotations

import math
from typing import Any, Sequence

from oah.indices.water_parameter_limits import (
    convert_to_unit,
    exact_numeric_value,
    is_health_measure_profile,
    is_water_profile,
    match_closed_parameter,
    representative_quantity,
)
from oah.timeutil import TimeError, parse_fhir_time

DISSOLVED_OXYGEN = "Dissolved Oxygen"
SATURATION_PARAMETER = "Dissolved oxygen saturation deviation"
WATER_TEMPERATURE = "Water temperature"


def oxygen_saturation_mg_per_l(temperature_c: float) -> float:
    """Equilibrium dissolved-oxygen concentration (mg/L) of fresh water at 1 atm and ``temperature_c``."""
    if not math.isfinite(temperature_c) or not 0.0 <= temperature_c <= 40.0:
        raise ValueError(f"temperature must be between 0 and 40 C for this formula, got {temperature_c}.")
    t = temperature_c + 273.15
    return math.exp(-139.34411 + 1.575701e5 / t - 6.642308e7 / t**2 + 1.243800e10 / t**3 - 8.621949e11 / t**4)


def saturation_deviation_percent(oxygen_mg_per_l: float, temperature_c: float) -> float:
    """``|100 - % saturation|`` of a concentration at a temperature (0 = exactly saturated)."""
    return abs(100.0 - 100.0 * oxygen_mg_per_l / oxygen_saturation_mg_per_l(temperature_c))


def _interval_text(value: str) -> tuple[str, str] | None:
    """UTC start and end (ISO text) of a FHIR date/dateTime, or None when it cannot be parsed."""
    try:
        parsed = parse_fhir_time(value)
    except TimeError:
        return None
    return parsed.start.isoformat(), parsed.end.isoformat()


def effective_key(observation: dict[str, Any]) -> str | None:
    """Text identifying the period an Observation covers, used to pair oxygen with temperature.

    Times are normalised to UTC intervals, so ``2020-01-01T00:00:00Z`` and ``2020-01-01T00:00:00+00:00``
    are the same key; two Observations pair only when their normalised intervals are equal (a period and
    an instant inside it do not pair). An unparseable time falls back to its raw text.
    """
    period = observation.get("effectivePeriod")
    if isinstance(period, dict) and (period.get("start") or period.get("end")):
        start = _interval_text(str(period["start"])) if period.get("start") else None
        end = _interval_text(str(period["end"])) if period.get("end") else None
        if (period.get("start") and start is None) or (period.get("end") and end is None):
            return f"{period.get('start')}/{period.get('end')}"
        return f"{start[0] if start else ''}/{end[1] if end else ''}"
    single = observation.get("effectiveDateTime") or observation.get("effectiveInstant")
    if not single:
        return None
    interval = _interval_text(str(single))
    return f"{interval[0]}/{interval[1]}" if interval else str(single)


TemperatureFinding = float | str  # a Celsius value, or the reason it cannot be used: "ambiguous" / "unusable"


def collect_water_temperatures(observations: Sequence[dict[str, Any]]) -> dict[tuple[str, str], TemperatureFinding]:
    """Water temperature per ``(location ref, period key)`` from the water-profile Observations.

    Same profile filters as the index itself (health-measure and non-water profiles are ignored). The
    value is the representative Celsius temperature; a key with two different temperatures is
    ``"ambiguous"`` (never resolved by input order); a temperature that exists but cannot be used (not
    exact, unit not convertible to Cel, outside 0-40 C) is ``"unusable"``.
    """
    values: dict[tuple[str, str], list[float]] = {}
    unusable: set[tuple[str, str]] = set()
    for obs in observations:
        profiles = obs.get("meta", {}).get("profile", [])
        if is_health_measure_profile(profiles) or not is_water_profile(profiles):
            continue
        matched = match_closed_parameter(obs)
        key = effective_key(obs)
        ref = obs.get("subject", {}).get("reference")
        if matched is None or matched[0] != WATER_TEMPERATURE or key is None or not ref:
            continue
        pair = (str(ref), key)
        quantity, _ = representative_quantity(obs)
        exact = exact_numeric_value(quantity) if quantity else None
        celsius = convert_to_unit(exact, quantity.get("code"), "Cel") if quantity and exact is not None else None
        if celsius is None or not 0.0 <= celsius <= 40.0:
            unusable.add(pair)
        else:
            values.setdefault(pair, []).append(celsius)
    found: dict[tuple[str, str], TemperatureFinding] = {}
    for pair, readings in values.items():
        found[pair] = readings[0] if len(set(readings)) == 1 else "ambiguous"
    for pair in unusable:
        found.setdefault(pair, "unusable")
    return found


def saturation_test(quantity: dict[str, Any], temperature: TemperatureFinding | None) -> tuple[str, float | None]:
    """Outcome of one oxygen measurement (mg/L) as a saturation-deviation test.

    ``("exact", deviation)``; ``("no-temperature", None)`` when no temperature of the same site and period
    exists, ``("ambiguous-temperature", None)`` when there are conflicting ones and
    ``("unusable-temperature", None)`` when the only one cannot be used; ``("indeterminate", None)`` for a
    censored value (a comparator bound cannot fix a deviation); ``("invalid", None)`` when there is no
    usable number.
    """
    value = quantity.get("value")
    if quantity.get("comparator"):
        return ("indeterminate", None) if isinstance(value, (int, float)) and not isinstance(value, bool) else ("invalid", None)
    exact = exact_numeric_value(quantity)
    if exact is None:
        return "invalid", None
    if temperature is None:
        return "no-temperature", None
    if isinstance(temperature, str):
        return f"{temperature}-temperature", None
    return "exact", saturation_deviation_percent(exact, temperature)
