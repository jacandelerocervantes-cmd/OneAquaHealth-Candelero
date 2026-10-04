"""Constants and the ONE mapping table between EEA Waterbase determinands and the project's closed parameter names.

Everything the store build keeps, and everything the reader may compare with a limit, is declared here and
documented in ``docs/waterbase_store.md``. Nothing is invented: the determinand codes, labels, units and matrices
are the ones verified in the EEA Waterbase Water Quality ICM 2026 file on 2026-10-02; the closed names are the
keys of ``oah.indices.water_parameter_limits.PARAMETER_UNITS``.

A determinand with no exact closed counterpart stays UNMAPPED: it is listed with its values but never compared
with a limit. Unit-basis rules (``mg{NO3}/L`` against ``mg{P}/L``) are in ``to_project_unit``: a conversion is
applied only where the table says so, and a basis that differs from the expected one is refused, not guessed.
Pure module: no I/O.
"""

from __future__ import annotations

import re
from dataclasses import dataclass

from oah.indices.regimes import PO4_PER_P
from oah.indices.water_parameter_limits import PARAMETER_UNITS, convert_to_unit

SOURCE_ID = "real-eea-waterbase"  # the ``origin`` / ``source`` label of every record read from the store
SOURCE_LABEL = "EEA Waterbase - Water Quality ICM 2026"
EDITION = "Waterbase - Water Quality ICM, 2026 edition (data 1900-2025), WISE6 tables v01_r00"
LICENCE = "CC BY 4.0 (European Environment Agency)"
ATTRIBUTION = "EEA Waterbase - Water Quality ICM 2026 (CC BY 4.0)"
SOURCE_URL = "https://www.eea.europa.eu/data-and-maps/data/waterbase-water-quality-icm-2"

# --- build filters (documented in docs/waterbase_store.md) ----------------------------------------------------

# Country codes of the file -> project code. Greece is written EL in Waterbase; the project already treats EL as an
# alias of GR (``oah.indices.regimes``). GR is accepted too, in case an edition uses it.
COUNTRY_CODES: dict[str, str] = {"EL": "GR", "GR": "GR", "IT": "IT", "NO": "NO"}
# parameterWaterBodyCategory values kept: rivers and lakes. Groundwater (GW), coastal (CW) and transitional (TW)
# waters are out of scope: the project's limit regimes cover rivers and drinking water only.
CATEGORIES: dict[str, str] = {"RW": "river", "LW": "lake"}
# procedureAnalysedMatrix values kept: W (water) and W-DIS (dissolved water).
MATRICES: frozenset[str] = frozenset({"W", "W-DIS"})
# resultObservationStatus values that mean "no observed value" (Waterbase dataset definition): dropped.
MISSING_VALUE_STATUSES: frozenset[str] = frozenset({"L", "M", "N", "O", "W"})
# metadata_observationStatus: U lower reliability, V unvalidated (A normal). Counted, never dropped.
LOWER_RELIABILITY_STATUSES: frozenset[str] = frozenset({"U", "V"})
BELOW_LOQ_TRUE: frozenset[str] = frozenset({"1", "true", "TRUE", "True"})
# First sampling year kept. A choice of this project (recent monitoring only, smaller store), not a property of
# the data; ``scripts/build_waterbase_store.py --min-year`` changes it and the value is stored in the provenance.
MIN_YEAR = 2010

# confidentialityStatus of the spatial table: ``F`` = free for publication, ``N`` = not for publication (the file's
# definition, see docs/waterbase_store.md). Only ``F`` allows coordinates to be stored or shown; any other value, a blank
# included, is treated as restricted (privacy by default).
FREE_FOR_PUBLICATION = "F"


def location_publishable(confidentiality: str | None) -> bool:
    """True only when the confidentiality status is exactly the documented ``F`` (after trimming blanks)."""
    return isinstance(confidentiality, str) and confidentiality.strip() == FREE_FOR_PUBLICATION


NO_LIMIT_REGIME = "no-limit-regime"  # lakes, and every measurement-only determinand: no limit regime in this project

# Parameter groups (a label of this project for display and filtering, not a Waterbase attribute). The existing
# chemistry keeps the first one; the two others hold the MEASUREMENT-ONLY determinands (no limit regime exists for them).
GROUP_WATER_CHEMISTRY = "water-chemistry"
GROUP_SOLIDS_TURBIDITY = "solids-turbidity"  # turbidity, suspended solids, Secchi depth: proxies for particulate/colloidal matter
GROUP_ORGANIC_MATTER = "organic-matter"  # a label only: no claim beyond it
GROUPS: tuple[str, ...] = (GROUP_WATER_CHEMISTRY, GROUP_SOLIDS_TURBIDITY, GROUP_ORGANIC_MATTER)


@dataclass(frozen=True)
class Determinand:
    """One kept Waterbase determinand and what the project may do with it."""

    code: str  # observedPropertyDeterminandCode
    label: str  # observedPropertyDeterminandLabel (verified 2026-10-02)
    closed_name: str | None  # key of PARAMETER_UNITS, or None when no exact counterpart exists
    matrices: frozenset[str]  # matrices in which the mapping holds (the closed name must mean the same thing)
    basis: str | None  # species basis the Waterbase unit label must carry, e.g. "NO3" for mg{NO3}/L; None = plain unit
    to_project_basis: float  # multiplier from the Waterbase basis to the basis the project limits use
    basis_source: str  # where the multiplier (or the decision to use 1.0) comes from
    unmapped_reason: str  # why there is no comparison (shown with unmapped records)
    group: str = GROUP_WATER_CHEMISTRY
    # Matrices the BUILD keeps for this code (the chemistry keeps W and W-DIS; a measurement-only code keeps only its rule).
    stored_matrices: frozenset[str] = MATRICES
    measurement_only: bool = False  # True: no limit regime exists, status is never within/exceeds
    expected_unit: str | None = None  # measurement-only: the exact Waterbase unit label accepted; any other is refused


_PLAIN = frozenset({"W"})
_DISSOLVED = frozenset({"W-DIS"})
_NO_FACTOR = "no conversion: the project limit is already expressed on the Waterbase basis (docs/waterbase_store.md)"
_METAL_REASON = (
    "the project's closed names are dissolved concentrations; matrix W (whole water) is not the dissolved fraction, "
    "so it is shown but not compared"
)


def _metal(code: str, name: str, closed: str) -> Determinand:
    return Determinand(code, f"{name} and its compounds", closed, _DISSOLVED, None, 1.0, _NO_FACTOR, _METAL_REASON)


def _plain(code: str, label: str, closed: str | None, basis: str | None, reason: str = "") -> Determinand:
    return Determinand(code, label, closed, _PLAIN, basis, 1.0, _NO_FACTOR, reason)


_NO_COUNTERPART = "no closed project parameter has the same meaning"


def _measurement_only(code: str, label: str, group: str, unit: str, matrix: str = "W") -> Determinand:
    """A determinand shown with its measurements and no limit: the project has no limit regime for it."""
    reason = f"measurement only: the project has no limit regime for {group} parameters"
    return Determinand(
        code, label, None, frozenset({matrix}), None, 1.0, "no conversion: the value is shown in the unit reported",
        reason, group=group, stored_matrices=frozenset({matrix}), measurement_only=True, expected_unit=unit,
    )


# Keyed by code. The label text is the Waterbase one (the metals read "<Metal> and its compounds").
DETERMINANDS: dict[str, Determinand] = {
    d.code: d
    for d in (
        _plain("EEA_3152-01-0", "pH", "pH", None),
        _plain("EEA_3132-01-2", "Dissolved oxygen", "Dissolved Oxygen", None),
        _plain(
            "EEA_3131-01-9", "Oxygen saturation", None, None,
            "oxygen saturation has no closed name; the national deviation criterion is derived per sample from "
            "dissolved oxygen and water temperature, which annual aggregates cannot reproduce",
        ),
        _plain("EEA_3121-01-5", "Water temperature", "Water temperature", None),
        _plain("EEA_3142-01-6", "Electrical conductivity", "Electrical conductivity", None),
        # Nitrate, nitrite and ammonium: Waterbase reports them as the ion (mg{NO3}/L, mg{NO2}/L, mg{NH4}/L) and the
        # project limits are already expressed as the ion (the N-to-ion factors NO3_PER_N, NO2_PER_N, NH4_PER_N are
        # folded into the national limits in oah.indices.regimes), so the factor is 1.0 and the basis must match.
        _plain("CAS_14797-55-8", "Nitrate", "Nitrate", "NO3"),
        _plain("CAS_14797-65-0", "Nitrite", "Nitrite", "NO2"),
        _plain("CAS_14798-03-9", "Ammonium", "Ammonium", "NH4"),
        _plain("CAS_14265-44-2", "Phosphate", None, "P", "orthophosphate is not total phosphorus; " + _NO_COUNTERPART),
        Determinand(
            "CAS_7723-14-0", "Total phosphorus", "Total phosphates", _PLAIN, "P", PO4_PER_P,
            "the project compares total phosphorus as phosphate (decision 2026-09-29, oah.indices.regimes.PO4_PER_P): "
            "multiplier PO4/P = (30.973762 + 4 x 15.999) / 30.973762, standard atomic weights",
            "",
        ),
        _plain("CAS_18785-72-3", "Sulphate", "Sulphate", None),
        _plain("CAS_16887-00-6", "Chloride", None, None, _NO_COUNTERPART),
        _metal("CAS_7440-43-9", "Cadmium", "Cadmium dissolved"),
        _metal("CAS_7439-97-6", "Mercury", "Mercury dissolved"),
        _metal("CAS_7439-92-1", "Lead", "Lead dissolved"),
        _metal("CAS_7440-02-0", "Nickel", "Nickel dissolved"),
        _metal("CAS_7440-38-2", "Arsenic", "Arsenic dissolved"),
        _metal("CAS_7440-66-6", "Zinc", "Zinc dissolved"),
        _metal("CAS_7440-50-8", "Copper", "Copper dissolved"),
        _metal("CAS_7439-89-6", "Iron", "Iron dissolved"),
        _metal("CAS_7429-90-5", "Aluminium", "Aluminium dissolved"),
        # --- measurement-only groups (labels, units and matrices as observed in the 2026 edition on 2026-10-02) ---
        # 'Colloids' as such are not measured: turbidity and suspended solids are PROXIES for particulate/colloidal matter.
        _measurement_only("EEA_3112-01-4", "Turbidity", GROUP_SOLIDS_TURBIDITY, "{NTU}"),
        _measurement_only("EEA_31-02-7", "Total suspended solids", GROUP_SOLIDS_TURBIDITY, "mg/L"),
        _measurement_only("EEA_3111-01-1", "Secchi depth", GROUP_SOLIDS_TURBIDITY, "m"),
        _measurement_only("EEA_3133-06-0", "Total organic carbon (TOC)", GROUP_ORGANIC_MATTER, "mg{C}/L"),
        _measurement_only("EEA_3133-05-9", "Dissolved organic carbon (DOC)", GROUP_ORGANIC_MATTER, "mg{C}/L", "W-DIS"),
        _measurement_only("EEA_3164-01-0", "Chlorophyll a", GROUP_ORGANIC_MATTER, "ug/L"),
        _measurement_only("EEA_3133-01-5", "BOD5", GROUP_ORGANIC_MATTER, "mg{O2}/L"),
        _measurement_only("EEA_3133-03-7", "CODCr", GROUP_ORGANIC_MATTER, "mg{O2}/L"),
    )
}
KEPT_DETERMINAND_CODES: frozenset[str] = frozenset(DETERMINANDS)

_UNIT_WITH_BASIS = re.compile(r"^(?P<mass>[A-Za-z]+)\{(?P<basis>[^{}/]+)\}/(?P<volume>[A-Za-z]+)$")


def closed_name(code: str, matrix: str) -> str | None:
    """The closed project parameter name for this determinand in this matrix, or None (unmapped, not compared)."""
    determinand = DETERMINANDS.get(code)
    if determinand is None or determinand.closed_name is None or matrix not in determinand.matrices:
        return None
    return determinand.closed_name


def listed_name(code: str, matrix: str) -> str:
    """The name a record is listed under: the closed name when mapped, else the Waterbase label."""
    mapped = closed_name(code, matrix)
    if mapped is not None:
        return mapped
    determinand = DETERMINANDS.get(code)
    return determinand.label if determinand is not None else code


def unmapped_reason(code: str, matrix: str) -> str:
    determinand = DETERMINANDS.get(code)
    if determinand is None:
        return "determinand is not part of the store"
    if determinand.closed_name is not None and matrix not in determinand.matrices:
        return _METAL_REASON if determinand.matrices == _DISSOLVED else "matrix is not the one the mapping holds for"
    return determinand.unmapped_reason or _NO_COUNTERPART


def group_of(code: str) -> str | None:
    """The parameter group of a determinand code, or None when the code is not part of the store."""
    determinand = DETERMINANDS.get(code)
    return determinand.group if determinand is not None else None


def codes_in_group(group: str) -> list[str]:
    """The determinand codes of one group, sorted (empty for an unknown group)."""
    return sorted(code for code, determinand in DETERMINANDS.items() if determinand.group == group)


def parameter_names() -> list[str]:
    """Every name a caller may filter the Waterbase records by: closed names and labels of unmapped determinands."""
    names = {d.closed_name for d in DETERMINANDS.values() if d.closed_name} | {d.label for d in DETERMINANDS.values()}
    return sorted(names)


def parameter_filter(name: str) -> tuple[str, str | None] | None:
    """``(determinand code, matrix or None)`` behind a filter name, or None when the name is unknown.

    A closed name selects the matrix the mapping holds for (so ``Cadmium dissolved`` means W-DIS); the Waterbase label
    of a determinand that has a closed name selects the other matrix (``Cadmium and its compounds`` means W, the
    records listed but not compared); the label of an unmapped determinand selects every matrix.
    """
    wanted = name.strip().lower()
    for determinand in DETERMINANDS.values():
        if determinand.closed_name is not None and determinand.closed_name.lower() == wanted:
            return determinand.code, sorted(determinand.matrices)[0]
    for determinand in DETERMINANDS.values():
        if determinand.label.lower() == wanted:
            if determinand.closed_name is None:
                return determinand.code, None
            others = sorted(MATRICES - determinand.matrices)
            return determinand.code, others[0] if others else None
    return None


def parse_unit(uom: str) -> tuple[str, str | None]:
    """Split a Waterbase unit label into ``(plain unit, species basis)``: ``mg{NO3}/L`` -> ``("mg/L", "NO3")``."""
    match = _UNIT_WITH_BASIS.match(uom.strip())
    if match is None:
        return uom.strip(), None
    return f"{match.group('mass')}/{match.group('volume')}", match.group("basis")


def to_project_unit(value: float, uom: str, determinand: Determinand) -> float | None:
    """``value`` in the unit and basis of the closed parameter, or None when that cannot be done exactly.

    Refused (None) when the unit label's species basis differs from the one the table expects (for example nitrate
    reported as N instead of NO3), or when the unit family is not convertible. Never guessed.
    """
    if determinand.closed_name is None:
        return None
    plain, basis = parse_unit(uom)
    if basis != determinand.basis:
        return None
    converted = convert_to_unit(value, plain, PARAMETER_UNITS[determinand.closed_name])
    return None if converted is None else converted * determinand.to_project_basis
