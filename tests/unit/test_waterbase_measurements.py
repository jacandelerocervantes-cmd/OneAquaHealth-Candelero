"""Annual Waterbase records against the limits: rivers scored with the existing machinery, everything else honest."""

from __future__ import annotations

from pathlib import Path
from typing import Any

import pytest
from waterbase_fixtures import build_fixture_store

from oah.indices.regimes import COUNTRY_SURFACE_LIMITS, PO4_PER_P
from oah.waterbase import store
from oah.waterbase.measurements import INDEX_STATUS, annual_record, regime_of, site_entry, site_info


@pytest.fixture()
def records(tmp_path: Path, monkeypatch) -> Any:
    path = build_fixture_store(tmp_path)
    monkeypatch.setenv("OAH_WATERBASE_STORE", str(path))

    def fetch(site_id: str, determinand: str | None = None, matrix: str | None = None) -> list[dict[str, Any]]:
        found = store.get_site(site_id)
        assert found is not None
        return [annual_record(found, row) for row in store.site_series(site_id, determinand, matrix=matrix)[1]]

    return fetch


def _one(records: list[dict[str, Any]], year: int = 2015) -> dict[str, Any]:
    matching = [r for r in records if r["year"] == year]
    assert len(matching) == 1
    return matching[0]


def test_italian_river_nitrate_is_scored_against_the_national_limit_on_the_annual_mean(records):
    record = _one(records("IT01-001025", "CAS_14797-55-8"))
    limit = COUNTRY_SURFACE_LIMITS["IT"]["Nitrate"]  # 1.2 mg/L N-NO3 as the ion
    assert record["parameter"] == "Nitrate" and record["unit"] == "mg/L" and record["original_unit"] == "mg{NO3}/L"
    assert (record["value"], record["min"], record["max"], record["n"], record["statistic"]) == (2.0, 1.0, 3.0, 2, "mean")
    assert record["limit"] == pytest.approx(limit) and record["limit_type"] == "maximum"
    assert record["status"] == "within-limit" and record["scored_value"] == 2.0  # 2 mg/L NO3 < 5.3 mg/L NO3
    assert record["limit_regime"] == "surface" and record["limit_country"] == "IT"
    assert record["limit_basis"].startswith("national: DM 260/2010 LIMeco (Italy)") and "unverified" in record["limit_basis"]
    assert record["origin"] == record["source"] == "real-eea-waterbase"
    assert (record["period_start"], record["period_end"], record["year"]) == ("2015-01-01", "2015-12-31", 2015)
    assert record["n_lower_reliability"] == 1 and "includes-lower-reliability-records" in record["data_quality_flags"]
    assert record["observation_id"] == "IT01-001025|CAS_14797-55-8|W|2015|mg{NO3}/L"


def test_total_phosphorus_is_converted_to_phosphate_and_compared_with_the_same_limit_basis(records):
    record = _one(records("IT01-001025", "CAS_7723-14-0"))
    assert record["parameter"] == "Total phosphates" and record["unit"] == "mg/L"
    assert record["original_unit"] == "mg{P}/L"
    assert record["value"] == pytest.approx(0.06 * PO4_PER_P)  # mean 0.06 as P, shown as PO4
    assert record["min"] == pytest.approx(0.04 * PO4_PER_P) and record["max"] == pytest.approx(0.08 * PO4_PER_P)
    assert record["limit"] == pytest.approx(0.100 * PO4_PER_P) and record["status"] == "within-limit"


def test_phosphorus_above_the_limit_exceeds_it_after_conversion(tmp_path: Path, monkeypatch):
    from waterbase_fixtures import TOTAL_P, obs

    path = build_fixture_store(tmp_path, rows=[obs(TOTAL_P, "0.15"), obs(TOTAL_P, "0.25", date="20150601")])
    monkeypatch.setenv("OAH_WATERBASE_STORE", str(path))
    found = store.get_site("IT01-001025")
    assert found is not None
    record = annual_record(found, store.site_series("IT01-001025")[1][0])
    assert record["status"] == "exceeds-limit"  # 0.20 mg/L P = 0.61 mg/L PO4 > 0.31


def test_greek_river_oxygen_below_the_minimum_exceeds(records):
    record = _one(records("EL000123", "EEA_3132-01-2"))
    assert record["parameter"] == "Dissolved Oxygen" and record["limit"] == 6.4 and record["limit_type"] == "minimum"
    assert record["value"] == pytest.approx(5.2) and record["status"] == "exceeds-limit"
    assert record["limit_country"] == "GR" and "HWQI" in record["limit_basis"]
    assert "includes-lower-reliability-records" in record["data_quality_flags"]  # one V record in the mean


def test_italian_oxygen_is_not_scored_because_its_criterion_is_per_sample(records):
    record = _one(records("IT01-001025", "EEA_3132-01-2"))
    assert record["status"] == "not-scored" and record["limit"] is None
    assert "oxygen-saturation-criterion-not-derivable" in record["data_quality_flags"]
    assert "saturation" in record["limit_basis"]


def test_water_temperature_is_interpretive_only_in_italy_and_greece(records):
    record = _one(records("IT01-001025", "EEA_3121-01-5"))
    assert record["status"] == "not-scored" and "interpretive-only" in record["data_quality_flags"] and record["limit"] is None
    assert record["value"] == 14.0 and record["unit"] == "Cel"


def test_ph_is_scored_against_the_two_sided_range_with_a_mean_warning(records):
    record = _one(records("IT01-001025", "EEA_3152-01-0"))
    assert record["value"] == 7.75 and record["limit_range"] == [6.5, 9.5] and record["status"] == "within-limit"
    assert "arithmetic-mean-of-ph" in record["data_quality_flags"]


def test_dissolved_lead_exceeds_the_eu_river_value_and_whole_water_lead_is_not_compared(records):
    dissolved = _one(records("IT01-001025", "CAS_7439-92-1", "W-DIS"))
    assert dissolved["parameter"] == "Lead dissolved" and dissolved["limit"] == 1.2  # Directive 2013/39/EU AA-EQS
    assert dissolved["value"] == 1.5 and dissolved["status"] == "exceeds-limit"
    assert dissolved["limit_basis"].startswith("legal: Directive 2013/39/EU")
    whole = _one(records("IT01-001025", "CAS_7439-92-1", "W"))
    assert whole["parameter"] == "Lead and its compounds" and whole["status"] == "not-scored"
    assert whole["limit"] is None and "no-limit-mapping" in whole["data_quality_flags"]
    assert "dissolved" in whole["limit_basis"] and whole["value"] == 4.0 and whole["unit"] == "ug/L"


def test_cadmium_needs_hardness_so_it_is_not_scored(records):
    record = _one(records("IT01-001025", "CAS_7440-43-9"))
    assert record["status"] == "not-scored" and "surface-limit-needs-hardness" in record["data_quality_flags"]


def test_unmapped_determinands_are_listed_but_not_compared(records):
    for code, label in (("EEA_3131-01-9", "Oxygen saturation"), ("CAS_16887-00-6", "Chloride"), ("CAS_14265-44-2", "Phosphate")):
        record = _one(records("IT01-001025", code))
        assert record["parameter"] == label and record["status"] == "not-scored" and record["limit"] is None
        assert "no-limit-mapping" in record["data_quality_flags"] and record["limit_basis"].startswith("not compared:")
    assert _one(records("IT01-001025", "CAS_16887-00-6"))["unit"] == "mg/L"  # shown as reported


def test_lakes_show_values_but_never_a_river_limit(records):
    record = _one(records("IT02-LAKE1", "CAS_14797-55-8"))
    assert record["limit_regime"] == "no-limit-regime" and regime_of("LW") == "no-limit-regime"
    assert record["status"] == "not-scored" and record["limit"] is None and record["limit_type"] is None
    assert record["value"] == 4.0 and record["unit"] == "mg/L"
    assert "no-limit-regime" in record["data_quality_flags"] and "lakes" in record["limit_basis"]


def test_a_basis_that_differs_from_the_expected_one_excludes_the_record(records):
    record = _one(records("NO0001", "CAS_14797-55-8"))
    assert record["status"] == "excluded" and "unit-mismatch" in record["data_quality_flags"]
    assert record["unit"] == "mg{N}/L" and record["value"] == pytest.approx(0.5) and record["limit"] is None


def test_below_loq_values_are_flagged_and_left_out_of_the_mean(records):
    record = _one(records("EL000123", "CAS_14798-03-9"))
    assert (record["n"], record["n_below_loq"], record["value"]) == (1, 2, 0.05)
    assert "below-loq-excluded-from-mean" in record["data_quality_flags"]
    assert record["status"] == "within-limit"  # 0.05 mg/L NH4 against the Greek value 0.06 x NH4_PER_N


def test_a_year_with_only_below_loq_values_is_indeterminate(records):
    record = _one(records("EL000123", "CAS_14797-65-0"), 2017)
    assert record["n"] == 0 and record["n_below_loq"] == 1 and record["value"] is None and record["min"] is None
    assert record["status"] == "indeterminate" and "all-below-loq" in record["data_quality_flags"]
    assert record["limit"] is not None  # the limit is still shown


def test_negative_concentrations_are_excluded_as_physically_impossible(tmp_path: Path, monkeypatch):
    from waterbase_fixtures import NITRATE, obs

    path = build_fixture_store(tmp_path, rows=[obs(NITRATE, "-3.0")])
    monkeypatch.setenv("OAH_WATERBASE_STORE", str(path))
    found = store.get_site("IT01-001025")
    assert found is not None
    record = annual_record(found, store.site_series("IT01-001025")[1][0])
    assert record["status"] == "excluded" and "physically-impossible" in record["data_quality_flags"]


def test_a_limits_file_override_applies_to_waterbase_records(records):
    from oah.indices import limit_overrides as lo

    lo.apply_overrides({
        "schema_version": 1, "note": "test",
        "limits": [{"regime": "surface", "country": "IT", "parameter": "Nitrate", "values": [1.0],
                    "unit": "mg/L", "source": "test file"}],
    })
    try:
        record = _one(records("IT01-001025", "CAS_14797-55-8"))
        assert record["limit"] == 1.0 and record["status"] == "exceeds-limit" and "override: test file" in record["limit_basis"]
    finally:
        lo.reset_overrides()


def test_site_entries_say_measurements_only_and_flag_a_missing_location(tmp_path: Path, monkeypatch):
    path = build_fixture_store(tmp_path)
    monkeypatch.setenv("OAH_WATERBASE_STORE", str(path))
    sites = {s.site_id: s for s in store.list_sites()[1]}
    located = site_entry(sites["IT01-001025"])
    assert located["status"] == INDEX_STATUS == "measurements-only" and located["ccme_wqi"] is None
    assert located["source"] == located["origin"] == "real-eea-waterbase" and located["kind"] == "water-body"
    assert located["location_status"] == "located" and (located["latitude"], located["longitude"]) == (44.65, 7.38)
    assert located["name"] == "PO - REVELLO" and located["limit_regime"] == "surface" and located["limit_country"] == "IT"
    assert "No CCME index" in located["reason"]
    nowhere = site_entry(sites["EL000123"])
    assert nowhere["location_status"] == "no-location" and nowhere["latitude"] is None and nowhere["limit_country"] == "GR"
    unnamed = site_entry(sites["IT02-LAKE1"])
    assert unnamed["name"] == "IT02-LAKE1" and unnamed["water_category"] == "lake" and unnamed["limit_regime"] == "no-limit-regime"
    info = site_info(sites["EL000123"])
    assert info["confidentiality"] == "N" and info["location_status"] == "no-location" and info["country"] == "GR"
