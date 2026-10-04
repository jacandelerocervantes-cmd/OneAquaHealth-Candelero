"""Annual Waterbase aggregates as measurement records, each judged against the limit that applies (rivers only).

No new formula and no index. The limit comes from the existing machinery (``resolve_limit``, ``limit_basis`` through
``_basis_with_verification``, ``classify_quantity`` / ``classify_range_quantity``, the same comparison as the
sandbox records), applied to the ANNUAL MEAN of the quantified samples. Rules (``docs/waterbase_store.md``):

- rivers (RW) are scored with the ``surface`` regime of the site's country; lakes (LW) have no limit regime and are
  shown with ``limit_regime = "no-limit-regime"`` and status ``not-scored`` (river limits are never applied to lakes);
- a determinand without an exact closed counterpart (or in a matrix the mapping does not hold for) is listed with its
  values and ``not-scored``;
- values below the limit of quantification are not in the mean (``n_below_loq`` counts them); a year with only such
  values is ``indeterminate``;
- Italian dissolved oxygen is ``not-scored``: its national criterion is a per-sample saturation deviation that an
  annual aggregate cannot reproduce; water temperature stays interpretive-only in IT and GR, as in the index.
Pure module apart from the overrides file the limits machinery already reads.
"""

from __future__ import annotations

import calendar
from datetime import UTC, datetime
from collections.abc import Sequence
from typing import Any

from oah.config import load_settings
from oah.indices.apply_to_sandbox import _basis_with_verification
from oah.indices.limit_overrides import ensure_overrides_loaded
from oah.indices.oxygen import DISSOLVED_OXYGEN, WATER_TEMPERATURE
from oah.indices.regimes import (
    COUNTRY_OXYGEN_DEVIATION_LIMIT,
    COUNTRY_TEMPERATURE_INTERPRETIVE,
    SURFACE,
    resolve_limit,
)
from oah.indices.site_measurements import NOT_SCORED_BASIS, _status_against
from oah.indices.water_parameter_limits import (
    CLOSED_PARAM_MAPPING,
    PARAMETER_UNITS,
    TWO_SIDED_LIMITS,
    classify_quantity,
    classify_range_quantity,
    is_physically_possible,
    resolve_range_limit,
)
from oah.waterbase.mapping import (
    ATTRIBUTION,
    DETERMINANDS,
    NO_LIMIT_REGIME,
    SOURCE_ID,
    closed_name,
    listed_name,
    to_project_unit,
    unmapped_reason,
)
from oah.waterbase.store import AnnualRow, MonthlyRow, WaterbaseSite

INDEX_STATUS = "measurements-only"
INDEX_REASON = (
    "No CCME index is computed for EEA Waterbase sites: the store holds annual aggregates only, so the sites are "
    "listed with their measurements (docs/waterbase_store.md)."
)
MEASUREMENT_ONLY_BASIS = (
    "not scored: measurement only; the project has no limit regime for this parameter (docs/waterbase_store.md)"
)
LAKE_BASIS = (
    "not scored: the project's limit regimes cover rivers (surface) and drinking water; no regime is defined for lakes"
)


def regime_of(category: str) -> str:
    """``surface`` for a river, ``no-limit-regime`` for a lake."""
    return SURFACE if category == "RW" else NO_LIMIT_REGIME


def site_entry(site: WaterbaseSite) -> dict[str, Any]:
    """One ``/sites`` entry for a Waterbase site (never evaluated: measurements only)."""
    return {
        "id": site.site_id,
        "name": site.name or site.site_id,
        "latitude": site.lat,
        "longitude": site.lon,
        "kind": "water-body",
        "status": INDEX_STATUS,
        "ccme_wqi": None,
        "ccme_class": None,
        "ui_status": "unavailable",
        "limit_regime": regime_of(site.category),
        "limit_country": site.country,
        "confidence": None,
        "veto_triggered": False,
        "eclipsed": False,
        "reason": INDEX_REASON,
        "origin": SOURCE_ID,
        "source": SOURCE_ID,
        "water_category": site.water_category,
        "location_status": "located" if site.has_location else "no-location",
        "water_body_name": site.water_body_name,
        "first_year": site.first_year,
        "last_year": site.last_year,
    }


def site_info(site: WaterbaseSite) -> dict[str, Any]:
    """The site block of a measurements response."""
    return {
        "id": site.site_id,
        "name": site.name or site.site_id,
        "country": site.country,
        "water_category": site.water_category,
        "water_body_name": site.water_body_name,
        "latitude": site.lat,
        "longitude": site.lon,
        "location_status": "located" if site.has_location else "no-location",
        "confidentiality": site.confidentiality,
        "first_year": site.first_year,
        "last_year": site.last_year,
    }


def _limit_entry(parameter: str) -> tuple[float, bool]:
    _name, limit, is_lower = CLOSED_PARAM_MAPPING[parameter.lower()]
    return limit, is_lower


def annual_record(site: WaterbaseSite, row: AnnualRow) -> dict[str, Any]:
    """One annual aggregate (or, for a ``MonthlyRow``, one monthly aggregate) as a measurement record (see the module
    docstring for the rules). A monthly record has the same fields plus ``month``; its period is that calendar month."""
    flags: list[str] = []
    regime = regime_of(row.category)
    parameter = closed_name(row.determinand, row.matrix)
    determinand = DETERMINANDS.get(row.determinand)
    unit, value, low, high = row.unit, row.mean, row.min, row.max
    blocked = False
    if parameter is not None and determinand is not None and row.mean is not None:
        converted = [
            None if raw is None else to_project_unit(raw, row.unit, determinand) for raw in (row.mean, row.min, row.max)
        ]
        if None in converted:
            flags.append("unit-mismatch")  # the unit label's basis is not the expected one: shown as reported
            blocked = True
        else:
            value, low, high = converted
            unit = PARAMETER_UNITS[parameter]
    elif parameter is not None and row.mean is None:
        unit = PARAMETER_UNITS[parameter]
    if row.n == 0:
        flags.append("all-below-loq")
    elif row.n_below_loq > 0:
        flags.append("below-loq-excluded-from-mean")
    if row.n_lower_reliability > 0:
        flags.append("includes-lower-reliability-records")
    if parameter == "pH" and row.n > 0:
        flags.append("arithmetic-mean-of-ph")

    month = row.month if isinstance(row, MonthlyRow) else None
    last_day = calendar.monthrange(row.year, month)[1] if month is not None else 31
    period_start = f"{row.year}-{month:02d}-01" if month is not None else f"{row.year}-01-01"
    period_end = f"{row.year}-{month:02d}-{last_day:02d}" if month is not None else f"{row.year}-12-31"
    base: dict[str, Any] = {
        "observation_id": (
            f"{row.site_id}|{row.determinand}|{row.matrix}|{row.year}|{row.unit}"
            if month is None
            else f"{row.site_id}|{row.determinand}|{row.matrix}|{row.year}-{month:02d}|{row.unit}"
        ),
        "parameter": listed_name(row.determinand, row.matrix),
        "value": value,
        "statistic": "mean",
        "comparator": None,
        "min": low,
        "max": high,
        "unit": unit,
        "original_unit": row.unit,
        "period_start": period_start,
        "period_end": period_end,
        "scored_value": None,
        "limit": None,
        "limit_unit": None,
        "limit_type": None,
        "limit_range": None,
        "limit_basis": None,
        "limit_regime": regime,
        "limit_country": row.country,
        "status": "not-scored",
        "data_quality_flags": flags,
        "origin": SOURCE_ID,
        "source": SOURCE_ID,
        "year": row.year,
        "month": month,
        "n": row.n,
        "n_below_loq": row.n_below_loq,
        "n_lower_reliability": row.n_lower_reliability,
        "determinand_code": row.determinand,
        "matrix": row.matrix,
        "group": determinand.group if determinand is not None else None,
    }
    if determinand is not None and determinand.measurement_only:
        # No limit regime exists for these determinands (turbidity, solids, organic matter): measurement only, whatever
        # the water category. A unit label other than the one expected is refused, never converted.
        base["limit_regime"] = NO_LIMIT_REGIME
        if row.unit != determinand.expected_unit:
            return {**base, "status": "excluded", "limit_basis": "not compared: unit label does not match the expected unit",
                    "data_quality_flags": flags + ["unit-mismatch", "no-limit-regime"]}
        return {**base, "limit_basis": MEASUREMENT_ONLY_BASIS, "data_quality_flags": flags + ["no-limit-regime", "measurement-only"]}
    if parameter is None:
        return {**base, "limit_basis": f"not compared: {unmapped_reason(row.determinand, row.matrix)}",
                "data_quality_flags": flags + ["no-limit-mapping"]}
    if blocked:
        return {**base, "status": "excluded", "limit_basis": "not compared: unit label does not match the expected basis"}
    if regime == NO_LIMIT_REGIME:
        return {**base, "limit_basis": LAKE_BASIS, "data_quality_flags": flags + ["no-limit-regime"]}

    country = row.country
    if parameter == WATER_TEMPERATURE and country in COUNTRY_TEMPERATURE_INTERPRETIVE:
        return {**base, "limit_basis": NOT_SCORED_BASIS["interpretive-only"], "data_quality_flags": flags + ["interpretive-only"]}
    ensure_overrides_loaded(load_settings().limits_file)
    default_limit, is_lower = _limit_entry(parameter)
    instant = datetime(row.year, month or 12, last_day, 23, 59, 59, tzinfo=UTC)
    limit = resolve_limit(parameter, default_limit, SURFACE, instant, country)
    if limit is None:
        return {**base, "limit_basis": _basis_with_verification(parameter, SURFACE, country),
                "data_quality_flags": flags + ["surface-limit-needs-hardness"]}
    if parameter == DISSOLVED_OXYGEN and country in COUNTRY_OXYGEN_DEVIATION_LIMIT:
        return {**base, "limit_basis": (
            "not scored: the national criterion for this country is the deviation from oxygen saturation of each "
            "sample, which annual aggregates cannot reproduce"),
            "data_quality_flags": flags + ["oxygen-saturation-criterion-not-derivable"]}

    base.update(limit=limit, limit_unit=unit, limit_type="minimum" if is_lower else "maximum",
                limit_basis=_basis_with_verification(parameter, SURFACE, country))
    value_range = TWO_SIDED_LIMITS.get(parameter)
    if value_range is not None:
        base["limit_range"] = list(value_range)
    if value is None:
        return {**base, "status": "indeterminate"}  # only values below the limit of quantification
    quantity = {"value": value}
    kind, scored = classify_range_quantity(quantity) if value_range else classify_quantity(quantity, limit, is_lower)
    if scored is None:
        return {**base, "status": "excluded", "data_quality_flags": flags + ["invalid-quantity"]}
    if not is_physically_possible(parameter, scored):
        return {**base, "status": "excluded", "data_quality_flags": flags + ["physically-impossible"]}
    if value_range is not None:
        limit, is_lower = resolve_range_limit(scored, *value_range)
        base.update(limit=limit, limit_type="minimum" if is_lower else "maximum")
    return {**base, "scored_value": scored, "status": _status_against(scored, limit, is_lower)}


def annual_records(site: WaterbaseSite, rows: Sequence[AnnualRow]) -> list[dict[str, Any]]:
    return [annual_record(site, row) for row in rows]


__all__ = ["ATTRIBUTION", "INDEX_REASON", "INDEX_STATUS", "annual_record", "annual_records", "regime_of", "site_entry", "site_info"]
