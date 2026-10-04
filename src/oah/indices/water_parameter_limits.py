"""Objective limits, unit conversion, profile matching, and plausibility checks for water parameters.

Objective limits for physicochemical parameters are derived from EU Environmental Quality
Standards (Directive 2008/105/EC and Directive 2013/39/EU for aquatic life protection) and
EU Drinking Water Directive (Directive (EU) 2020/2184) as documented environmental proxies
for lack of published site-specific ambient standards in the public sandbox.

This module is pure: no I/O, no sandbox access, no network. See ``oah.indices.sandbox_loader``
for sandbox-resource loading and ``oah.indices.apply_to_sandbox`` for the CCME WQI pipeline
that consumes these limits and conversions.
"""

from __future__ import annotations

import math
from typing import Any, Sequence

from oah.qc.statistics import check_statistics

WATER_PROFILES = frozenset(
    {
        "http://hl7.eu/fhir/ig/oah/StructureDefinition/observation-with-component-oah",
        "http://hl7.eu/fhir/ig/oah/StructureDefinition/observation-indicators-oah",
        "observation-with-component-oah",
        "observation-indicators-oah",
    }
)

HEALTH_MEASURE_PROFILES = frozenset(
    {
        "http://hl7.eu/fhir/ig/oah/StructureDefinition/observation-health-measure-oah",
        "observation-health-measure-oah",
    }
)

# Closed, exact FHIR code and display mapping to (parameter_name, objective_limit, is_lower_bound)
CLOSED_PARAM_MAPPING: dict[str, tuple[str, float, bool]] = {
    "aluminium-dissolved": ("Aluminium dissolved", 200.0, False),
    "aluminium dissolved": ("Aluminium dissolved", 200.0, False),
    "ammonium": ("Ammonium", 0.50, False),
    "arsenic-dissolved": ("Arsenic dissolved", 10.0, False),
    "arsenic dissolved": ("Arsenic dissolved", 10.0, False),
    "cadmium-dissolved": ("Cadmium dissolved", 5.0, False),
    "cadmium dissolved": ("Cadmium dissolved", 5.0, False),
    "copper-dissolved": ("Copper dissolved", 2000.0, False),
    "copper dissolved": ("Copper dissolved", 2000.0, False),
    "dissolved-oxygen": ("Dissolved Oxygen", 6.0, True),
    "dissolved oxygen": ("Dissolved Oxygen", 6.0, True),
    "electrical-conductivity": ("Electrical conductivity", 2500.0, False),
    "electrical conductivity": ("Electrical conductivity", 2500.0, False),
    "conductivity": ("Conductivity", 2500.0, False),
    "iron-dissolved": ("Iron dissolved", 200.0, False),
    "iron dissolved": ("Iron dissolved", 200.0, False),
    "lead-dissolved": ("Lead dissolved", 10.0, False),
    "lead dissolved": ("Lead dissolved", 10.0, False),
    "mercury-dissolved": ("Mercury dissolved", 1.0, False),
    "mercury dissolved": ("Mercury dissolved", 1.0, False),
    "nickel-dissolved": ("Nickel dissolved", 20.0, False),
    "nickel dissolved": ("Nickel dissolved", 20.0, False),
    "nitrate": ("Nitrate", 50.0, False),
    "nitrite": ("Nitrite", 0.50, False),
    "ph": ("pH", 8.5, False),
    "sulphate": ("Sulphate", 250.0, False),
    "total-phosphates": ("Total phosphates", 0.10, False),
    "total phosphates": ("Total phosphates", 0.10, False),
    "watertemperature": ("Water temperature", 25.0, False),
    "water temperature": ("Water temperature", 25.0, False),
    "703421000": ("Water temperature", 25.0, False),
    "temperature (water)": ("Water temperature", 25.0, False),
    "zinc-dissolved": ("Zinc dissolved", 100.0, False),
    "zinc dissolved": ("Zinc dissolved", 100.0, False),
}


# Unit each objective limit is expressed in (UCUM). Limits are compared only after converting the
# observed value to this unit; an unknown or incompatible unit is skipped and counted, never guessed.
PARAMETER_UNITS: dict[str, str] = {
    "Aluminium dissolved": "ug/L", "Arsenic dissolved": "ug/L", "Cadmium dissolved": "ug/L",
    "Copper dissolved": "ug/L", "Iron dissolved": "ug/L", "Lead dissolved": "ug/L",
    "Mercury dissolved": "ug/L", "Nickel dissolved": "ug/L", "Zinc dissolved": "ug/L",
    "Ammonium": "mg/L", "Nitrate": "mg/L", "Nitrite": "mg/L", "Sulphate": "mg/L",
    "Total phosphates": "mg/L", "Dissolved Oxygen": "mg/L",
    "Electrical conductivity": "uS/cm", "Conductivity": "uS/cm",
    "Water temperature": "Cel", "pH": "pH", "Dissolved oxygen saturation deviation": "%",
}
# Multiplicative factors to a common base per family (mass concentration in mg/L, conductivity in uS/cm).
_UNIT_FAMILIES: dict[str, tuple[str, float]] = {
    "ng/L": ("concentration", 1e-6), "ug/L": ("concentration", 1e-3), "mg/L": ("concentration", 1.0),
    "g/L": ("concentration", 1e3),
    # UCUM allows a lower-case l for litre; the sandbox data use the capital.
    "ng/l": ("concentration", 1e-6), "ug/l": ("concentration", 1e-3), "mg/l": ("concentration", 1.0),
    "g/l": ("concentration", 1e3),
    "uS/cm": ("conductivity", 1.0), "mS/cm": ("conductivity", 1e3),
    "Cel": ("temperature", 1.0), "pH": ("ph", 1.0), "[pH]": ("ph", 1.0),
}


def convert_to_unit(value: float, from_unit: str | None, to_unit: str) -> float | None:
    """Convert ``value`` to ``to_unit`` or return None when the conversion is unknown or impossible.

    A missing unit is accepted only for pH (dimensionless); everything else needs a known code.
    """
    if from_unit is None:
        return value if to_unit == "pH" else None
    source, target = _UNIT_FAMILIES.get(from_unit), _UNIT_FAMILIES.get(to_unit)
    if source is None or target is None or source[0] != target[0]:
        return None
    return value * source[1] / target[1]


def exact_numeric_value(quantity: dict[str, Any]) -> float | None:
    """Return a Quantity's value only when it is an exact number.

    A Quantity with a ``comparator`` ("<", "<=", ">=", ">") is a censored or bounded value, not
    a measurement. Booleans are not numbers.
    """
    value = quantity.get("value")
    if quantity.get("comparator") or isinstance(value, bool) or not isinstance(value, (int, float)):
        return None
    if not math.isfinite(value):
        return None
    return float(value)


def classify_quantity(quantity: dict[str, Any], limit: float, is_lower: bool) -> tuple[str, float | None]:
    """Classify one Quantity against an objective limit for CCME scoring.

    Returns ``("exact", value)``, ``("pass-by-bound", bound)`` when a comparator's bound alone
    proves the measurement meets the limit (F1/F2 count it as a pass and its excursion is 0, so
    the bound is an exact stand-in), ``("indeterminate", None)`` when the bound cannot decide
    pass/fail or the amplitude, or ``("invalid", None)`` when no usable number exists.
    """
    exact = exact_numeric_value(quantity)
    if exact is not None:
        return "exact", exact
    comparator, bound = quantity.get("comparator"), quantity.get("value")
    if not comparator or isinstance(bound, bool) or not isinstance(bound, (int, float)):
        return "invalid", None
    # Upper-limit parameters fail when value > limit: "<" / "<=" a bound at or under the limit passes.
    # Lower-limit parameters fail when value < limit: ">" / ">=" a bound at or over the limit passes.
    if not is_lower and comparator in ("<", "<=") and bound <= limit:
        return "pass-by-bound", float(bound)
    if is_lower and comparator in (">", ">=") and bound >= limit:
        return "pass-by-bound", float(bound)
    return "indeterminate", None


# Parameters whose objective is a two-sided range (lower, upper), in ``PARAMETER_UNITS`` units. A
# parameter listed here is scored against the range instead of the single limit in
# ``CLOSED_PARAM_MAPPING`` (whose pH entry is now only used for name matching).
# pH 6.5-9.5: Directive (EU) 2020/2184, Annex I Part C, "Hydrogen ion concentration >= 6,5 and <= 9,5
# pH units"; enabled 2026-09-29 on the project auditor's sign-off (see
# ``docs/unvalidated_values_register.md`` section 3a).
TWO_SIDED_LIMITS: dict[str, tuple[float, float]] = {"pH": (6.5, 9.5)}


def resolve_range_limit(value: float, lower: float, upper: float) -> tuple[float, bool]:
    """Pick the (limit, is_lower) a measurement is scored against for a two-sided range.

    Below ``lower`` the lower bound is the violated objective (``is_lower=True``); above ``upper``
    the upper bound is; inside the range the measurement passes and is scored against the upper
    bound (excursion 0). This keeps the ``(name, value, limit, is_lower)`` test shape used by
    ``ccme_wqi``: each range measurement is ONE test, and its excursion is relative to the bound it violates.
    """
    if lower >= upper:
        raise ValueError(f"lower bound must be below upper bound, got ({lower}, {upper}).")
    if value < lower:
        return lower, True
    return upper, False


def classify_range_quantity(quantity: dict[str, Any]) -> tuple[str, float | None]:
    """Classify one Quantity against a two-sided range, like ``classify_quantity`` for one limit.

    A comparator bound ("<", ">", ...) can prove only one side of a range, never both, so a
    censored value is always ``("indeterminate", None)``; ``("invalid", None)`` when no number exists.
    """
    exact = exact_numeric_value(quantity)
    if exact is not None:
        return "exact", exact
    bound = quantity.get("value")
    if not quantity.get("comparator") or isinstance(bound, bool) or not isinstance(bound, (int, float)):
        return "invalid", None
    return "indeterminate", None


def is_physically_possible(parameter: str, value: float) -> bool:
    """Definitional plausibility only: the pH scale spans 0-14 and no concentration or level is negative.

    No ecological range is invented here. Water temperature is excluded from the non-negative rule
    because it is expressed in degrees Celsius. NaN and infinity are never physically possible.
    """
    if not math.isfinite(value):
        return False
    if parameter == "pH":
        return 0.0 <= value <= 14.0
    if parameter == "Water temperature":
        return True
    return value >= 0.0


STATISTIC_CODES = frozenset({"average", "median", "minimum", "maximum", "std-dev"})
# One period-summary Observation is ONE test for the CCME index. The median is the representative
# level (robust to the scale-corrupted averages/extremes seen in the public sandbox); the average
# is the fallback. Dispersion ("std-dev") and the extremes are never scored as levels.
REPRESENTATIVE_STATISTICS = ("median", "average")


def representative_quantity(observation: dict[str, Any]) -> tuple[dict[str, Any] | None, str | None]:
    """Pick the single Quantity that represents an Observation in the CCME index.

    Returns ``(quantity, None)`` or ``(None, reason)`` with reason ``qc-inconsistent`` (the summary
    statistics violate min <= median <= max or min <= average <= max, so they are not trusted),
    ``no-representative-statistic`` or ``no-quantity``.
    """
    components = observation.get("component", [])
    if not components:
        quantity = observation.get("valueQuantity")
        return (quantity, None) if isinstance(quantity, dict) else (None, "no-quantity")
    by_code: dict[str, dict[str, Any]] = {}
    for component in components:
        codes = [c.get("code") for c in component.get("code", {}).get("coding", [])]
        code = next((c for c in codes if c in STATISTIC_CODES), None)
        quantity = component.get("valueQuantity")
        if code and isinstance(quantity, dict):
            by_code[code] = quantity
    exact = {code: exact_numeric_value(q) for code, q in by_code.items() if code != "std-dev"}
    if check_statistics({code: value for code, value in exact.items() if value is not None}):
        return None, "qc-inconsistent"
    for code in REPRESENTATIVE_STATISTICS:
        if code in by_code:
            return by_code[code], None
    return None, "no-representative-statistic"


def is_water_profile(profiles: Sequence[str]) -> bool:
    """Check if an observation has an environmental/water FHIR profile."""
    for p in profiles:
        p_clean = p.split("/")[-1]
        if p in WATER_PROFILES or p_clean in WATER_PROFILES:
            return True
    return False


def is_health_measure_profile(profiles: Sequence[str]) -> bool:
    """Check if an observation has a population health measure profile."""
    for p in profiles:
        p_clean = p.split("/")[-1]
        if p in HEALTH_MEASURE_PROFILES or p_clean in HEALTH_MEASURE_PROFILES:
            return True
    return False


def match_closed_parameter(obs: dict[str, Any]) -> tuple[str, float, bool] | None:
    """Match observation FHIR code/display against the closed limit dictionary using exact matching."""
    code_obj = obs.get("code", {})
    candidates = []

    codings = code_obj.get("coding", [])
    for c in codings:
        if c.get("code"):
            candidates.append(c["code"].strip().lower())
        if c.get("display"):
            candidates.append(c["display"].strip().lower())

    if code_obj.get("text"):
        candidates.append(code_obj["text"].strip().lower())

    for key in candidates:
        if key in CLOSED_PARAM_MAPPING:
            return CLOSED_PARAM_MAPPING[key]

    return None
