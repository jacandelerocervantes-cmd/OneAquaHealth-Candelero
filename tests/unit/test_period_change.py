"""The pure period comparison (oah.indices.period_change): arithmetic, coverage rules, paired sites, limits, properties.

All numbers are invented for the tests (SYNTHETIC) and chosen so that every expected value can be checked by hand.
"""

from __future__ import annotations

import copy
import math
from collections.abc import Sequence

import pytest
from hypothesis import given, settings
from hypothesis import strategies as st

from oah.indices import limit_overrides as lo
from oah.indices.period_change import (
    COMPARISON_DECIMALS,
    FEW_SITES_THRESHOLD,
    MIN_SAMPLES_PER_PERIOD,
    Cell,
    ParameterContext,
    Period,
    PeriodError,
    SiteContext,
    assess_mean,
    change_block,
    compare_country,
    compare_site,
    crossing,
    month_position,
    month_text,
    parse_year_month,
    period_stats,
)
from oah.indices.regimes import PO4_PER_P

NITRATE = ParameterContext("Nitrate", "mg/L", "water-chemistry", "Nitrate")
PHOSPHATES = ParameterContext("Total phosphates", "mg/L", "water-chemistry", "Total phosphates")
RIVER_IT = SiteContext("S1", "IT", "surface", "River Alpha")


def pos(year: int, month: int) -> int:
    return month_position(year, month)


def cell(site: str, year: int, month: int, values: Sequence[float], below: int = 0, unreliable: int = 0) -> Cell:
    """A monthly cell of the given quantified values (``below`` samples were under the quantification limit)."""
    first = pos(year, month)
    if not values:
        return Cell(site, first, first, 0, 0.0, None, None, below, unreliable)
    return Cell(site, first, first, len(values), math.fsum(values), min(values), max(values), below, unreliable)


def span(cells: Sequence[Cell]) -> tuple[int, int] | None:
    return (min(c.first_month for c in cells), max(c.last_month for c in cells)) if cells else None


A = Period.parse("2021-01", "2021-12", "a")
B = Period.parse("2023-01", "2023-12", "b")


def three_samples(site: str, year: int, mean: float) -> list[Cell]:
    """Three samples in three months of ``year`` whose mean is exactly ``mean``."""
    return [cell(site, year, 2, [mean - 1.0]), cell(site, year, 6, [mean]), cell(site, year, 10, [mean + 1.0])]


def site(cells: Sequence[Cell], parameter: ParameterContext = NITRATE, context: SiteContext = RIVER_IT, **kwargs):
    return compare_site(cells, parameter, context, A, B, data_range=span(cells), **kwargs)


# --- months and periods ---------------------------------------------------------------------------------------------------


def test_year_months_are_parsed_strictly():
    assert month_text(parse_year_month("2021-05")) == "2021-05" and parse_year_month("2021-05") == pos(2021, 5)
    assert parse_year_month(" 2021-05 ") == pos(2021, 5)
    for bad in ("2021-13", "2021-00", "2021-5", "21-05", "2021/05", "2021-05-01", "1899-12", "2101-01", "", None, 202105, "２０２１-05"):
        with pytest.raises(PeriodError):
            parse_year_month(bad)


def test_periods_must_not_be_inverted_or_longer_than_a_century():
    period = Period.parse("2021-05", "2026-05", "b")
    assert (period.start, period.end, period.months) == ("2021-05", "2026-05", 61)
    assert Period.parse("2021-05", "2021-05", "a").months == 1
    with pytest.raises(PeriodError, match="a_from must not be after a_to"):
        Period.parse("2021-06", "2021-05", "a")
    with pytest.raises(PeriodError):
        Period.parse("1900-01", "2100-12", "a")
    with pytest.raises(PeriodError, match="b_to"):
        Period.parse("2021-05", "nonsense", "b")


# --- the statistics ---------------------------------------------------------------------------------------------------------


def test_the_mean_is_the_sum_over_the_count_not_the_mean_of_monthly_means():
    cells = [cell("S1", 2021, 3, [1.0]), cell("S1", 2021, 7, [2.0, 4.0, 6.0])]
    stats = period_stats(cells, A)
    assert stats.n_samples == 4 and stats.mean == 13.0 / 4.0 == 3.25  # not (1 + 4) / 2 = 2.5
    assert (stats.low, stats.high, stats.n_months_with_data, stats.months_in_period) == (1.0, 6.0, 2, 12)


def test_how_the_samples_are_grouped_into_months_does_not_change_the_mean():
    values = [0.1, 0.7, 2.2, 3.9, 4.4, 9.0]
    together = period_stats([cell("S", 2021, 1, values)], A).mean
    apart = period_stats([cell("S", 2021, m + 1, [v]) for m, v in enumerate(values)], A).mean
    assert together == pytest.approx(apart, abs=1e-12) and together == pytest.approx(sum(values) / len(values))


def test_values_below_the_quantification_limit_are_counted_never_averaged():
    stats = period_stats([cell("S", 2021, 3, [2.0, 4.0], below=2), cell("S", 2021, 4, [], below=1)], A)
    assert (stats.n_samples, stats.n_below_loq, stats.mean) == (2, 3, 3.0)
    assert stats.below_loq_share == 3 / 5
    result = site([cell("S1", 2021, 3, [2.0, 4.0, 6.0], below=2), *three_samples("S1", 2023, 5.0)])
    assert "below-loq-excluded-bias-upward" in result["periods"]["a"]["flags"]
    assert "below-loq-excluded-bias-upward" not in result["periods"]["b"]["flags"]
    assert result["periods"]["a"]["below_loq_share"] == round(2 / 5, 6) and result["periods"]["a"]["n_below_loq"] == 2


def test_a_cell_outside_the_period_is_ignored_and_a_period_with_only_below_loq_values_has_no_mean():
    stats = period_stats([cell("S", 2020, 12, [100.0]), cell("S", 2021, 1, [], below=4), cell("S", 2022, 1, [100.0])], A)
    assert stats.n_samples == 0 and stats.mean is None and stats.low is None and stats.n_below_loq == 4 and stats.has_records


def test_the_mean_never_leaves_the_minimum_maximum_interval():
    value = 0.1 + 0.2  # a float whose repeated sums drift
    stats = period_stats([cell("S", 2021, m, [value] * 3) for m in range(1, 13)], A)
    assert stats.low is not None and stats.high is not None and stats.low <= stats.mean <= stats.high


# --- the change -------------------------------------------------------------------------------------------------------------


def test_absolute_and_relative_change_are_exact_and_antisymmetric_in_the_absolute_part():
    up = change_block(2.0, 3.0, "mg/L")
    assert up == {"absolute": 1.0, "relative_percent": 50.0, "relative_percent_note": None, "direction": "increased"}
    down = change_block(3.0, 2.0, "mg/L")
    assert down["absolute"] == -1.0 and down["relative_percent"] == -33.3333 and down["direction"] == "decreased"
    assert change_block(4.0, 1.0, "mg/L")["relative_percent"] == -75.0


def test_a_zero_or_missing_baseline_gives_no_relative_change_and_says_why():
    zero = change_block(0.0, 2.0, "mg/L")
    assert zero["relative_percent"] is None and zero["relative_percent_note"] == "baseline-zero" and zero["absolute"] == 2.0
    assert zero["direction"] == "increased"
    almost = change_block(4e-7, 2.0, "mg/L")  # zero after rounding to the comparison precision
    assert almost["relative_percent"] is None and almost["relative_percent_note"] == "baseline-zero"
    missing = change_block(None, 2.0, "mg/L")
    assert missing == {"absolute": None, "relative_percent": None, "relative_percent_note": "baseline-missing", "direction": None}
    assert change_block(2.0, None, "mg/L")["relative_percent_note"] == "comparison-missing"
    both = site([cell("S1", 2021, 1, [0.0, 0.0, 0.0]), *three_samples("S1", 2023, 3.0)])
    assert "relative-change-undefined" in both["flags"] and both["change"]["relative_percent"] is None


def test_the_direction_is_equality_after_rounding_and_nothing_more():
    assert COMPARISON_DECIMALS == 6
    assert change_block(1.0, 1.0000004, "mg/L")["direction"] == "no-change"  # below the rounding precision
    assert change_block(1.0, 1.000002, "mg/L")["direction"] == "increased"
    assert change_block(1.0, 0.999998, "mg/L")["direction"] == "decreased"
    assert change_block(1.0, 1.0004, "mg/L", decimals=2)["direction"] == "no-change"  # the precision is a parameter
    same = change_block(2.5, 2.5, "mg/L")
    assert same["absolute"] == 0.0 and same["relative_percent"] == 0.0 and not str(same["absolute"]).startswith("-")


def test_a_negative_baseline_keeps_the_sign_of_the_direction_and_interval_scales_are_flagged():
    cold = change_block(-2.0, -1.0, "Cel")
    assert cold["absolute"] == 1.0 and cold["relative_percent"] == 50.0 and cold["direction"] == "increased"  # divided by |baseline|
    assert cold["relative_percent_note"] == "interval-scale"
    assert change_block(7.0, 7.7, "pH")["relative_percent_note"] == "interval-scale"
    assert change_block(7.0, 7.7, "mg/L")["relative_percent_note"] is None


# --- coverage: minimum samples, data range, partial periods ----------------------------------------------------------------


def test_a_period_with_too_few_samples_is_insufficient_but_the_numbers_are_still_returned():
    cells = [cell("S1", 2021, 3, [1.0, 2.0]), *three_samples("S1", 2023, 5.0)]
    result = site(cells)
    assert MIN_SAMPLES_PER_PERIOD == 3 and result["status"] == "insufficient-data" and result["min_samples_per_period"] == 3
    assert result["periods"]["a"]["n_samples"] == 2 and result["periods"]["a"]["mean"] == 1.5
    assert result["periods"]["a"]["meets_minimum_samples"] is False and result["periods"]["b"]["meets_minimum_samples"] is True
    assert result["change"]["absolute"] == 3.5 and result["change"]["direction"] == "increased"  # still computed
    assert result["crossed_limit"] is None
    assert site(cells, min_samples=2)["status"] == "ok"  # the minimum is configurable


def test_a_period_beyond_the_data_is_reported_plainly_never_shifted_or_filled():
    """The 'May 2021 to May 2026' question against a store that ends in December 2024."""
    cells = [cell("S1", 2021, 5, [1.0, 2.0, 3.0]), cell("S1", 2024, 12, [4.0])]
    may_2021, may_2026 = Period.parse("2021-05", "2021-05", "a"), Period.parse("2026-05", "2026-05", "b")
    result = compare_site(cells, NITRATE, RIVER_IT, may_2021, may_2026, data_range=span(cells))
    assert result["data_range"] == {"first": "2021-05", "last": "2024-12"}  # the UI can propose the latest available
    b = result["periods"]["b"]
    assert b["n_samples"] == 0 and b["mean"] is None and b["n_months_with_data"] == 0
    assert "period-outside-data" in b["flags"] and "period-outside-data" not in result["periods"]["a"]["flags"]
    assert result["status"] == "insufficient-data" and "period-outside-data" in result["flags"]
    assert result["change"]["absolute"] is None and result["change"]["direction"] is None
    assert result["periods"]["a"]["mean"] == 2.0  # the period that exists is reported as it is


def test_a_period_that_ends_after_the_data_but_starts_inside_is_partial_and_outside():
    cells = [cell("S1", m_year, m, [1.0, 2.0, 3.0]) for m_year, m in ((2024, 1), (2024, 6), (2024, 12))]
    period = Period.parse("2024-01", "2025-12", "b")
    result = compare_site(cells, NITRATE, RIVER_IT, A, period, data_range=span(cells))
    flags = result["periods"]["b"]["flags"]
    assert "period-outside-data" in flags and "partial-period" in flags
    assert result["periods"]["b"]["n_months_with_data"] == 3 and result["periods"]["b"]["months_in_period"] == 24
    assert result["periods"]["b"]["mean"] == 2.0  # the months that exist, nothing imputed for 2025


def test_a_partial_period_inside_the_data_range_is_flagged_and_a_period_before_the_data_too():
    cells = [cell("S1", 2021, 2, [1.0]), cell("S1", 2021, 6, [1.0]), cell("S1", 2021, 10, [1.0]), *three_samples("S1", 2023, 2.0)]
    result = site(cells)
    assert "partial-period" in result["periods"]["a"]["flags"] and result["periods"]["a"]["n_months_with_data"] == 3
    early = compare_site(cells, NITRATE, RIVER_IT, Period.parse("2015-01", "2015-12", "a"), B, data_range=span(cells))
    assert "period-before-data" in early["periods"]["a"]["flags"] and early["periods"]["a"]["n_samples"] == 0
    complete = site([cell("S1", 2021, m, [1.0]) for m in range(1, 13)] + three_samples("S1", 2023, 1.0))
    assert "partial-period" not in complete["periods"]["a"]["flags"] and complete["periods"]["a"]["n_months_with_data"] == 12


def test_no_data_at_all_and_overlapping_periods_are_flagged():
    empty = compare_site([], NITRATE, RIVER_IT, A, B, data_range=None)
    assert empty["status"] == "insufficient-data" and empty["data_range"] == {"first": None, "last": None}
    assert {"no-data-for-scope", "period-outside-data"} <= set(empty["flags"])
    overlapping = compare_site(three_samples("S1", 2021, 2.0), NITRATE, RIVER_IT, A, Period.parse("2021-06", "2022-06", "b"), data_range=None)
    assert "periods-overlap" in overlapping["flags"]


# --- annual-only sources ------------------------------------------------------------------------------------------------------


def annual(site_id: str, year: int, value: float) -> Cell:
    """An annual aggregate (a sandbox record): ONE record covering the whole year."""
    return Cell(site_id, pos(year, 1), pos(year, 12), 1, value, value, value)


def test_an_annual_aggregate_counts_as_one_record_and_the_result_says_annual_only():
    parameter = ParameterContext("Nitrate", "mg/L", "water-chemistry", "Nitrate", resolution="annual-only")
    cells = [annual("S1", 2021, 2.0), annual("S1", 2023, 5.0)]
    result = compare_site(cells, parameter, RIVER_IT, A, B, data_range=span(cells))
    assert result["resolution"] == "annual-only" and "annual-only" in result["flags"]
    assert result["periods"]["a"]["n_unit"] == "aggregate-records" and result["periods"]["a"]["n_samples"] == 1
    assert result["periods"]["a"]["n_months_with_data"] == 12  # the months the aggregate covers, flagged, not monthly resolution
    assert result["min_samples_per_period"] == 1 and result["status"] == "ok"
    assert result["change"]["absolute"] == 3.0 and result["change"]["relative_percent"] == 150.0


def test_an_aggregate_that_crosses_the_period_edge_is_left_out_not_split():
    parameter = ParameterContext("Nitrate", "mg/L", "water-chemistry", "Nitrate", resolution="annual-only")
    cells = [annual("S1", 2021, 2.0), annual("S1", 2023, 5.0)]
    half_year = Period.parse("2021-05", "2021-12", "a")  # the 2021 aggregate covers January to December
    result = compare_site(cells, parameter, RIVER_IT, half_year, B, data_range=span(cells))
    assert result["periods"]["a"]["n_samples"] == 0 and result["periods"]["a"]["n_records_excluded_crossing_period_edge"] == 1
    assert "records-crossing-period-edge-excluded" in result["periods"]["a"]["flags"] and result["status"] == "insufficient-data"
    two_years = Period.parse("2021-01", "2022-12", "a")  # contains it: used
    assert compare_site(cells, parameter, RIVER_IT, two_years, B, data_range=span(cells))["periods"]["a"]["n_samples"] == 1


# --- a country: paired sites only -------------------------------------------------------------------------------------------


def country_sites(count: int) -> dict[str, SiteContext]:
    return {f"R{i}": SiteContext(f"R{i}", "IT", "surface") for i in range(1, count + 1)}


def run_country(cells_by_site, sites, parameter=PHOSPHATES, period_a=A, period_b=B, **kwargs):
    everything = [c for cells in cells_by_site.values() for c in cells]
    return compare_country(cells_by_site, sites, parameter, "IT", period_a, period_b, data_range=span(everything), **kwargs)


def test_only_sites_with_enough_data_in_both_periods_are_compared_and_nothing_is_imputed():
    cells = {
        "R1": three_samples("R1", 2021, 2.0) + three_samples("R1", 2023, 4.0),  # paired
        "R2": three_samples("R2", 2021, 9.0),  # only in period A
        "R3": three_samples("R3", 2023, 9.0),  # only in period B
        "R4": three_samples("R4", 2021, 9.0) + [cell("R4", 2023, 1, [9.0, 9.0])],  # two samples in B: below the minimum
        "R5": [cell("R5", 2019, 1, [9.0, 9.0, 9.0])],  # data, but in neither period: not considered at all
    }
    result = run_country(cells, country_sites(5))
    assert (result["n_sites_considered"], result["n_sites_paired"], result["n_sites_excluded"]) == (4, 1, 3)
    assert result["exclusion_reasons"] == {"absent-in-period-a": 1, "absent-in-period-b": 1, "insufficient-samples": 1}
    a, b = result["periods"]["a"], result["periods"]["b"]
    assert (a["n_sites"], b["n_sites"]) == (1, 1) and (a["n_samples"], b["n_samples"]) == (3, 3)  # the excluded sites' 9.0 are nowhere
    assert (a["mean_of_site_means"], b["mean_of_site_means"]) == (2.0, 4.0) and result["status"] == "ok"
    assert "few-sites" in result["flags"] and result["few_sites_threshold"] == FEW_SITES_THRESHOLD == 5


def test_the_site_statistics_median_of_changes_and_direction_counts_are_exact():
    a_means = [1.0, 2.0, 3.0, 4.0, 5.0, 6.0]
    b_means = [2.0, 2.0, 6.0, 2.0, 10.0, 3.0]
    cells = {f"R{i + 1}": three_samples(f"R{i + 1}", 2021, a) + three_samples(f"R{i + 1}", 2023, b) for i, (a, b) in enumerate(zip(a_means, b_means))}
    result = run_country(cells, country_sites(6))
    assert result["n_sites_paired"] == 6 and "few-sites" not in result["flags"]
    assert result["periods"]["a"]["mean_of_site_means"] == 3.5 and result["periods"]["b"]["mean_of_site_means"] == round(25 / 6, 6)
    change = result["change_of_site_means"]
    assert change["absolute"] == round(25 / 6 - 3.5, 6) and change["relative_percent"] == round((25 / 6 - 3.5) / 3.5 * 100, 4)
    # per-site relative changes: +100, 0, +100, -50, +100, -50  ->  sorted -50, -50, 0, 100, 100, 100  ->  median (0 + 100) / 2
    assert result["median_site_relative_change_percent"] == 50.0
    assert (result["sites_increased"], result["sites_decreased"], result["sites_unchanged"]) == (3, 2, 1)
    assert result["periods"]["a"]["n_samples"] == 18 and result["periods"]["a"]["n_months_with_data"] == 3


def test_few_sites_flag_follows_the_threshold_and_a_zero_baseline_site_has_no_relative_change():
    def sites_with(count: int):
        return {f"R{i}": three_samples(f"R{i}", 2021, 2.0) + three_samples(f"R{i}", 2023, 3.0) for i in range(1, count + 1)}

    assert "few-sites" in run_country(sites_with(4), country_sites(4))["flags"]
    assert "few-sites" not in run_country(sites_with(5), country_sites(5))["flags"]
    assert "few-sites" in run_country(sites_with(2), country_sites(2), few_sites=3)["flags"]  # the threshold is a parameter
    cells = sites_with(3)
    cells["R1"] = [cell("R1", 2021, 1, [0.0, 0.0, 0.0])] + three_samples("R1", 2023, 3.0)
    result = run_country(cells, country_sites(3))
    assert result["n_sites_relative_change_undefined"] == 1 and result["median_site_relative_change_percent"] == 50.0
    assert result["sites_increased"] == 3


def test_a_country_without_a_paired_site_is_insufficient_and_still_reports_the_counts():
    cells = {"R1": three_samples("R1", 2021, 2.0), "R2": three_samples("R2", 2023, 2.0)}
    result = run_country(cells, country_sites(2))
    assert result["status"] == "insufficient-data" and result["n_sites_paired"] == 0 and result["n_sites_excluded"] == 2
    assert result["periods"]["a"]["mean_of_site_means"] is None and result["change_of_site_means"]["direction"] is None
    assert result["median_site_relative_change_percent"] is None and "few-sites" not in result["flags"]


def test_a_country_period_beyond_the_data_is_reported_with_the_data_range():
    cells = {"R1": three_samples("R1", 2021, 2.0) + three_samples("R1", 2024, 3.0)}
    beyond = Period.parse("2026-05", "2026-05", "b")
    result = run_country(cells, country_sites(1), period_b=beyond)
    assert result["data_range"] == {"first": "2021-02", "last": "2024-10"}
    assert "period-outside-data" in result["periods"]["b"]["flags"] and result["status"] == "insufficient-data"


# --- limits ------------------------------------------------------------------------------------------------------------------


def test_a_river_with_a_country_regime_crosses_the_limit_and_the_basis_is_reported():
    cells = three_samples("S1", 2021, 0.1) + three_samples("S1", 2023, 0.5)
    result = site(cells, PHOSPHATES)
    a, b = result["periods"]["a"]["assessment"], result["periods"]["b"]["assessment"]
    limit = round(0.100 * PO4_PER_P, 6)  # Italy, DM 260/2010 LIMeco: 100 ug/l P, compared as phosphate
    assert a["limit"] == b["limit"] == limit and a["limit_type"] == "maximum" and a["limit_unit"] == "mg/L"
    assert a["limit_basis"].startswith("national: DM 260/2010 LIMeco (Italy)") and a["limit_regime"] == "surface"
    assert (a["status"], b["status"]) == ("within-limit", "exceeds-limit")
    assert result["crossed_limit"] == "within-to-exceeds"
    reverse = compare_site(cells, PHOSPHATES, RIVER_IT, B, A, data_range=span(cells))
    assert reverse["crossed_limit"] == "exceeds-to-within"
    steady = site(three_samples("S1", 2021, 0.1) + three_samples("S1", 2023, 0.12), PHOSPHATES)
    assert steady["crossed_limit"] == "none"


def test_the_greek_regime_and_a_country_without_a_national_table_use_their_own_limits():
    greek = SiteContext("G1", "GR", "surface")
    result = compare_site(three_samples("G1", 2021, 0.1) + three_samples("G1", 2023, 0.2), PHOSPHATES, greek, A, B,
                          data_range=(pos(2021, 2), pos(2023, 10)))
    assert result["periods"]["a"]["assessment"]["limit"] == round(0.165 * PO4_PER_P, 6)
    assert result["periods"]["a"]["assessment"]["limit_basis"].startswith("national: HWQI")
    norway = SiteContext("N1", "NO", "surface")
    nitrate = compare_site(three_samples("N1", 2021, 10.0) + three_samples("N1", 2023, 60.0), NITRATE, norway, A, B,
                           data_range=(pos(2021, 2), pos(2023, 10)))
    assert nitrate["periods"]["a"]["assessment"]["limit"] == 50.0
    assert nitrate["periods"]["a"]["assessment"]["limit_basis"].startswith("proxy, drinking-water value on a river site")
    assert nitrate["crossed_limit"] == "within-to-exceeds"


def test_a_lake_a_measurement_only_parameter_and_an_unmapped_one_have_no_limit_and_no_crossing():
    lake = SiteContext("L1", "IT", "no-limit-regime")
    cells = three_samples("L1", 2021, 0.1) + three_samples("L1", 2023, 9.0)
    result = compare_site(cells, PHOSPHATES, lake, A, B, data_range=span(cells))
    for key in ("a", "b"):
        assessment = result["periods"][key]["assessment"]
        assert assessment["limit"] is None and assessment["status"] == "not-scored" and assessment["limit_regime"] == "no-limit-regime"
        assert "lakes" in assessment["limit_basis"] and assessment["flags"] == ["no-limit-regime"]
    assert result["crossed_limit"] is None and result["change"]["direction"] == "increased"  # the data is still delivered
    turbidity = ParameterContext("Turbidity", "{NTU}", "solids-turbidity", None, measurement_only=True)
    measured = site(cells, turbidity)
    assessment = measured["periods"]["b"]["assessment"]
    assert assessment["limit"] is None and assessment["limit_regime"] == "no-limit-regime"
    assert assessment["flags"] == ["no-limit-regime", "measurement-only"] and "measurement only" in assessment["limit_basis"]
    assert measured["crossed_limit"] is None and measured["change"]["absolute"] == 8.9
    chloride = ParameterContext("Chloride", "mg/L", "water-chemistry", None)
    assert site(cells, chloride)["periods"]["a"]["assessment"]["flags"] == ["no-limit-mapping"]


def test_parameters_the_existing_machinery_does_not_score_are_not_scored_here_either():
    oxygen = ParameterContext("Dissolved Oxygen", "mg/L", "water-chemistry", "Dissolved Oxygen")
    italian = assess_mean(oxygen, RIVER_IT, 9.0, pos(2023, 12))
    assert italian["status"] == "not-scored" and italian["flags"] == ["oxygen-saturation-criterion-not-derivable"]
    greek_oxygen = assess_mean(oxygen, SiteContext("G", "GR", "surface"), 5.0, pos(2023, 12))
    assert greek_oxygen["limit"] == 6.4 and greek_oxygen["limit_type"] == "minimum" and greek_oxygen["status"] == "exceeds-limit"
    temperature = ParameterContext("Water temperature", "Cel", "water-chemistry", "Water temperature")
    assert assess_mean(temperature, RIVER_IT, 30.0, pos(2023, 12))["flags"] == ["interpretive-only"]
    cadmium = ParameterContext("Cadmium dissolved", "ug/L", "water-chemistry", "Cadmium dissolved")
    assert assess_mean(cadmium, RIVER_IT, 1.0, pos(2023, 12))["flags"] == ["surface-limit-needs-hardness"]
    none_quantified = assess_mean(NITRATE, SiteContext("N", "NO", "surface"), None, pos(2023, 12))
    assert none_quantified["status"] == "indeterminate" and none_quantified["limit"] == 50.0
    assert assess_mean(NITRATE, SiteContext("N", "NO", "surface"), -1.0, pos(2023, 12))["status"] == "excluded"


def test_the_ph_range_is_used_for_a_period_mean():
    ph = ParameterContext("pH", "pH", "water-chemistry", "pH")
    cells = three_samples("S1", 2021, 7.0) + three_samples("S1", 2023, 9.7)
    result = site(cells, ph)
    inside, outside = result["periods"]["a"]["assessment"], result["periods"]["b"]["assessment"]
    assert inside["limit_range"] == [6.5, 9.5] and inside["status"] == "within-limit"
    assert outside["status"] == "exceeds-limit" and outside["limit"] == 9.5 and outside["limit_type"] == "maximum"
    assert result["crossed_limit"] == "within-to-exceeds" and "relative-change-interval-scale" in result["flags"]


def test_a_dated_limit_is_judged_at_the_end_of_the_period():
    lead = ParameterContext("Lead dissolved", "ug/L", "water-chemistry", "Lead dissolved")
    drinking = SiteContext("D", None, "drinking")
    assert assess_mean(lead, drinking, 7.0, pos(2035, 12))["limit"] == 10.0
    assert assess_mean(lead, drinking, 7.0, pos(2036, 1))["limit"] == 5.0  # 12 January 2036: the stricter value from the end of the period


def test_crossing_needs_both_periods_to_be_judged():
    assert crossing("within-limit", "exceeds-limit") == "within-to-exceeds"
    assert crossing("exceeds-limit", "within-limit") == "exceeds-to-within"
    assert crossing("exceeds-limit", "exceeds-limit") == crossing("within-limit", "within-limit") == "none"
    for status in ("not-scored", "indeterminate", "excluded"):
        assert crossing(status, "within-limit") is None and crossing("within-limit", status) is None


def test_the_country_counts_river_sites_over_the_limit_and_leaves_lakes_out():
    limit = 0.100 * PO4_PER_P  # 0.3066 mg/L
    means_a, means_b = [0.1, 0.2, 0.4, 0.5], [0.4, 0.5, 0.45, 0.1]
    cells = {f"R{i + 1}": three_samples(f"R{i + 1}", 2021, a) + three_samples(f"R{i + 1}", 2023, b) for i, (a, b) in enumerate(zip(means_a, means_b))}
    cells["L1"] = three_samples("L1", 2021, 9.0) + three_samples("L1", 2023, 9.0)
    sites = {**country_sites(4), "L1": SiteContext("L1", "IT", "no-limit-regime")}
    result = run_country(cells, sites)
    assert result["n_sites_paired"] == 5
    a, b = result["periods"]["a"], result["periods"]["b"]
    assert (a["river_sites_judged"], a["river_sites_over_limit"]) == (4, 2)  # 0.4 and 0.5 exceed 0.3066 in period A
    assert (b["river_sites_judged"], b["river_sites_over_limit"]) == (4, 3)  # 0.4, 0.5 and 0.45 exceed 0.3066 in period B
    assert all(m > limit for m in (0.4, 0.5, 0.45)) and 0.2 < limit
    assert result["river_limit"]["a"]["limit"] == round(limit, 6) and result["river_limit"]["a"]["limit_basis"].startswith("national: DM 260/2010")
    assert result["river_limit"]["a"]["limit_regime"] == "surface"


def test_a_limits_file_override_is_applied_to_the_period_mean_and_named_in_the_basis():
    before = {name: copy.deepcopy(table) for name, table in lo._tables().items()}
    try:
        lo.apply_overrides(
            {"schema_version": 1, "note": "test", "limits": [
                {"regime": "surface", "country": "IT", "parameter": "Total phosphates", "values": [0.25], "unit": "mg/L", "source": "test source"}
            ]},
            "test",
        )
        result = site(three_samples("S1", 2021, 0.2) + three_samples("S1", 2023, 0.3), PHOSPHATES)
        assessment = result["periods"]["a"]["assessment"]
        assert assessment["limit"] == 0.25 and assessment["limit_basis"].startswith("override: test source")
        assert result["crossed_limit"] == "within-to-exceeds"
    finally:
        lo.reset_overrides()
        for name, table in lo._tables().items():
            table.clear()
            table.update(before[name])
        lo._ORIGINALS = None


# --- properties --------------------------------------------------------------------------------------------------------------


month_in_window = st.integers(min_value=0, max_value=35)  # 36 months: 2021-01 to 2023-12
value = st.floats(min_value=0.0, max_value=1000.0, allow_nan=False, allow_infinity=False)
sample_lists = st.lists(st.lists(value, min_size=1, max_size=5), min_size=0, max_size=12)


def cells_from(site_id: str, groups: list[list[float]], months: list[int]) -> list[Cell]:
    return [cell(site_id, 2021 + months[i % len(months)] // 12, months[i % len(months)] % 12 + 1, values) for i, values in enumerate(groups)]


@settings(max_examples=120, deadline=None)
@given(groups=sample_lists, months=st.lists(month_in_window, min_size=1, max_size=12))
def test_property_swapping_the_periods_negates_the_absolute_change(groups, months):
    cells = cells_from("S1", groups, months)
    forward = compare_site(cells, NITRATE, RIVER_IT, A, B, data_range=span(cells))
    backward = compare_site(cells, NITRATE, RIVER_IT, B, A, data_range=span(cells))
    assert forward["periods"]["a"]["mean"] == backward["periods"]["b"]["mean"]
    assert forward["periods"]["b"]["mean"] == backward["periods"]["a"]["mean"]
    f, b = forward["change"], backward["change"]
    if f["absolute"] is None:
        assert b["absolute"] is None
    else:
        assert f["absolute"] == -b["absolute"] or (f["absolute"] == 0.0 and b["absolute"] == 0.0)
        opposite = {"increased": "decreased", "decreased": "increased", "no-change": "no-change"}
        assert b["direction"] == opposite[f["direction"]]


@settings(max_examples=120, deadline=None)
@given(groups=sample_lists, months=st.lists(month_in_window, min_size=1, max_size=12))
def test_property_the_mean_lies_between_the_minimum_and_the_maximum_and_is_sum_over_n(groups, months):
    cells = cells_from("S1", groups, months)
    result = compare_site(cells, NITRATE, RIVER_IT, Period.parse("2021-01", "2023-12", "a"), B, data_range=span(cells))
    period = result["periods"]["a"]
    if period["n_samples"] == 0:
        assert period["mean"] is None and period["min"] is None
        return
    assert period["min"] - 1e-6 <= period["mean"] <= period["max"] + 1e-6
    every = [v for values in groups for v in values]
    assert period["n_samples"] == len(every)
    assert period["mean"] == pytest.approx(math.fsum(every) / len(every), abs=1e-5)


@settings(max_examples=60, deadline=None)
@given(
    data=st.dictionaries(
        st.sampled_from(["R1", "R2", "R3", "R4", "R5", "R6"]),
        st.tuples(sample_lists, sample_lists),
        min_size=1, max_size=6,
    )
)
def test_property_the_paired_set_and_the_counts_are_symmetric(data):
    cells: dict[str, list[Cell]] = {}
    for site_id, (first, second) in data.items():
        cells[site_id] = cells_from(site_id, first, [0, 4, 8]) + cells_from(site_id, second, [24, 28, 32])
    sites = {site_id: SiteContext(site_id, "IT", "surface") for site_id in cells}
    everything = [c for group in cells.values() for c in group]
    forward = compare_country(cells, sites, NITRATE, "IT", A, B, data_range=span(everything))
    backward = compare_country(cells, sites, NITRATE, "IT", B, A, data_range=span(everything))
    assert forward["n_sites_paired"] == backward["n_sites_paired"]
    assert forward["n_sites_considered"] == backward["n_sites_considered"] and forward["n_sites_excluded"] == backward["n_sites_excluded"]
    assert forward["periods"]["a"]["mean_of_site_means"] == backward["periods"]["b"]["mean_of_site_means"]
    assert forward["sites_increased"] == backward["sites_decreased"] and forward["sites_unchanged"] == backward["sites_unchanged"]
    assert forward["periods"]["a"]["n_sites"] == forward["periods"]["b"]["n_sites"] == forward["n_sites_paired"]  # one site set for both


@settings(max_examples=80, deadline=None)
@given(values=st.lists(value, min_size=1, max_size=40), cuts=st.lists(st.integers(min_value=0, max_value=40), max_size=6))
def test_property_regrouping_the_samples_into_months_never_changes_the_mean(values, cuts):
    edges = sorted({0, len(values), *(c for c in cuts if c <= len(values))})
    chunks = [values[i:j] for i, j in zip(edges, edges[1:]) if values[i:j]]
    grouped = [cell("S", 2021, (index % 12) + 1, chunk) for index, chunk in enumerate(chunks)]
    one_by_one = [cell("S", 2021, (index % 12) + 1, [v]) for index, v in enumerate(values)]
    a = period_stats(grouped, A)
    b = period_stats(one_by_one, A)
    assert a.n_samples == b.n_samples == len(values)
    assert a.mean == pytest.approx(b.mean, abs=1e-9)
