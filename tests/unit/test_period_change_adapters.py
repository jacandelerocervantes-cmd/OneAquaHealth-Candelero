"""The adapters of the period comparison: Waterbase rows to cells (units, matrix), and parity with the measurement records.

The parity test is the guarantee that a period mean is judged by exactly the machinery the annual records use: for every
mapped determinand, country and water category the limit, its basis, the regime, the status and the scored value of
``assess_mean`` equal those of ``annual_record``. Values are invented (SYNTHETIC).
"""

from __future__ import annotations

import pytest

from oah.indices.period_change import Period, assess_mean, month_position
from oah.indices.regimes import PO4_PER_P
from oah.indices.water_parameter_limits import PARAMETER_UNITS
from oah.waterbase import change
from oah.waterbase.change import Series, regime_of, resolve_series, to_cells
from oah.waterbase.mapping import DETERMINANDS, MATRICES, NO_LIMIT_REGIME, parameter_names
from oah.waterbase.measurements import annual_record
from oah.waterbase.store import AnnualRow, MonthlyRow, WaterbaseSite


def native_unit(code: str, matrix: str) -> str:
    """A unit label the real file uses for this determinand (basis in braces where the mapping expects one)."""
    determinand = DETERMINANDS[code]
    if determinand.measurement_only:
        return str(determinand.expected_unit)
    if determinand.closed_name is None:
        return "mg/L"
    plain = PARAMETER_UNITS[determinand.closed_name]
    if plain == "pH":
        return "[pH]"
    if determinand.basis is not None:
        mass, volume = plain.split("/")
        return f"{mass}{{{determinand.basis}}}/{volume}"
    return plain


def site_of(country: str, category: str) -> WaterbaseSite:
    return WaterbaseSite("S", country, category, "n", None, None, 1.0, 1.0, "F", 2020, 2022, 1)


@pytest.mark.parametrize("country", ["IT", "GR", "NO"])
@pytest.mark.parametrize("category", ["RW", "LW"])
def test_a_period_mean_is_judged_exactly_like_the_annual_record(country, category):
    checked = 0
    for code, determinand in DETERMINANDS.items():
        for matrix in sorted(determinand.stored_matrices):
            unit = native_unit(code, matrix)
            context = to_cells([], Series(code, matrix))[2]
            for value in (0.0, 0.05, 0.5, 7.0, 100.0, 5000.0):
                row = AnnualRow(country, "S", category, code, matrix, unit, 2022, 3, value, value, value, 0, 0)
                record = annual_record(site_of(country, category), row)
                if record["status"] == "excluded" and "unit-mismatch" in record["data_quality_flags"]:
                    continue
                converted = record["value"]
                mine = assess_mean(context, change_site_context(country, category), converted, month_position(2022, 12))
                assert mine["limit_regime"] == record["limit_regime"], (code, matrix, value)
                assert mine["limit"] == record["limit"] and mine["limit_type"] == record["limit_type"], (code, matrix, value)
                assert mine["limit_range"] == record["limit_range"] and mine["limit_unit"] == record["limit_unit"], (code, matrix, value)
                if "oxygen-saturation-criterion-not-derivable" not in mine["flags"]:  # the one sentence that names annual aggregates
                    assert mine["limit_basis"] == record["limit_basis"], (code, matrix, value)
                assert mine["status"] == record["status"] and mine["scored_value"] == record["scored_value"], (code, matrix, value)
                assert set(mine["flags"]) <= set(record["data_quality_flags"]), (code, matrix, value)
                checked += 1
    assert checked > 200


def change_site_context(country: str, category: str):
    from oah.indices.period_change import SiteContext

    return SiteContext("S", country, regime_of(category))


def test_the_regime_of_a_category_matches_the_measurement_records():
    assert regime_of("RW") == "surface" and regime_of("LW") == NO_LIMIT_REGIME


# --- from rows to cells -----------------------------------------------------------------------------------------------------


def monthly(code: str, unit: str, total: float, n: int = 1, month: int = 1, matrix: str = "W", site: str = "S1") -> MonthlyRow:
    return MonthlyRow("IT", site, "RW", code, matrix, unit, 2022, n, total / n, total / n, total / n, 0, 0, month, total)


LEAD = "CAS_7439-92-1"
TOTAL_P = "CAS_7723-14-0"
NITRATE = "CAS_14797-55-8"
CHLORIDE = "CAS_16887-00-6"
TURBIDITY = "EEA_3112-01-4"


def test_units_are_converted_per_row_and_the_basis_is_checked():
    rows = [monthly(LEAD, "ug/L", 2.0, month=1, matrix="W-DIS"), monthly(LEAD, "mg/L", 0.004, month=2, matrix="W-DIS")]
    cells, kept, context, excluded = to_cells(rows, Series(LEAD, "W-DIS"))
    assert excluded == 0 and len(kept) == 2 and context.unit == "ug/L" and context.closed_name == "Lead dissolved"
    assert [c.total for c in cells] == [2.0, pytest.approx(4.0)] and context.name == "Lead dissolved"
    phosphorus = [monthly(TOTAL_P, "mg{P}/L", 0.1, n=1), monthly(TOTAL_P, "mg{PO4}/L", 0.1, month=2)]
    cells, kept, context, excluded = to_cells(phosphorus, Series(TOTAL_P, "W"))
    assert excluded == 1 and len(cells) == 1 and cells[0].total == pytest.approx(0.1 * PO4_PER_P)  # PO4 reported twice is refused
    assert context.unit == "mg/L" and context.name == "Total phosphates"
    nitrate_as_n = [monthly(NITRATE, "mg{N}/L", 1.0)]
    assert to_cells(nitrate_as_n, Series(NITRATE, "W"))[3] == 1 and to_cells(nitrate_as_n, Series(NITRATE, "W"))[0] == []


def test_a_measurement_only_determinand_keeps_only_its_expected_unit():
    rows = [monthly(TURBIDITY, "{NTU}", 5.0), monthly(TURBIDITY, "mg/L", 5.0, month=2)]
    cells, _, context, excluded = to_cells(rows, Series(TURBIDITY, "W"))
    assert excluded == 1 and len(cells) == 1 and context.measurement_only and context.closed_name is None
    assert context.unit == "{NTU}" and context.group == "solids-turbidity"


def test_an_unmapped_determinand_keeps_the_unit_with_most_records_and_counts_the_rest():
    rows = [monthly(CHLORIDE, "mg/L", 30.0, n=3, month=1), monthly(CHLORIDE, "g/L", 0.03, n=1, month=2)]
    cells, _, context, excluded = to_cells(rows, Series(CHLORIDE, "W"))
    assert excluded == 1 and len(cells) == 1 and context.unit == "mg/L" and context.closed_name is None
    assert to_cells([], Series(CHLORIDE, "W"))[2].unit == ""


def test_a_month_without_a_quantified_value_becomes_a_cell_that_only_counts_below_loq():
    row = MonthlyRow("IT", "S1", "RW", NITRATE, "W", "mg{NO3}/L", 2022, 0, None, None, None, 2, 0, 4, 0.0)
    cells = to_cells([row], Series(NITRATE, "W"))[0]
    assert (cells[0].n, cells[0].n_below_loq, cells[0].low, cells[0].first_month) == (0, 2, None, month_position(2022, 4))


# --- which series a name stands for --------------------------------------------------------------------------------------


def test_every_listed_parameter_name_resolves_to_one_series():
    for name in parameter_names():
        series = resolve_series(name)
        assert series is not None and series.code in DETERMINANDS and series.matrix in MATRICES, name
        assert series.matrix in DETERMINANDS[series.code].stored_matrices or series.matrix in MATRICES
    assert resolve_series("Nitrate") == Series(NITRATE, "W")
    assert resolve_series("Lead dissolved") == Series(LEAD, "W-DIS")
    assert resolve_series("Lead and its compounds") == Series(LEAD, "W")  # the label: the matrix the mapping does not hold
    assert resolve_series("Chloride") == Series(CHLORIDE, "W")  # an unmapped label stands for whole water
    assert resolve_series("Dissolved organic carbon (DOC)") == Series("EEA_3133-05-9", "W-DIS")
    assert resolve_series("no such parameter") is None and resolve_series("") is None


def test_the_module_exposes_the_two_comparisons():
    assert callable(change.site_change) and callable(change.country_change)
    assert Period.parse("2021-01", "2021-12", "a").months == 12
