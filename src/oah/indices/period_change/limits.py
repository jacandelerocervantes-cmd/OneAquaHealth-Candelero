"""The limit machinery applied to a period mean: the existing ``resolve_limit`` and verification labels, never a new rule."""
from __future__ import annotations

import calendar
from collections.abc import Mapping
from datetime import UTC, datetime
from typing import Any

from oah.config import load_settings
from oah.indices.apply_to_sandbox import _basis_with_verification
from oah.indices.limit_overrides import ensure_overrides_loaded
from oah.indices.oxygen import DISSOLVED_OXYGEN, WATER_TEMPERATURE
from oah.indices.period_change.periods import ParameterContext, SiteContext
from oah.indices.period_change.stats import _out
from oah.indices.regimes import (
    COUNTRY_OXYGEN_DEVIATION_LIMIT,
    COUNTRY_TEMPERATURE_INTERPRETIVE,
    SURFACE,
    resolve_limit,
)
from oah.indices.site_measurements import NOT_SCORED_BASIS, _status_against
from oah.indices.water_parameter_limits import (
    CLOSED_PARAM_MAPPING,
    TWO_SIDED_LIMITS,
    is_physically_possible,
    resolve_range_limit,
)


NO_LIMIT_REGIME = "no-limit-regime"
MEASUREMENT_ONLY_BASIS = (
    "not scored: measurement only; the project has no limit regime for this parameter (docs/waterbase_store.md)"
)
LAKE_BASIS = (
    "not scored: the project's limit regimes cover rivers (surface) and drinking water; no regime is defined for lakes"
)
NO_COUNTERPART_BASIS = "not compared: this determinand has no closed project parameter, so no limit exists for it"
OXYGEN_BASIS = (
    "not scored: the national criterion for this country is the deviation from oxygen saturation of each "
    "sample, which period means cannot reproduce"
)


def _month_end(position: int) -> datetime:
    year, month = divmod(position, 12)
    month += 1
    return datetime(year, month, calendar.monthrange(year, month)[1], 23, 59, 59, tzinfo=UTC)


def assess_mean(
    parameter: ParameterContext, site: SiteContext, mean: float | None, last_month: int
) -> dict[str, Any]:
    """The limit that applies to ``parameter`` at ``site`` on the last day of the period, and the status of ``mean``.

    The same decisions as ``oah.waterbase.measurements.annual_record`` (a parity test keeps them identical): measurement
    only and lakes have no limit; a determinand without a closed name has none; Italian oxygen, Cadmium and the interpretive
    temperature are not scored; every other parameter uses ``resolve_limit`` with the site's regime and country, the limit
    basis with its verification label and the pH range. ``status`` is ``within-limit``, ``exceeds-limit``,
    ``indeterminate`` (no quantified value), ``not-scored`` or ``excluded``.
    """
    out: dict[str, Any] = {
        "limit": None, "limit_unit": None, "limit_type": None, "limit_range": None, "limit_basis": None,
        "limit_regime": site.regime, "status": "not-scored", "scored_value": None, "flags": [],
    }
    if parameter.measurement_only:
        return {**out, "limit_regime": NO_LIMIT_REGIME, "limit_basis": MEASUREMENT_ONLY_BASIS, "flags": ["no-limit-regime", "measurement-only"]}
    if parameter.closed_name is None:
        basis = f"not compared: {parameter.unmapped_reason}" if parameter.unmapped_reason else NO_COUNTERPART_BASIS
        return {**out, "limit_basis": basis, "flags": ["no-limit-mapping"]}
    if site.regime == NO_LIMIT_REGIME:
        return {**out, "limit_basis": LAKE_BASIS, "flags": ["no-limit-regime"]}
    name, country, regime = parameter.closed_name, site.country, site.regime
    if regime == SURFACE and name == WATER_TEMPERATURE and country in COUNTRY_TEMPERATURE_INTERPRETIVE:
        return {**out, "limit_basis": NOT_SCORED_BASIS["interpretive-only"], "flags": ["interpretive-only"]}
    ensure_overrides_loaded(load_settings().limits_file)
    _display, default_limit, is_lower = CLOSED_PARAM_MAPPING[name.lower()]
    limit = resolve_limit(name, default_limit, regime, _month_end(last_month), country)
    if limit is None:
        return {**out, "limit_basis": _basis_with_verification(name, regime, country), "flags": ["surface-limit-needs-hardness"]}
    if name == DISSOLVED_OXYGEN and regime == SURFACE and country in COUNTRY_OXYGEN_DEVIATION_LIMIT:
        return {**out, "limit_basis": OXYGEN_BASIS, "flags": ["oxygen-saturation-criterion-not-derivable"]}
    out.update(
        limit=limit, limit_unit=parameter.unit, limit_type="minimum" if is_lower else "maximum",
        limit_basis=_basis_with_verification(name, regime, country),
    )
    value_range = TWO_SIDED_LIMITS.get(name)
    if value_range is not None:
        out["limit_range"] = list(value_range)
    if mean is None:
        return {**out, "status": "indeterminate"}  # only values below the limit of quantification
    if not is_physically_possible(name, mean):
        return {**out, "status": "excluded", "flags": ["physically-impossible"]}
    if value_range is not None:
        limit, is_lower = resolve_range_limit(mean, *value_range)
        out.update(limit=limit, limit_type="minimum" if is_lower else "maximum")
    return {**out, "scored_value": mean, "status": _status_against(mean, limit, is_lower)}


def _assessment_view(assessment: Mapping[str, Any]) -> dict[str, Any]:
    """The assessment as it is shown (numbers rounded like the others)."""
    view = dict(assessment)
    view["limit"] = _out(view["limit"])
    view["scored_value"] = _out(view["scored_value"])
    if view["limit_range"] is not None:
        view["limit_range"] = [_out(bound) for bound in view["limit_range"]]
    return view


CROSSING_VALUES = ("within-to-exceeds", "exceeds-to-within", "none")


def crossing(status_a: str, status_b: str) -> str | None:
    """``within-to-exceeds`` or ``exceeds-to-within`` when the comparison with the limit changed between the periods,
    ``none`` when both are judged and the same, None when either period was not judged (no limit, not scored, no value)."""
    judged = {"within-limit", "exceeds-limit"}
    if status_a not in judged or status_b not in judged:
        return None
    if status_a == status_b:
        return "none"
    return "within-to-exceeds" if status_b == "exceeds-limit" else "exceeds-to-within"
