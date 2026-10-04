"""Which set of objective limits applies to a location, and which value applies on a given date.

Two regimes exist (decision recorded 2026-09-29, ``docs/math_registry.md``):

- ``drinking``: Directive (EU) 2020/2184, Annex I, parametric values (the values in
  ``oah.indices.water_parameter_limits.CLOSED_PARAM_MAPPING``). Default when a location's type is unknown.
- ``surface``: Directive 2013/39/EU, Annex II (Annex I Part A of 2008/105/EC), AA-EQS for inland
  surface waters, for locations typed as a river.

The regime is decided per location, never per parameter. Pure module: no I/O.
"""

from __future__ import annotations

import re
from datetime import UTC, datetime, timedelta
from typing import Any, Sequence

from oah.timeutil import TimeError, parse_fhir_time, utc_now

DRINKING = "drinking"
SURFACE = "surface"
DEFAULT_REGIME = DRINKING

# Explicit per-location decisions, keyed by Location id; wins over the type rule. Empty by default.
LOCATION_REGIME_OVERRIDES: dict[str, str] = {}

# (regime, country, parameter) -> source text, for limits replaced through OAH_LIMITS_FILE
# (see oah.indices.limit_overrides). Empty unless a limits file is in use.
OVERRIDE_SOURCES: dict[tuple[str, str | None, str], str] = {}

# SNOMED CT location type -> regime. Only 420531007 "River" (seen on the real Almyros Location) is
# mapped; other observed type 288520005 "City environment" says nothing about the water body, so it
# keeps the default. No code is invented: extend this table only with codes seen in real Locations.
REGIME_BY_LOCATION_TYPE: dict[str, str] = {"420531007": SURFACE}

# Surface-water AA-EQS for inland surface waters, ug/L (Directive 2013/39/EU, Annex II, L 226/15):
# mercury "0,07"; lead "1,2" and nickel "4" (both footnote 13: bioavailable concentration).
# The sandbox reports dissolved concentrations, so comparing them with a bioavailable EQS is an
# approximation (dissolved >= bioavailable, so it can overstate an exceedance); see the registry.
SURFACE_LIMITS: dict[str, float] = {"Lead dissolved": 1.2, "Mercury dissolved": 0.07, "Nickel dissolved": 4.0}
# Cadmium's EQS depends on water hardness (five classes, 0,08 to 0,25 ug/L); the sandbox carries no
# hardness, so no class can be chosen and the observation is skipped and counted, never guessed.
SURFACE_NEEDS_HARDNESS = frozenset({"Cadmium dissolved"})

# Country decides which national surface-water values apply (auditor decision 2026-09-29). Italy and
# Greece are implemented; Norway's instrument has not been read, so it uses the EU values.
# Country of a Location: explicit override by id, else the trailing "(..., XX)" of its description
# (e.g. "City of Benevento (Campania, IT)"), else its partOf parent. Almyros carries no country in its
# own text: the fixture is the Greek pilot (Hellenic Government Chemical Service, Crete coordinates).
LOCATION_COUNTRY_OVERRIDES: dict[str, str] = {"Loc-Almyros": "GR"}
_COUNTRY_CODES = {"IT": "IT", "GR": "GR", "EL": "GR", "NO": "NO"}
_COUNTRY_IN_DESCRIPTION = re.compile(r"\(([^()]{0,80},\s*)?([A-Z]{2})\)\s*$")
_COUNTRY_NAME_IN_DESCRIPTION = re.compile(r"[,(]\s*(Greece|Italy|Norway)\)?\.?\s*$")
_COUNTRY_NAMES = {"Greece": "GR", "Italy": "IT", "Norway": "NO"}

# Total phosphorus is compared as phosphate (auditor decision 2026-09-29: phosphorus is not found free
# in nature). Ratio of the molar masses PO4 / P with standard atomic weights P 30.973762, O 15.999.
PO4_PER_P = (30.973762 + 4 * 15.999) / 30.973762
# Italy, DM 8 November 2010 n. 260, Annex 1, Tab. 4.1.2/a (LIMeco), "Livello 2" (good status) boundaries
# for river (surface) locations: total phosphorus 100 ug/l P -> mg/L as PO4; oxygen |100 - % saturation| <= 20.
# Nitrogen is compared as the ion the sandbox reports (auditor decision 2026-09-29: nitrate is the usual
# nitrogen form for contamination; ammonium likewise): N-NO3 -> NO3 and N-NH4 -> NH4 with standard atomic
# weights N 14.0067, O 15.999, H 1.008. LIMeco level 2: N-NH4 0.06 mg/l and N-NO3 1.2 mg/l (as N).
NO3_PER_N = (14.0067 + 3 * 15.999) / 14.0067
NH4_PER_N = (14.0067 + 4 * 1.008) / 14.0067
NO2_PER_N = (14.0067 + 2 * 15.999) / 14.0067
# Greece, Hellenic Water Quality Index (HWQI) of the Hellenic Centre for Marine Research, Table 1 of
# Water 2022, 14, 2738 (https://doi.org/10.3390/w14172738): "good" class upper bounds (the good/moderate
# boundary) for rivers: N-NO3 0.60 mg/L, N-NH4 0.06 mg/L, N-NO2 8 ug/L (all as N), total phosphorus
# 165 ug/L (as P; compared as PO4 like Italy), dissolved oxygen 6.4 mg/L as a minimum (good class 6.4-9).
COUNTRY_SURFACE_LIMITS: dict[str, dict[str, float]] = {
    "IT": {
        "Total phosphates": 0.100 * PO4_PER_P,
        "Nitrate": 1.2 * NO3_PER_N,
        "Ammonium": 0.06 * NH4_PER_N,
    },
    "GR": {
        "Total phosphates": 0.165 * PO4_PER_P,
        "Nitrate": 0.60 * NO3_PER_N,
        "Ammonium": 0.06 * NH4_PER_N,
        "Nitrite": 0.008 * NO2_PER_N,
        "Dissolved Oxygen": 6.4,
    },
}
# Country -> maximum |100 - % O2 saturation| replacing the mg/L minimum for dissolved oxygen.
COUNTRY_OXYGEN_DEVIATION_LIMIT: dict[str, float] = {"IT": 20.0}
# Countries whose classification uses water temperature only to interpret biological data and to derive
# oxygen saturation ("non per la classificazione", DM 260/2010): it is not scored against a limit.
# Greece: the HWQI classifies with five nutrient species and dissolved oxygen only, not temperature.
COUNTRY_TEMPERATURE_INTERPRETIVE = frozenset({"IT", "GR"})

# Drinking-water limits that change on a date: (parameter) -> (effective_from_utc, new_limit).
# Lead: "The parametric value of 5 ug/l shall be met, at the latest, by 12 January 2036. The
# parametric value for lead until that date shall be 10 ug/l." (Annex I Part B, L 435/36).
DATED_DRINKING_LIMITS: dict[str, tuple[datetime, float]] = {
    "Lead dissolved": (datetime(2036, 1, 12, tzinfo=UTC), 5.0),
}


def regime_for_location(location: dict[str, Any]) -> str:
    """Regime for one Location resource: explicit override, then type code, then the default."""
    override = LOCATION_REGIME_OVERRIDES.get(str(location.get("id")))
    if override is not None:
        return override
    for location_type in location.get("type") or []:
        for coding in (location_type or {}).get("coding") or []:
            regime = REGIME_BY_LOCATION_TYPE.get(str(coding.get("code")))
            if regime is not None:
                return regime
    return DEFAULT_REGIME


def regimes_by_location_ref(locations: Sequence[dict[str, Any]] | None) -> dict[str, str]:
    """``{"Location/<id>": regime}`` for every Location that has an id (empty when none are given)."""
    return {f"Location/{loc['id']}": regime_for_location(loc) for loc in locations or [] if loc.get("id")}


def country_for_location(location: dict[str, Any], by_id: dict[str, dict[str, Any]] | None = None) -> str | None:
    """ISO country of a Location (IT, GR, NO), or None when it cannot be told.

    Order: explicit override, the "(..., XX)" or ", <Country>" suffix of the description, then the partOf parent
    (looked up in ``by_id``, at most five ancestors). Never guessed beyond those.
    """
    current: dict[str, Any] | None = location
    for _ in range(6):
        if current is None:
            return None
        override = LOCATION_COUNTRY_OVERRIDES.get(str(current.get("id")))
        if override is not None:
            return override
        description = str(current.get("description") or "").strip()[-200:]
        match = _COUNTRY_IN_DESCRIPTION.search(description)
        if match and match.group(2) in _COUNTRY_CODES:
            return _COUNTRY_CODES[match.group(2)]
        named = _COUNTRY_NAME_IN_DESCRIPTION.search(description)
        if named:
            return _COUNTRY_NAMES[named.group(1)]
        parent = str((current.get("partOf") or {}).get("reference") or "")
        current = (by_id or {}).get(parent.removeprefix("Location/"))
    return None


def countries_by_location_ref(locations: Sequence[dict[str, Any]] | None) -> dict[str, str]:
    """``{"Location/<id>": country}`` for every Location whose country can be determined."""
    by_id = {str(loc["id"]): loc for loc in locations or [] if loc.get("id")}
    found = {f"Location/{i}": country_for_location(loc, by_id) for i, loc in by_id.items()}
    return {ref: country for ref, country in found.items() if country is not None}


def known_countries() -> list[str]:
    """Every country the code or the active ``OAH_LIMITS_FILE`` can resolve, sorted.

    Read from the live tables (the recognised country codes, the national limit tables and the Location country
    overrides), so a country added through the limits file appears without a code change.
    """
    found = set(_COUNTRY_CODES.values()) | set(COUNTRY_SURFACE_LIMITS) | set(COUNTRY_OXYGEN_DEVIATION_LIMIT)
    return sorted(found | set(LOCATION_COUNTRY_OVERRIDES.values()))


def country_name(code: str) -> str | None:
    """The English name of a country code when the project already carries one (the names of the Location
    descriptions: Greece, Italy, Norway); None otherwise. Nothing is guessed for another code."""
    return next((name for name, known in _COUNTRY_NAMES.items() if known == code), None)


def has_national_limits(country: str) -> bool:
    """True when a national river-limit table (or an oxygen deviation limit) exists for ``country``."""
    return bool(COUNTRY_SURFACE_LIMITS.get(country)) or country in COUNTRY_OXYGEN_DEVIATION_LIMIT


def country_limit_sources(country: str) -> list[str]:
    """The distinct ``limit_basis`` texts a river site of ``country`` is scored with, sorted.

    Built from the same ``limit_basis`` function as every index result: national and override entries first
    come from the country's own tables, then the EU surface values that apply everywhere.
    """
    parameters = set(COUNTRY_SURFACE_LIMITS.get(country, {})) | set(SURFACE_LIMITS)
    if country in COUNTRY_OXYGEN_DEVIATION_LIMIT:
        parameters.add(SATURATION_BASIS_PARAMETER)
    return sorted({limit_basis(parameter, SURFACE, country) for parameter in parameters})


def observation_instant(observation: dict[str, Any]) -> datetime:
    """The instant a dated limit is assessed at: the last moment of the Observation's effective time.

    Using the end of the interval means a period that touches the change date is judged by the
    stricter (later) limit. A missing or unparseable time falls back to the current time.
    """
    effective = observation.get("effectiveDateTime") or observation.get("effectiveInstant")
    period = observation.get("effectivePeriod")
    if not effective and isinstance(period, dict):
        effective = period.get("end") or period.get("start")
    if isinstance(effective, str):
        try:
            return parse_fhir_time(effective).end - timedelta(microseconds=1)
        except TimeError:
            pass
    return utc_now()


def resolve_limit(
    parameter: str, limit: float, regime: str, instant: datetime, country: str | None = None
) -> float | None:
    """The objective limit of ``parameter`` under ``regime`` at ``instant``; None when it cannot be decided.

    ``limit`` is the single-value entry of ``CLOSED_PARAM_MAPPING`` (drinking-water regime).
    None means a surface-water limit that needs data the sandbox lacks (hardness).
    """
    if regime == SURFACE:
        if parameter in SURFACE_NEEDS_HARDNESS:
            return None
        national = COUNTRY_SURFACE_LIMITS.get(country or "", {}).get(parameter)
        if national is not None:
            return national
        return SURFACE_LIMITS.get(parameter, limit)
    dated = DATED_DRINKING_LIMITS.get(parameter)
    if dated is not None and instant >= dated[0]:
        return dated[1]
    return limit


# Shown with every index output (audit 2026-09-29): the numbers are reference values, not compliance findings.
INTERPRETATION_NOTICE = (
    "Reference values, not a legal compliance determination: a failed measurement means the reference "
    "value used was exceeded, not a legal exceedance. See limit_basis for each parameter's source."
)

_DRINKING_PARAMETRIC = frozenset(
    {"Arsenic dissolved", "Cadmium dissolved", "Copper dissolved", "Lead dissolved", "Mercury dissolved",
     "Nickel dissolved", "Nitrate", "Nitrite"}
)
_DRINKING_INDICATOR = frozenset(
    {"Aluminium dissolved", "Ammonium", "Conductivity", "Electrical conductivity", "Iron dissolved", "Sulphate", "pH"}
)
_NATIONAL_SOURCE = {"IT": "DM 260/2010 LIMeco (Italy)", "GR": "HWQI, Water 2022, 14, 2738 (Greece)"}
SATURATION_BASIS_PARAMETER = "Dissolved oxygen saturation deviation"


def _override_basis(parameter: str, regime: str, country: str | None) -> str | None:
    """``override: <source>`` when the limit in force was replaced by the user's limits file."""
    if regime == SURFACE and country and (SURFACE, country, parameter) in OVERRIDE_SOURCES:
        return f"override: {OVERRIDE_SOURCES[(SURFACE, country, parameter)]}"
    if (regime, None, parameter) in OVERRIDE_SOURCES:
        return f"override: {OVERRIDE_SOURCES[(regime, None, parameter)]}"
    if regime == SURFACE and (DRINKING, None, parameter) in OVERRIDE_SOURCES:
        return f"override: {OVERRIDE_SOURCES[(DRINKING, None, parameter)]} (drinking-water value used on a river site)"
    return None


def limit_basis(parameter: str, regime: str, country: str | None) -> str:
    """Where the limit used for ``parameter`` comes from: ``"<basis>: <source>"``.

    Basis is ``legal`` (a binding EU value), ``legal indicator`` (an EU indicator parameter, not a health
    limit), ``national`` (a national classification boundary), ``proxy`` (a value borrowed from another
    context) or ``convention`` (a project value with no legal source found).
    """
    overridden = _override_basis(parameter, regime, country)
    if overridden is not None:
        return overridden
    if parameter == SATURATION_BASIS_PARAMETER and country in _NATIONAL_SOURCE:
        return f"national: {_NATIONAL_SOURCE[country]}"
    if regime == SURFACE:
        if country in _NATIONAL_SOURCE and parameter in COUNTRY_SURFACE_LIMITS.get(country or "", {}):
            return f"national: {_NATIONAL_SOURCE[country or '']}"
        if parameter in SURFACE_LIMITS:
            return "legal: Directive 2013/39/EU AA-EQS, inland surface waters (lead and nickel: bioavailable)"
        if parameter in SURFACE_NEEDS_HARDNESS:
            return "not scored: hardness-dependent EQS"
    if parameter in _DRINKING_PARAMETRIC:
        source = "legal: Directive (EU) 2020/2184 Annex I Part B"
    elif parameter in _DRINKING_INDICATOR:
        source = "legal indicator: Directive (EU) 2020/2184 Annex I Part C"
    else:
        return "convention: project value, no legal source found"
    if parameter == "Lead dissolved" and regime != SURFACE:
        source += " (10 ug/L until 2036-01-12, 5 ug/L after)"
    return f"proxy, drinking-water value on a river site ({source})" if regime == SURFACE else source
