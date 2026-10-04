"""Change the limits without editing code: an optional external JSON file of overrides.

The limits shipped in the code are EU, Italian and Greek reference values (see docs/limits_verification.md). For
another region, a demo or a what-if, ``OAH_LIMITS_FILE`` may point to a JSON file (outside the repository) that
replaces or adds limits, location countries and location regimes. The file is validated strictly, the change is
labelled in every output (``limit_basis`` reads ``override: <source>``), overridden limits are never reported as
verified, and the file is re-read when it changes, so values can be edited while the API runs.

Format (``docs/limits_override.example.json``)::

    {"schema_version": 1, "note": "what this file is",
     "limits": [{"regime": "surface", "country": "MX", "parameter": "Nitrate", "values": [10.0],
                 "unit": "mg/L", "source": "where the value comes from"}],
     "location_countries": {"Loc-Example": "MX"}, "location_regimes": {"Loc-Example": "surface"}}

Rules: ``regime`` is ``drinking`` or ``surface``; ``parameter`` is a name the index knows
(``oah.indices.water_parameter_limits.PARAMETER_UNITS``); ``unit`` must equal that parameter's unit, so a value in
the wrong unit is refused rather than misread; values are finite and positive; a range (two values) needs the
lower one below the upper one. A ``surface`` limit with a ``country`` applies to river locations of that country
(two capital letters); without a country it applies to every river location.
"""

from __future__ import annotations

import copy
import json
import logging
import math
import os
import re
from dataclasses import dataclass
from pathlib import Path
from typing import Any

from oah.indices import regimes, water_parameter_limits
from oah.indices.regimes import DRINKING, SURFACE

logger = logging.getLogger(__name__)

SCHEMA_VERSION = 1
_COUNTRY = re.compile(r"^[A-Z]{2}$")
_ALLOWED_TOP = {"schema_version", "note", "limits", "location_countries", "location_regimes"}
_ALLOWED_ENTRY = {"regime", "country", "parameter", "values", "unit", "source"}


class LimitOverrideError(ValueError):
    """The overrides file is malformed or asks for something the index cannot represent."""


@dataclass(frozen=True)
class OverrideReport:
    """What a successful load changed (shown in the index result)."""

    path: str
    note: str
    limits: int
    locations: int


_ORIGINALS: dict[str, Any] | None = None
_LOADED: tuple[str, float] | None = None  # (path, mtime) of the file currently applied
_REPORT: OverrideReport | None = None


def _tables() -> dict[str, Any]:
    return {
        "mapping": water_parameter_limits.CLOSED_PARAM_MAPPING,
        "two_sided": water_parameter_limits.TWO_SIDED_LIMITS,
        "dated": regimes.DATED_DRINKING_LIMITS,
        "surface": regimes.SURFACE_LIMITS,
        "country_surface": regimes.COUNTRY_SURFACE_LIMITS,
        "country_oxygen": regimes.COUNTRY_OXYGEN_DEVIATION_LIMIT,
        "location_country": regimes.LOCATION_COUNTRY_OVERRIDES,
        "location_regime": regimes.LOCATION_REGIME_OVERRIDES,
        "sources": regimes.OVERRIDE_SOURCES,
    }


def _snapshot() -> None:
    global _ORIGINALS
    if _ORIGINALS is None:
        _ORIGINALS = {name: copy.deepcopy(table) for name, table in _tables().items()}


def reset_overrides() -> None:
    """Restore the limits shipped in the code (used before each load, and by tests)."""
    global _LOADED, _REPORT
    if _ORIGINALS is not None:
        for name, table in _tables().items():
            table.clear()
            table.update(copy.deepcopy(_ORIGINALS[name]))
    _LOADED, _REPORT = None, None


def _number(value: Any, where: str) -> float:
    if isinstance(value, bool) or not isinstance(value, (int, float)) or not math.isfinite(value) or value <= 0:
        raise LimitOverrideError(f"{where}: values must be finite numbers greater than zero, got {value!r}.")
    return float(value)


def _validate_entry(entry: Any, index: int) -> tuple[str, str | None, str, tuple[float, ...], str]:
    where = f"limits[{index}]"
    if not isinstance(entry, dict) or set(entry) - _ALLOWED_ENTRY:
        raise LimitOverrideError(f"{where}: expected an object with only {sorted(_ALLOWED_ENTRY)}.")
    regime, country, parameter = entry.get("regime"), entry.get("country"), entry.get("parameter")
    unit, source, values = entry.get("unit"), entry.get("source"), entry.get("values")
    if regime not in (DRINKING, SURFACE):
        raise LimitOverrideError(f"{where}: regime must be 'drinking' or 'surface'.")
    if country is not None and (not isinstance(country, str) or not _COUNTRY.match(country)):
        raise LimitOverrideError(f"{where}: country must be two capital letters or null.")
    if regime == DRINKING and country is not None:
        raise LimitOverrideError(f"{where}: a drinking-water limit has no country.")
    if parameter not in water_parameter_limits.PARAMETER_UNITS:
        raise LimitOverrideError(f"{where}: unknown parameter {parameter!r}; known: {sorted(water_parameter_limits.PARAMETER_UNITS)}.")
    expected = water_parameter_limits.PARAMETER_UNITS[parameter]
    if unit != expected:
        raise LimitOverrideError(f"{where}: unit for {parameter} must be {expected!r} (got {unit!r}); convert the value first.")
    if not isinstance(source, str) or not source.strip():
        raise LimitOverrideError(f"{where}: source is required (say where the value comes from).")
    if not isinstance(values, list) or not 1 <= len(values) <= 2:
        raise LimitOverrideError(f"{where}: values must be a list of one or two numbers.")
    numbers = tuple(_number(v, where) for v in values)
    if len(numbers) == 2 and regime == SURFACE:
        raise LimitOverrideError(f"{where}: a two-value range or dated limit is only supported for drinking-water limits.")
    return regime, country, parameter, numbers, source.strip()


def _apply_limit(regime: str, country: str | None, parameter: str, values: tuple[float, ...], source: str) -> None:
    mapping = water_parameter_limits.CLOSED_PARAM_MAPPING
    if regime == DRINKING:
        names = {name for name, _, _ in mapping.values()}
        if parameter not in names:
            raise LimitOverrideError(f"drinking limit for {parameter!r}: the parameter has no drinking-water entry to change.")
        if parameter in water_parameter_limits.TWO_SIDED_LIMITS:
            if len(values) != 2 or values[0] >= values[1]:
                raise LimitOverrideError(f"{parameter}: a range needs two values, lower below upper.")
            water_parameter_limits.TWO_SIDED_LIMITS[parameter] = (values[0], values[1])
        elif parameter in regimes.DATED_DRINKING_LIMITS:
            effective, _old = regimes.DATED_DRINKING_LIMITS[parameter]
            if len(values) == 2:
                regimes.DATED_DRINKING_LIMITS[parameter] = (effective, values[1])
        elif len(values) != 1:
            raise LimitOverrideError(f"{parameter}: this limit takes one value.")
        for key, (name, _limit, is_lower) in list(mapping.items()):
            if name == parameter:
                mapping[key] = (name, values[0], is_lower)
    elif country is None:
        if len(values) != 1:
            raise LimitOverrideError(f"{parameter}: a surface limit takes one value.")
        regimes.SURFACE_LIMITS[parameter] = values[0]
    elif parameter == regimes.SATURATION_BASIS_PARAMETER:
        regimes.COUNTRY_OXYGEN_DEVIATION_LIMIT[country] = values[0]
    else:
        regimes.COUNTRY_SURFACE_LIMITS.setdefault(country, {})[parameter] = values[0]
    regimes.OVERRIDE_SOURCES[(regime, country, parameter)] = source


def apply_overrides(data: Any, path: str = "<memory>") -> OverrideReport:
    """Validate ``data`` (a parsed overrides document) and apply it on top of the shipped limits."""
    if not isinstance(data, dict) or set(data) - _ALLOWED_TOP:
        raise LimitOverrideError(f"the file must be an object with only {sorted(_ALLOWED_TOP)}.")
    if data.get("schema_version") != SCHEMA_VERSION:
        raise LimitOverrideError(f"schema_version must be {SCHEMA_VERSION}.")
    entries = data.get("limits", [])
    if not isinstance(entries, list):
        raise LimitOverrideError("limits must be a list.")
    parsed = [_validate_entry(entry, i) for i, entry in enumerate(entries)]
    countries, regime_map = data.get("location_countries", {}), data.get("location_regimes", {})
    if not isinstance(countries, dict) or not all(isinstance(k, str) and isinstance(v, str) and _COUNTRY.match(v) for k, v in countries.items()):
        raise LimitOverrideError("location_countries must map a Location id to a two-letter country.")
    if not isinstance(regime_map, dict) or not all(isinstance(k, str) and v in (DRINKING, SURFACE) for k, v in regime_map.items()):
        raise LimitOverrideError("location_regimes must map a Location id to 'drinking' or 'surface'.")
    note = str(data.get("note", "")).strip()[:200]

    _snapshot()
    reset_overrides()
    try:
        for regime, country, parameter, values, source in parsed:
            _apply_limit(regime, country, parameter, values, source)
    except LimitOverrideError:
        reset_overrides()  # a half-applied file never stays in effect
        raise
    regimes.LOCATION_COUNTRY_OVERRIDES.update(countries)
    regimes.LOCATION_REGIME_OVERRIDES.update(regime_map)
    global _REPORT
    _REPORT = OverrideReport(path, note, len(parsed), len(countries) + len(regime_map))
    return _REPORT


def active_report() -> OverrideReport | None:
    return _REPORT


def ensure_overrides_loaded(limits_file: Path | None, strict: bool = False) -> OverrideReport | None:
    """Apply ``limits_file`` if set and changed since the last look; restore the shipped limits if it was unset.

    ``strict`` raises on a bad file (used at startup, so a wrong file stops the server with a clear message);
    otherwise a bad file is logged and the last good state stays in effect, so a running demo does not break.
    """
    global _LOADED
    if limits_file is None:
        if _LOADED is not None:
            reset_overrides()
        return None
    try:
        stamp = (str(limits_file), os.stat(limits_file).st_mtime)
        if stamp == _LOADED:
            return _REPORT
        data = json.loads(limits_file.read_text(encoding="utf-8"))
        report = apply_overrides(data, str(limits_file.name))
        _LOADED = stamp
        logger.warning("Limit overrides applied from %s: %d limits, %d location settings.", limits_file.name, report.limits, report.locations)
        return report
    except (OSError, json.JSONDecodeError, LimitOverrideError) as error:
        if strict:
            raise LimitOverrideError(f"OAH_LIMITS_FILE cannot be used: {error}") from error
        logger.error("Ignoring the changed limits file, keeping the previous limits: %s", error)
        return _REPORT
