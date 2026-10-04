"""Per-parameter measurement detail for one Location: the individual values behind its CCME score.

Adds no formula. Every step reuses the functions the index itself uses (``representative_quantity``,
``convert_to_unit``, ``resolve_limit``, ``classify_quantity``, ``classify_range_quantity``,
``resolve_range_limit``, ``saturation_test``), in the same order as ``apply_ccme_wqi_to_sandbox``, so a
record's status here is the status the index gave that Observation. Unlike the index it keeps the records the
index leaves out and says why (``data_quality_flags``), instead of only counting them. See
``docs/api_routes.md`` for the record fields. Pure apart from the overrides file the index also reads.
"""

from __future__ import annotations

import math
from datetime import UTC, date, datetime, timedelta
from typing import Any, Sequence

from oah.config import load_settings
from oah.indices.apply_to_sandbox import _basis_with_verification
from oah.indices.limit_overrides import ensure_overrides_loaded
from oah.indices.oxygen import (
    DISSOLVED_OXYGEN,
    SATURATION_PARAMETER,
    WATER_TEMPERATURE,
    collect_water_temperatures,
    effective_key,
    saturation_test,
)
from oah.indices.regimes import (
    COUNTRY_OXYGEN_DEVIATION_LIMIT,
    COUNTRY_TEMPERATURE_INTERPRETIVE,
    DEFAULT_REGIME,
    SURFACE,
    countries_by_location_ref,
    observation_instant,
    regimes_by_location_ref,
    resolve_limit,
)
from oah.indices.water_parameter_limits import (
    CLOSED_PARAM_MAPPING,
    PARAMETER_UNITS,
    STATISTIC_CODES,
    TWO_SIDED_LIMITS,
    classify_quantity,
    classify_range_quantity,
    convert_to_unit,
    exact_numeric_value,
    is_health_measure_profile,
    is_physically_possible,
    is_water_profile,
    match_closed_parameter,
    representative_quantity,
    resolve_range_limit,
)
from oah.timeutil import TimeError, parse_fhir_time

NOT_SCORED_BASIS = {
    "interpretive-only": (
        "not scored: for this country's classification water temperature only interprets biological data "
        "and derives oxygen saturation (see docs/limits_verification.md)"
    ),
}


def parameter_names() -> list[str]:
    """The closed parameter names a caller may filter by (the names in ``CLOSED_PARAM_MAPPING``), sorted."""
    return sorted({name for name, _limit, _is_lower in CLOSED_PARAM_MAPPING.values()})


def _statistic_name(observation: dict[str, Any], quantity: dict[str, Any]) -> str:
    """Name of the statistic ``representative_quantity`` picked (median, average, or value for a plain Quantity)."""
    for component in observation.get("component") or []:
        codes = [c.get("code") for c in component.get("code", {}).get("coding", [])]
        code = next((c for c in codes if c in STATISTIC_CODES), None)
        if code and component.get("valueQuantity") is quantity:
            return str(code)
    return "value"


def _extreme(observation: dict[str, Any], statistic: str, unit: str) -> float | None:
    """The exact minimum or maximum component, converted to ``unit`` (None when absent or not convertible)."""
    for component in observation.get("component") or []:
        codes = [c.get("code") for c in component.get("code", {}).get("coding", [])]
        quantity = component.get("valueQuantity")
        if statistic in codes and isinstance(quantity, dict):
            exact = exact_numeric_value(quantity)
            return convert_to_unit(exact, quantity.get("code"), unit) if exact is not None else None
    return None


def _period(observation: dict[str, Any]) -> tuple[str | None, str | None]:
    period = observation.get("effectivePeriod")
    if isinstance(period, dict) and (period.get("start") or period.get("end")):
        return period.get("start"), period.get("end")
    single = observation.get("effectiveDateTime") or observation.get("effectiveInstant")
    return (single, single) if isinstance(single, str) else (None, None)


def _overlaps(start: str | None, end: str | None, date_from: date | None, date_to: date | None) -> bool:
    """True when the record's period overlaps [date_from, date_to] (UTC calendar days, both ends included)."""
    if date_from is None and date_to is None:
        return True
    try:
        first = parse_fhir_time(start or end or "").start
        last = parse_fhir_time(end or start or "").end
    except TimeError:
        return False  # a record whose time cannot be read cannot be placed inside a requested window
    if date_from is not None and last <= datetime(date_from.year, date_from.month, date_from.day, tzinfo=UTC):
        return False
    if date_to is not None:
        after = datetime(date_to.year, date_to.month, date_to.day, tzinfo=UTC) + timedelta(days=1)
        if first >= after:
            return False
    return True


def _status_against(value: float, limit: float, is_lower: bool) -> str:
    """Same comparison as the index's failed-measurement count."""
    return "exceeds-limit" if (value < limit if is_lower else value > limit) else "within-limit"


def _record(
    obs: dict[str, Any],
    matched: tuple[str, float, bool],
    regime: str,
    country: str | None,
    temperatures: dict[tuple[str, str], Any],
    location_ref: str,
) -> dict[str, Any]:
    param_name, limit, is_lower = matched
    unit = PARAMETER_UNITS[param_name]
    flags: list[str] = []
    start, end = _period(obs)

    quantity, reason = representative_quantity(obs)
    statistic: str | None = None
    value: float | None = None
    original_unit: str | None = None
    comparator: str | None = None
    low: float | None = None
    high: float | None = None
    blocked = False  # no usable number: the record is shown but excluded
    if quantity is None:
        flags.append(reason or "no-quantity")
        blocked = True
    else:
        statistic = _statistic_name(obs, quantity)
        original_unit = quantity.get("code") or quantity.get("unit")
        comparator = quantity.get("comparator") or None
        low, high = _extreme(obs, "minimum", unit), _extreme(obs, "maximum", unit)
        raw = quantity.get("value")
        if isinstance(raw, (int, float)) and not isinstance(raw, bool) and not math.isfinite(raw):
            flags.append("non-finite-value")
            blocked = True
        elif isinstance(raw, (int, float)) and not isinstance(raw, bool):
            converted = convert_to_unit(float(raw), quantity.get("code"), unit)
            if converted is None:
                flags.append("unit-mismatch")
                blocked = True
            else:
                value = converted
                quantity = {**quantity, "value": converted}
        if comparator:
            flags.append("censored")

    base: dict[str, Any] = {
        "observation_id": obs.get("id"),
        "parameter": param_name,
        "value": value,
        "statistic": statistic,
        "comparator": comparator,
        "min": low,
        "max": high,
        "unit": unit,
        "original_unit": original_unit,
        "period_start": start,
        "period_end": end,
        "scored_value": None,
        "limit": None,
        "limit_unit": unit,
        "limit_type": None,
        "limit_range": None,
        "limit_basis": None,
        "limit_regime": regime,
        "limit_country": country,
        "status": "excluded",
        "data_quality_flags": flags,
        "origin": "real-sandbox",
    }

    if regime == SURFACE and param_name == WATER_TEMPERATURE and country in COUNTRY_TEMPERATURE_INTERPRETIVE:
        return {**base, "status": "not-scored", "limit_basis": NOT_SCORED_BASIS["interpretive-only"],
                "data_quality_flags": flags + ["interpretive-only"]}
    regime_limit = resolve_limit(param_name, limit, regime, observation_instant(obs), country)
    if regime_limit is None:
        return {**base, "status": "not-scored", "limit_basis": _basis_with_verification(param_name, regime, country),
                "data_quality_flags": flags + ["surface-limit-needs-hardness"]}
    limit = regime_limit
    base["limit"], base["limit_type"] = limit, "minimum" if is_lower else "maximum"
    base["limit_basis"] = _basis_with_verification(param_name, regime, country)
    if blocked or quantity is None:
        return base

    value_range = TWO_SIDED_LIMITS.get(param_name)
    oxygen_limit = COUNTRY_OXYGEN_DEVIATION_LIMIT.get(country or "") if regime == SURFACE else None
    scored_name = param_name
    if param_name == DISSOLVED_OXYGEN and oxygen_limit is not None:
        concentration = exact_numeric_value(quantity)
        if concentration is not None and not is_physically_possible(DISSOLVED_OXYGEN, concentration):
            return {**base, "data_quality_flags": flags + ["physically-impossible"]}
        kind, scored = saturation_test(quantity, temperatures.get((location_ref, effective_key(obs) or "")))
        if kind.endswith("temperature"):
            return {**base, "data_quality_flags": flags + [f"{kind}-for-saturation"]}
        scored_name, limit, is_lower = SATURATION_PARAMETER, oxygen_limit, False
        base.update(limit=limit, limit_unit=PARAMETER_UNITS[SATURATION_PARAMETER], limit_type="maximum",
                    limit_basis=_basis_with_verification(SATURATION_PARAMETER, regime, country))
    elif value_range is None:
        kind, scored = classify_quantity(quantity, limit, is_lower)
    else:
        kind, scored = classify_range_quantity(quantity)

    if scored is not None and not is_physically_possible(scored_name, scored):
        return {**base, "data_quality_flags": flags + ["physically-impossible"]}
    if scored is not None and value_range is not None:
        limit, is_lower = resolve_range_limit(scored, *value_range)
        base.update(limit=limit, limit_type="minimum" if is_lower else "maximum", limit_range=list(value_range))
    if scored is not None:
        base.update(scored_value=scored, status=_status_against(scored, limit, is_lower))
        if kind == "pass-by-bound":
            base["data_quality_flags"] = flags + ["censored-bound-counted-as-pass"]
    elif kind == "indeterminate":
        base["status"] = "indeterminate"
    else:
        base["data_quality_flags"] = flags + ["invalid-quantity"]
    return base


def location_known(location_id: str, observations: Sequence[dict[str, Any]], locations: Sequence[dict[str, Any]]) -> bool:
    """True when a Location with this id exists, or an Observation refers to it."""
    ref = f"Location/{location_id}"
    return any(loc.get("id") == location_id for loc in locations) or any(
        (obs.get("subject") or {}).get("reference") == ref for obs in observations
    )


def site_measurement_records(
    observations: Sequence[dict[str, Any]],
    locations: Sequence[dict[str, Any]],
    location_id: str,
    parameter: str | None = None,
    date_from: date | None = None,
    date_to: date | None = None,
) -> list[dict[str, Any]]:
    """One record per water-profile Observation of the Location that matches a closed parameter.

    Sorted by period start, parameter and Observation id. ``parameter`` is an exact closed name from
    ``parameter_names`` (case-insensitive); the date window keeps records whose period overlaps it.
    """
    ensure_overrides_loaded(load_settings().limits_file)
    location_ref = f"Location/{location_id}"
    regime = regimes_by_location_ref(locations).get(location_ref, DEFAULT_REGIME)
    country = countries_by_location_ref(locations).get(location_ref)
    temperatures = collect_water_temperatures(observations)
    wanted = parameter.strip().lower() if parameter else None

    records: list[dict[str, Any]] = []
    for obs in observations:
        if (obs.get("subject") or {}).get("reference") != location_ref:
            continue
        profiles = obs.get("meta", {}).get("profile", [])
        if is_health_measure_profile(profiles) or not is_water_profile(profiles):
            continue
        matched = match_closed_parameter(obs)
        if matched is None or (wanted is not None and matched[0].lower() != wanted):
            continue
        record = _record(obs, matched, regime, country, temperatures, location_ref)
        if _overlaps(record["period_start"], record["period_end"], date_from, date_to):
            records.append(record)
    records.sort(key=lambda r: (str(r["period_start"] or ""), r["parameter"], str(r["observation_id"] or "")))
    return records
