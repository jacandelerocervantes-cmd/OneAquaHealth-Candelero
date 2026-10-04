"""The determinand mapping table and the unit-basis rules (docs/waterbase_store.md)."""

from __future__ import annotations

import math

import pytest

from oah.indices.regimes import COUNTRY_SURFACE_LIMITS, NH4_PER_N, NO2_PER_N, NO3_PER_N, PO4_PER_P
from oah.indices.water_parameter_limits import CLOSED_PARAM_MAPPING, PARAMETER_UNITS
from oah.waterbase.mapping import (
    CATEGORIES,
    COUNTRY_CODES,
    DETERMINANDS,
    GROUP_ORGANIC_MATTER,
    GROUP_SOLIDS_TURBIDITY,
    GROUP_WATER_CHEMISTRY,
    GROUPS,
    KEPT_DETERMINAND_CODES,
    MATRICES,
    MIN_YEAR,
    closed_name,
    codes_in_group,
    group_of,
    listed_name,
    parameter_filter,
    parameter_names,
    parse_unit,
    to_project_unit,
    unmapped_reason,
)


def test_the_filters_are_the_documented_ones():
    assert COUNTRY_CODES == {"EL": "GR", "GR": "GR", "IT": "IT", "NO": "NO"}
    assert CATEGORIES == {"RW": "river", "LW": "lake"}  # no groundwater, coastal or transitional waters
    assert MATRICES == {"W", "W-DIS"} and MIN_YEAR == 2010
    assert len(KEPT_DETERMINAND_CODES) == 29  # 21 water chemistry (12 non-metals, 9 metals) and 8 measurement-only
    chemistry = [d for d in DETERMINANDS.values() if d.group == GROUP_WATER_CHEMISTRY]
    assert len(chemistry) == 21 and all(not d.measurement_only and d.stored_matrices == MATRICES for d in chemistry)


def test_every_closed_name_in_the_table_is_a_real_project_parameter_with_a_limit_entry():
    for determinand in DETERMINANDS.values():
        if determinand.closed_name is None:
            continue
        assert determinand.closed_name in PARAMETER_UNITS
        assert determinand.closed_name.lower() in CLOSED_PARAM_MAPPING  # the single-value entry the limits start from
        assert CLOSED_PARAM_MAPPING[determinand.closed_name.lower()][0] == determinand.closed_name


def test_each_closed_name_is_used_by_one_determinand_only():
    names = [d.closed_name for d in DETERMINANDS.values() if d.closed_name]
    assert len(names) == len(set(names))


def test_unmapped_determinands_are_listed_with_a_reason_and_never_compared():
    for code in ("EEA_3131-01-9", "CAS_14265-44-2", "CAS_16887-00-6"):  # oxygen saturation, phosphate, chloride
        assert closed_name(code, "W") is None
        assert listed_name(code, "W") == DETERMINANDS[code].label
        assert unmapped_reason(code, "W")
    assert "orthophosphate" in unmapped_reason("CAS_14265-44-2", "W")


def test_metals_are_compared_only_as_dissolved_water():
    lead = "CAS_7439-92-1"
    assert closed_name(lead, "W-DIS") == "Lead dissolved" and closed_name(lead, "W") is None
    assert listed_name(lead, "W") == "Lead and its compounds"
    assert "dissolved" in unmapped_reason(lead, "W")
    assert all(d.matrices == {"W-DIS"} for d in DETERMINANDS.values() if d.closed_name and d.closed_name.endswith("dissolved"))


def test_other_determinands_are_compared_only_in_plain_water():
    assert closed_name("CAS_14797-55-8", "W") == "Nitrate" and closed_name("CAS_14797-55-8", "W-DIS") is None
    assert closed_name("CAS_UNKNOWN", "W") is None and listed_name("CAS_UNKNOWN", "W") == "CAS_UNKNOWN"
    assert unmapped_reason("CAS_UNKNOWN", "W") == "determinand is not part of the store"


def test_the_filter_names_resolve_to_a_code_and_a_matrix():
    assert parameter_filter("nitrate") == ("CAS_14797-55-8", "W")
    assert parameter_filter(" Lead dissolved ") == ("CAS_7439-92-1", "W-DIS")
    assert parameter_filter("Lead and its compounds") == ("CAS_7439-92-1", "W")  # the listed, not compared records
    assert parameter_filter("Chloride") == ("CAS_16887-00-6", None)
    assert parameter_filter("Oxygen saturation") == ("EEA_3131-01-9", None)
    assert parameter_filter("Not a parameter") is None
    assert {"Nitrate", "Chloride", "Lead dissolved", "Lead and its compounds", "Total phosphates", "Total phosphorus"} <= set(
        parameter_names()
    )


def test_unit_labels_are_split_into_a_plain_unit_and_a_species_basis():
    assert parse_unit("mg{NO3}/L") == ("mg/L", "NO3")
    assert parse_unit("mg{P}/L") == ("mg/L", "P")
    assert parse_unit("ug{NH4}/L") == ("ug/L", "NH4")
    assert parse_unit("ug/L") == ("ug/L", None)
    assert parse_unit("[pH]") == ("[pH]", None)
    assert parse_unit(" Cel ") == ("Cel", None)
    assert parse_unit("mg{a}{b}/L") == ("mg{a}{b}/L", None)  # anything unexpected stays as it is


def test_nitrate_nitrite_and_ammonium_need_no_conversion_because_the_project_limits_are_ion_based():
    # The national limits are written as the ion (N-NO3 x NO3_PER_N ...): Waterbase's mg{NO3}/L is the same basis.
    assert to_project_unit(2.0, "mg{NO3}/L", DETERMINANDS["CAS_14797-55-8"]) == 2.0
    assert to_project_unit(2.0, "mg{NO2}/L", DETERMINANDS["CAS_14797-65-0"]) == 2.0
    assert to_project_unit(2.0, "mg{NH4}/L", DETERMINANDS["CAS_14798-03-9"]) == 2.0
    # the identity the decision rests on: an Italian limit of 1.2 mg/L N-NO3 is 1.2 x NO3_PER_N as nitrate
    assert COUNTRY_SURFACE_LIMITS["IT"]["Nitrate"] == pytest.approx(1.2 * NO3_PER_N)
    assert COUNTRY_SURFACE_LIMITS["IT"]["Ammonium"] == pytest.approx(0.06 * NH4_PER_N)
    assert COUNTRY_SURFACE_LIMITS["GR"]["Nitrite"] == pytest.approx(0.008 * NO2_PER_N)


def test_a_different_basis_or_a_missing_basis_is_refused_not_guessed():
    nitrate = DETERMINANDS["CAS_14797-55-8"]
    assert to_project_unit(1.0, "mg{N}/L", nitrate) is None  # as N: the factor would have to be chosen by someone
    assert to_project_unit(1.0, "mg/L", nitrate) is None  # no basis stated
    assert to_project_unit(1.0, "mg{P}/L", nitrate) is None
    assert to_project_unit(1.0, "uS/cm", nitrate) is None  # another unit family
    assert to_project_unit(1.0, "mg/L", DETERMINANDS["CAS_16887-00-6"]) is None  # unmapped: nothing to convert to


def test_total_phosphorus_as_p_becomes_phosphate_with_the_documented_factor():
    total_p = DETERMINANDS["CAS_7723-14-0"]
    assert total_p.to_project_basis == PO4_PER_P
    assert PO4_PER_P == pytest.approx((30.973762 + 4 * 15.999) / 30.973762)
    assert PO4_PER_P == pytest.approx(3.0662, abs=1e-4)
    assert to_project_unit(0.100, "mg{P}/L", total_p) == pytest.approx(0.100 * PO4_PER_P)
    # 100 ug/L as P is the Italian boundary: converting it gives exactly the limit the regime table holds
    assert to_project_unit(100.0, "ug{P}/L", total_p) == pytest.approx(COUNTRY_SURFACE_LIMITS["IT"]["Total phosphates"])
    assert to_project_unit(0.165, "mg{P}/L", total_p) == pytest.approx(COUNTRY_SURFACE_LIMITS["GR"]["Total phosphates"])
    assert to_project_unit(1.0, "mg{PO4}/L", total_p) is None  # already phosphate: not silently multiplied again


def test_plain_units_convert_between_mass_prefixes_and_keep_ph_and_temperature():
    sulphate = DETERMINANDS["CAS_18785-72-3"]
    assert to_project_unit(250.0, "ug/L", sulphate) == pytest.approx(0.25)
    assert to_project_unit(1.0, "g/L", sulphate) == pytest.approx(1000.0)
    lead = DETERMINANDS["CAS_7439-92-1"]
    assert to_project_unit(1.2, "ug/L", lead) == pytest.approx(1.2)
    assert to_project_unit(0.0012, "mg/L", lead) == pytest.approx(1.2)
    assert to_project_unit(7.5, "[pH]", DETERMINANDS["EEA_3152-01-0"]) == 7.5
    assert to_project_unit(14.0, "Cel", DETERMINANDS["EEA_3121-01-5"]) == 14.0
    assert to_project_unit(500.0, "uS/cm", DETERMINANDS["EEA_3142-01-6"]) == 500.0
    assert math.isclose(to_project_unit(1.0, "mS/cm", DETERMINANDS["EEA_3142-01-6"]) or 0.0, 1000.0)


# --- the measurement-only groups (solids-turbidity, organic-matter) ----------------------------------------------------

# Code, label, unit and matrix exactly as observed in the 2026 edition on 2026-10-02 (docs/waterbase_store.md).
MEASUREMENT_ONLY = {
    "EEA_3112-01-4": ("Turbidity", GROUP_SOLIDS_TURBIDITY, "{NTU}", "W"),
    "EEA_31-02-7": ("Total suspended solids", GROUP_SOLIDS_TURBIDITY, "mg/L", "W"),
    "EEA_3111-01-1": ("Secchi depth", GROUP_SOLIDS_TURBIDITY, "m", "W"),
    "EEA_3133-06-0": ("Total organic carbon (TOC)", GROUP_ORGANIC_MATTER, "mg{C}/L", "W"),
    "EEA_3133-05-9": ("Dissolved organic carbon (DOC)", GROUP_ORGANIC_MATTER, "mg{C}/L", "W-DIS"),
    "EEA_3164-01-0": ("Chlorophyll a", GROUP_ORGANIC_MATTER, "ug/L", "W"),
    "EEA_3133-01-5": ("BOD5", GROUP_ORGANIC_MATTER, "mg{O2}/L", "W"),
    "EEA_3133-03-7": ("CODCr", GROUP_ORGANIC_MATTER, "mg{O2}/L", "W"),
}


@pytest.mark.parametrize(("code", "expected"), MEASUREMENT_ONLY.items())
def test_each_measurement_only_determinand_has_its_documented_group_unit_and_matrix_rule(code, expected):
    label, group, unit, matrix = expected
    determinand = DETERMINANDS[code]
    assert (determinand.label, determinand.group, determinand.expected_unit) == (label, group, unit)
    assert determinand.stored_matrices == {matrix} and determinand.matrices == {matrix}
    assert determinand.measurement_only and determinand.closed_name is None  # no limit exists, so no closed parameter
    assert closed_name(code, matrix) is None and listed_name(code, matrix) == label
    assert "no limit regime" in unmapped_reason(code, matrix)


def test_groups_partition_the_determinands_and_the_api_literal_follows_them():
    from typing import get_args

    from oah.api.schemas import ParameterGroup

    assert GROUPS == ("water-chemistry", "solids-turbidity", "organic-matter") == get_args(ParameterGroup)
    assert {d.group for d in DETERMINANDS.values()} == set(GROUPS)
    assert sum(len(codes_in_group(group)) for group in GROUPS) == len(DETERMINANDS)
    assert codes_in_group(GROUP_SOLIDS_TURBIDITY) == sorted(["EEA_3111-01-1", "EEA_3112-01-4", "EEA_31-02-7"])
    assert len(codes_in_group(GROUP_ORGANIC_MATTER)) == 5 and codes_in_group("nothing") == []
    assert group_of("EEA_3112-01-4") == GROUP_SOLIDS_TURBIDITY and group_of("CAS_14797-55-8") == GROUP_WATER_CHEMISTRY
    assert group_of("CAS_UNKNOWN") is None


def test_no_limit_exists_for_the_measurement_only_names():
    for label, *_rest in MEASUREMENT_ONLY.values():
        assert label.lower() not in CLOSED_PARAM_MAPPING and label not in PARAMETER_UNITS


def test_measurement_only_labels_are_filter_names_for_every_matrix_they_hold():
    assert parameter_filter("turbidity") == ("EEA_3112-01-4", None)
    assert parameter_filter("Total organic carbon (TOC)") == ("EEA_3133-06-0", None)
    assert {"Turbidity", "Secchi depth", "BOD5", "CODCr", "Chlorophyll a"} <= set(parameter_names())
