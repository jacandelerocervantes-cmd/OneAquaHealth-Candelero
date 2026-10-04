"""Verification registry for every numeric limit the index can use.

A limit is a regulatory-looking number, so its trustworthiness is recorded, not assumed. Every limit that the
code can apply has a stable key ``regime|country|parameter`` (``country`` is ``-`` when it does not apply).
``VERIFICATIONS`` holds the signatures. A signature is made by a person, in a human-authored commit, after
comparing the value with the primary text of the cited provision (procedure: docs/limits_verification.md).
It is bound to the value it was made for: if the limit later changes, the signature turns ``stale`` instead
of silently vouching for a different number. An agent must never add a signature.

Pure module: no I/O.
"""

from __future__ import annotations

import math
from dataclasses import dataclass

from oah.indices.regimes import (
    COUNTRY_OXYGEN_DEVIATION_LIMIT,
    COUNTRY_SURFACE_LIMITS,
    DATED_DRINKING_LIMITS,
    DRINKING,
    SATURATION_BASIS_PARAMETER,
    SURFACE,
    SURFACE_LIMITS,
    limit_basis,
)
from oah.indices.water_parameter_limits import CLOSED_PARAM_MAPPING, PARAMETER_UNITS, TWO_SIDED_LIMITS


@dataclass(frozen=True)
class LimitRecord:
    """One limit the code can apply: its key, value(s), unit and where it comes from."""

    key: str
    values: tuple[float, ...]
    unit: str
    source: str


@dataclass(frozen=True)
class Verification:
    """A person's signature on one limit, bound to the value and unit that were compared."""

    verified_by: str  # a handle, never an e-mail address (the trail is public)
    verified_on: str  # ISO date
    values: tuple[float, ...]
    unit: str
    evidence: str  # the primary provision compared, for example "Directive (EU) 2020/2184 Annex I Part B, L 435/35"


# Signatures live here, added by the auditor. Empty until a person signs a row.
VERIFICATIONS: dict[str, Verification] = {}


def limit_key(regime: str, country: str | None, parameter: str) -> str:
    return f"{regime}|{country or '-'}|{parameter}"


def current_limits() -> dict[str, LimitRecord]:
    """Every limit the code can apply, read from the live tables (so a changed number is seen at once)."""
    records: dict[str, LimitRecord] = {}

    def add(regime: str, country: str | None, parameter: str, values: tuple[float, ...], unit: str) -> None:
        key = limit_key(regime, country, parameter)
        records[key] = LimitRecord(key, values, unit, limit_basis(parameter, regime, country))

    for name, limit, _ in sorted({v for v in CLOSED_PARAM_MAPPING.values()}):
        unit = PARAMETER_UNITS.get(name, "")
        if name in TWO_SIDED_LIMITS:
            add(DRINKING, None, name, tuple(TWO_SIDED_LIMITS[name]), unit)
        elif name in DATED_DRINKING_LIMITS:
            add(DRINKING, None, name, (limit, DATED_DRINKING_LIMITS[name][1]), unit)
        else:
            add(DRINKING, None, name, (limit,), unit)
    for name, limit in SURFACE_LIMITS.items():
        add(SURFACE, None, name, (limit,), PARAMETER_UNITS.get(name, ""))
    for country, table in COUNTRY_SURFACE_LIMITS.items():
        for name, limit in table.items():
            add(SURFACE, country, name, (limit,), PARAMETER_UNITS.get(name, ""))
    for country, limit in COUNTRY_OXYGEN_DEVIATION_LIMIT.items():
        add(SURFACE, country, SATURATION_BASIS_PARAMETER, (limit,), PARAMETER_UNITS.get(SATURATION_BASIS_PARAMETER, "%"))
    return records


def _same(a: tuple[float, ...], b: tuple[float, ...]) -> bool:
    return len(a) == len(b) and all(math.isclose(x, y, rel_tol=1e-9, abs_tol=1e-12) for x, y in zip(a, b))


def verification_status(key: str) -> str:
    """``unverified``, ``verified`` or ``stale`` (signed for a value or unit that has since changed)."""
    signature = VERIFICATIONS.get(key)
    if signature is None:
        return "unverified"
    current = current_limits().get(key)
    if current is None or current.unit != signature.unit or not _same(current.values, signature.values):
        return "stale"
    return "verified"


def verification_label(regime: str, country: str | None, parameter: str) -> str:
    """Short text appended to a limit's basis in every output, so a reader sees how far to trust it."""
    key = limit_key(regime, country, parameter)
    status = verification_status(key)
    if status == "verified":
        signature = VERIFICATIONS[key]
        return f"[verified by {signature.verified_by} on {signature.verified_on}]"
    if status == "stale":
        return "[verification stale: the value changed after it was signed]"
    return "[unverified]"
