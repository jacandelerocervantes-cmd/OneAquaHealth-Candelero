"""Period comparison over the monthly Waterbase store and the annual sandbox records: store, routes, errors, localisation.

Every row is SYNTHETIC (invented values in temporary directories, see ``waterbase_fixtures``); nothing is a measurement.
No test uses the network or the real archive.
"""

from __future__ import annotations

import sqlite3
from pathlib import Path
from typing import Any

import pytest
from fastapi.testclient import TestClient
from waterbase_fixtures import NITRATE, build_fixture_store

import oah.api.app as app_module
import oah.api.deps as deps_module
from oah.api.rate_limit import RateLimiter
from oah.i18n.strings import ENGLISH, load_strings
from oah.indices.regimes import NO3_PER_N, PO4_PER_P
from oah.waterbase import store
from oah.waterbase.build import DDL
from oah.waterbase.store import month_position

from period_fixtures import LAKE, LOCATIONS, OBSERVATIONS, PERIODS, S1, S2, rows


@pytest.fixture(autouse=True)
def _world(monkeypatch):
    monkeypatch.setattr(deps_module, "get_rate_limiter", lambda: RateLimiter(10_000, 60.0))
    monkeypatch.setattr(deps_module, "get_cached_observations", lambda: OBSERVATIONS)
    monkeypatch.setattr(deps_module, "get_cached_locations", lambda: LOCATIONS)


@pytest.fixture()
def http() -> TestClient:
    return TestClient(app_module.app)


@pytest.fixture()
def built(tmp_path: Path, monkeypatch) -> Path:
    path = build_fixture_store(tmp_path, rows=rows())
    monkeypatch.setenv("OAH_WATERBASE_STORE", str(path))
    return path


def change(http: TestClient, site: str, parameter: str, periods: str = PERIODS, extra: str = "") -> Any:
    return http.get(f"/sites/{site}/change?parameter={parameter}&{periods}{extra}")


# --- the monthly store ----------------------------------------------------------------------------------------------------


def test_the_store_is_monthly_and_the_annual_view_is_the_sum_of_sums_over_the_sum_of_counts(built):
    nitrate = NITRATE[0]
    total, months = store.site_monthly_series(S1, nitrate, month_position(2021, 1), month_position(2021, 12))
    assert total == 2 and [(m.month, m.n, m.sum_value, m.mean, m.min, m.max) for m in months] == [
        (5, 2, 30.0, 15.0, 10.0, 20.0), (6, 1, 30.0, 30.0, 30.0, 30.0),
    ]
    annual = [row for row in store.site_series(S1, nitrate)[1] if row.year == 2021][0]
    assert (annual.n, annual.mean, annual.min, annual.max) == (3, 20.0, 10.0, 30.0)  # 60 / 3, not (15 + 30) / 2 = 22.5
    assert store.provenance()["schema_version"] == "3"


def test_the_monthly_reader_is_bounded_ordered_and_parameterised(built):
    assert store.site_monthly_series(S1, limit=3)[0] > 3 and len(store.site_monthly_series(S1, limit=3)[1]) == 3
    assert len(store.site_monthly_series(S1, limit=0)[1]) == 1 and len(store.site_monthly_series(S1, limit=10**9)[1]) <= store.MAX_SERIES
    ordered = [(r.year, r.month) for r in store.site_monthly_series(S1, NITRATE[0])[1]]
    assert ordered == sorted(ordered)
    only_2024 = store.site_monthly_series(S1, NITRATE[0], month_position(2024, 1), month_position(2024, 12))[1]
    assert [(r.year, r.month, r.n) for r in only_2024] == [(2024, 12, 1)]
    for text in ("'; DROP TABLE measurements; --", "x' OR '1'='1"):
        assert store.site_monthly_series(S1, text) == (0, [])
        assert store.site_monthly_series(text) == (0, [])
        assert store.scope_monthly_rows(text, "W", [(0, 10**6)], country="IT")[0] == []
        assert store.scope_monthly_rows(NITRATE[0], text, [(0, 10**6)], site_id=S1)[0] == []
        assert store.scope_monthly_rows(NITRATE[0], "W", [(0, 10**6)], country=text)[0] == []
    assert store.list_sites()[0] > 0  # the tables are intact


def test_a_scope_read_returns_the_windows_and_the_whole_data_range(built):
    window = (month_position(2023, 1), month_position(2023, 12))
    rows, data_range, truncated = store.scope_monthly_rows(NITRATE[0], "W", [window], site_id=S1)
    assert [(r.year, r.month) for r in rows] == [(2023, 2), (2023, 6), (2023, 10)] and not truncated
    assert data_range == (month_position(2021, 5), month_position(2024, 12))  # the range ignores the window
    rows, data_range, _ = store.scope_monthly_rows(NITRATE[0], "W", [window], country="it")
    assert {r.site_id for r in rows} == {S1, S2, LAKE} and data_range == (month_position(2021, 1), month_position(2024, 12))
    assert store.scope_monthly_rows(NITRATE[0], "W", [], country="IT") == ([], None, False)
    assert store.scope_monthly_rows(NITRATE[0], "W", [window], country="DE") == ([], None, False)
    many = [(i, i) for i in range(50)]
    assert store.scope_monthly_rows(NITRATE[0], "W", many, site_id=S1)[0] == []  # at most MAX_WINDOWS windows are read
    with pytest.raises(ValueError):
        store.scope_monthly_rows(NITRATE[0], "W", [window])
    with pytest.raises(ValueError):
        store.scope_monthly_rows(NITRATE[0], "W", [window], site_id=S1, country="IT")


def test_countries_carry_the_first_and_last_month_of_each_source(http, built):
    body = http.get("/countries").json()
    by_code = {c["code"]: {s["source"]: s for s in c["sources"]} for c in body["countries"]}
    assert by_code["IT"]["real-eea-waterbase"]["data_range"] == {"first": "2021-01", "last": "2024-12"}
    assert by_code["GR"]["real-eea-waterbase"]["data_range"] == {"first": "2015-03", "last": "2015-06"}
    assert by_code["NO"]["real-eea-waterbase"]["data_range"] == {"first": "2015-03", "last": "2015-06"}
    assert by_code["GR"]["real-sandbox"]["data_range"] == {"first": "2018-01", "last": "2021-12"}  # the censored 2021 record is a record
    assert by_code["IT"]["real-sandbox"]["data_range"] == {"first": "2018-01", "last": "2019-12"}
    assert by_code["NO"]["real-sandbox"]["data_range"] is None  # no sandbox record: null, never a guess


def test_without_a_store_the_countries_have_no_waterbase_range(http, tmp_path: Path, monkeypatch):
    monkeypatch.setenv("OAH_WATERBASE_STORE", str(tmp_path / "absent.sqlite"))
    body = http.get("/countries").json()
    for country in body["countries"]:
        assert [s["source"] for s in country["sources"]] == ["real-sandbox"]


# --- GET /sites/{id}/change, Waterbase ---------------------------------------------------------------------------------------


def test_a_river_site_crosses_its_country_limit_and_the_numbers_are_exact(http, built):
    response = change(http, S1, "Total phosphates")
    assert response.status_code == 200, response.text
    body = response.json()
    assert body["origin"] == body["source"] == "real-eea-waterbase" and body["attribution"].startswith("EEA Waterbase")
    assert body["data_freshness"]["status"] == "snapshot" and body["language"] == "en"
    assert body["scope"] == {"type": "site", "id": S1, "name": "PO - REVELLO", "country": "IT", "water_category": "river", "regime": "surface"}
    assert (body["parameter"], body["unit"], body["group"], body["resolution"]) == ("Total phosphates", "mg/L", "water-chemistry", "monthly")
    a, b = body["periods"]["a"], body["periods"]["b"]
    assert (a["start"], a["end"], a["n_samples"], a["n_months_with_data"], a["n_below_loq"]) == ("2021-01", "2021-12", 3, 3, 0)
    assert a["mean"] == pytest.approx(0.04 * PO4_PER_P, abs=1e-6) and b["mean"] == pytest.approx(0.12 * PO4_PER_P, abs=1e-6)
    assert (b["n_samples"], b["n_below_loq"], b["below_loq_share"]) == (3, 1, 0.25)
    assert "below-loq-excluded-bias-upward" in b["flags"] and "below-loq-excluded-bias-upward" not in a["flags"]
    assert "partial-period" in a["flags"] and a["meets_minimum_samples"] is True
    assert body["change"]["direction"] == "increased" and body["change"]["relative_percent"] == 200.0
    assert body["change"]["absolute"] == pytest.approx(0.08 * PO4_PER_P, abs=1e-6)
    assert a["assessment"]["limit"] == pytest.approx(0.1 * PO4_PER_P, abs=1e-6) and a["assessment"]["status"] == "within-limit"
    assert b["assessment"]["status"] == "exceeds-limit" and a["assessment"]["limit_basis"].startswith("national: DM 260/2010 LIMeco (Italy)")
    assert body["crossed_limit"] == "within-to-exceeds" and body["status"] == "ok"
    assert body["data_range"] == {"first": "2021-03", "last": "2023-08"} and body["rows_excluded_unit"] == 0


def test_the_may_2021_to_may_2026_question_reports_the_data_range_and_changes_nothing(http, built):
    body = change(http, S1, "Nitrate", "a_from=2021-05&a_to=2021-05&b_from=2026-05&b_to=2026-05").json()
    assert body["data_range"] == {"first": "2021-05", "last": "2024-12"}  # the latest available month the UI can propose
    b = body["periods"]["b"]
    assert (b["start"], b["end"], b["n_samples"], b["mean"]) == ("2026-05", "2026-05", 0, None)  # not shifted, not filled
    assert "period-outside-data" in b["flags"] and "period-outside-data" in body["flags"]
    assert body["status"] == "insufficient-data" and body["change"]["absolute"] is None
    assert body["periods"]["a"]["n_samples"] == 2 and body["periods"]["a"]["mean"] == 15.0  # May 2021 is reported as it is
    latest = change(http, S1, "Nitrate", "a_from=2023-01&a_to=2023-12&b_from=2024-12&b_to=2024-12").json()
    assert latest["periods"]["b"]["n_samples"] == 1 and latest["periods"]["b"]["mean"] == 60.0 and latest["status"] == "insufficient-data"


def test_a_measurement_only_parameter_is_delivered_without_a_limit(http, built):
    body = change(http, S1, "Turbidity").json()
    assert (body["group"], body["unit"], body["status"]) == ("solids-turbidity", "{NTU}", "ok")
    assert (body["periods"]["a"]["mean"], body["periods"]["b"]["mean"]) == (6.0, 12.0)
    assert body["change"] == {"absolute": 6.0, "relative_percent": 100.0, "relative_percent_note": None, "direction": "increased"}
    assessment = body["periods"]["b"]["assessment"]
    assert assessment["limit"] is None and assessment["limit_regime"] == "no-limit-regime" and assessment["status"] == "not-scored"
    assert assessment["flags"] == ["no-limit-regime", "measurement-only"] and body["crossed_limit"] is None


def test_a_lake_has_no_limit_regime_and_the_data_is_still_delivered(http, built):
    body = change(http, LAKE, "Nitrate").json()
    assert body["scope"]["water_category"] == "lake" and body["scope"]["regime"] == "no-limit-regime"
    assert (body["periods"]["a"]["mean"], body["periods"]["b"]["mean"]) == (4.0, 6.0) and body["change"]["relative_percent"] == 50.0
    assert body["periods"]["a"]["assessment"]["limit"] is None and body["crossed_limit"] is None


def test_a_river_nitrate_period_is_judged_with_the_italian_limit_in_the_ion_basis(http, built):
    body = change(http, S2, "Nitrate").json()
    limit = round(1.2 * NO3_PER_N, 6)
    assert body["periods"]["a"]["assessment"]["limit"] == limit and body["periods"]["a"]["assessment"]["status"] == "within-limit"  # 5.0 < 5.31
    assert body["periods"]["b"]["assessment"]["status"] == "exceeds-limit" and body["crossed_limit"] == "within-to-exceeds"


def test_a_unit_that_cannot_be_used_is_left_out_and_counted_never_converted(http, built):
    body = change(http, "NO0001", "Nitrate", "a_from=2015-01&a_to=2015-12&b_from=2016-01&b_to=2016-12").json()
    assert body["rows_excluded_unit"] == 2 and body["periods"]["a"]["n_samples"] == 0 and body["status"] == "insufficient-data"


def test_the_parameter_name_is_case_insensitive_and_a_label_selects_its_listed_matrix(http, built):
    assert change(http, S1, "total%20PHOSPHATES").json()["parameter"] == "Total phosphates"
    other = change(http, S1, "Total%20phosphorus").json()  # the Waterbase label: the W-DIS matrix, which the store does not hold for this site
    assert other["periods"]["a"]["n_samples"] == 0 and other["periods"]["a"]["assessment"]["flags"] == ["no-limit-mapping"]


# --- errors ---------------------------------------------------------------------------------------------------------------


@pytest.mark.parametrize(
    "query",
    [
        "parameter=Nitrate&a_from=2021-12&a_to=2021-01&b_from=2023-01&b_to=2023-12",  # inverted period A
        "parameter=Nitrate&a_from=2021-01&a_to=2021-12&b_from=2023-12&b_to=2023-01",  # inverted period B
        "parameter=Nitrate&a_from=2021-13&a_to=2021-12&b_from=2023-01&b_to=2023-12",  # month 13
        "parameter=Nitrate&a_from=2021-1&a_to=2021-12&b_from=2023-01&b_to=2023-12",  # not YYYY-MM
        "parameter=Nitrate&a_from=2021-01-01&a_to=2021-12&b_from=2023-01&b_to=2023-12",  # a date, not a month
        "parameter=Nitrate&a_from=1800-01&a_to=1800-12&b_from=2023-01&b_to=2023-12",  # a year outside 1900-2100
        "parameter=Nitrate&a_from=1900-01&a_to=2100-12&b_from=2023-01&b_to=2023-12",  # longer than a century
        "parameter=Nitrate&a_from=%00&a_to=2021-12&b_from=2023-01&b_to=2023-12",
        "parameter=Unobtainium&a_from=2021-01&a_to=2021-12&b_from=2023-01&b_to=2023-12",  # unknown parameter
        "parameter=%27%3B%20DROP%20TABLE%20measurements%3B%20--&a_from=2021-01&a_to=2021-12&b_from=2023-01&b_to=2023-12",
        f"parameter={'x' * 65}&a_from=2021-01&a_to=2021-12&b_from=2023-01&b_to=2023-12",  # over-long parameter
        "a_from=2021-01&a_to=2021-12&b_from=2023-01&b_to=2023-12",  # parameter missing
        "parameter=Nitrate&a_from=2021-01&a_to=2021-12&b_from=2023-01",  # b_to missing
        f"parameter=Nitrate&{PERIODS}&language=klingon",  # unknown language
    ],
)
def test_invalid_input_is_a_422(http, built, query):
    response = http.get(f"/sites/{S1}/change?{query}")
    assert response.status_code == 422, response.text
    assert "detail" in response.json()
    assert store.list_sites()[0] > 0  # nothing was damaged


def test_an_unknown_site_is_a_404_and_an_injection_in_the_id_is_inert(http, built):
    assert change(http, "NOPE-1", "Nitrate").status_code == 404
    assert change(http, "x'%20OR%20'1'='1", "Nitrate").status_code == 404
    assert change(http, "x%27%3B%20DROP%20TABLE%20sites%3B%20--", "Nitrate").status_code == 404
    assert store.list_sites()[0] > 0


def test_a_sandbox_only_parameter_is_unknown_for_a_waterbase_site_and_the_reverse(http, built):
    assert change(http, S1, "Conductivity").status_code == 422  # a closed name the Waterbase mapping does not hold
    assert change(http, "Loc-Almyros", "Turbidity").status_code == 422  # a Waterbase label, not a sandbox parameter


def test_an_old_store_is_not_served_and_says_so(http, tmp_path: Path, monkeypatch):
    path = tmp_path / "old.sqlite"
    connection = sqlite3.connect(path)
    connection.executescript(DDL)
    connection.execute("INSERT INTO provenance VALUES ('schema_version', '2')")
    connection.execute("INSERT INTO sites VALUES ('S1','IT','RW','x',NULL,NULL,1.0,1.0,'F',2015,2015,1)")
    connection.commit()
    connection.close()
    monkeypatch.setenv("OAH_WATERBASE_STORE", str(path))
    assert store.store_status().state == "rebuild-required" and store.countries_summary() == []
    assert store.site_series("S1") == (0, []) and store.scope_monthly_rows(NITRATE[0], "W", [(0, 10**6)], site_id="S1") == ([], None, False)
    assert http.get("/sites").json()["waterbase"]["state"] == "rebuild-required"
    assert change(http, "S1", "Nitrate").status_code == 404
    body = http.get("/countries/IT/change?parameter=Nitrate&" + PERIODS).json()
    assert body["waterbase"]["state"] == "rebuild-required" and [r["source"] for r in body["results"]] == ["real-sandbox"]


# --- localisation ---------------------------------------------------------------------------------------------------------


def test_the_notices_are_the_fixed_strings_in_the_requested_language(http, built):
    english = change(http, S1, "Nitrate").json()
    assert english["approximation_notice"] == ENGLISH["approximation_notice"] and english["interpretation_notice"] == ENGLISH["interpretation_notice"]
    assert "LIMeco" in english["approximation_notice"] and "not a compliance assessment" in english["approximation_notice"]
    spanish = change(http, S1, "Nitrate", extra="&language=es").json()
    strings = load_strings("es-MX")
    assert spanish["language"] == "es-MX" and spanish["approximation_notice"] == strings.get("approximation_notice")
    assert spanish["interpretation_notice"] == strings.get("interpretation_notice") and spanish["approximation_notice"] != english["approximation_notice"]
    country = http.get(f"/countries/IT/change?parameter=Nitrate&{PERIODS}&language=it").json()
    assert country["language"] == "it" and country["approximation_notice"] == load_strings("it").get("approximation_notice")


# --- GET /countries/{code}/change ---------------------------------------------------------------------------------------


def country_change(http: TestClient, code: str, parameter: str, periods: str = PERIODS, extra: str = "") -> Any:
    return http.get(f"/countries/{code}/change?parameter={parameter}&{periods}{extra}")


def test_a_country_uses_paired_sites_only_and_keeps_the_sources_apart(http, built):
    body = country_change(http, "IT", "Nitrate", extra="&source=real-eea-waterbase").json()
    assert body["origin"] == "real-eea-waterbase" and body["scope"] == {"type": "country", "code": "IT"}
    assert body["waterbase"]["state"] == "ready" and body["approximation_notice"] == ENGLISH["approximation_notice"]
    [result] = body["results"]
    assert (result["source"], result["unit"], result["resolution"], result["status"]) == ("real-eea-waterbase", "mg/L", "monthly", "ok")
    assert (result["n_sites_considered"], result["n_sites_paired"], result["n_sites_excluded"]) == (4, 3, 1)  # S1, S2 and the lake; S3 has no data in 2023
    assert result["exclusion_reasons"] == {"absent-in-period-b": 1} and "few-sites" in result["flags"]
    a, b = result["periods"]["a"], result["periods"]["b"]
    assert (a["n_sites"], b["n_sites"]) == (3, 3) and (a["n_samples"], b["n_samples"]) == (9, 9)  # S3's 99.0 is in neither period
    assert a["mean_of_site_means"] == pytest.approx((20.0 + 5.0 + 4.0) / 3, abs=1e-6)
    assert b["mean_of_site_means"] == pytest.approx((40.0 + 7.0 + 6.0) / 3, abs=1e-6)
    assert (a["river_sites_judged"], a["river_sites_over_limit"]) == (2, 1) and (b["river_sites_judged"], b["river_sites_over_limit"]) == (2, 2)
    assert result["river_limit"]["a"]["limit"] == round(1.2 * NO3_PER_N, 6) and result["river_limit"]["a"]["limit_regime"] == "surface"
    assert (result["sites_increased"], result["sites_decreased"], result["sites_unchanged"]) == (3, 0, 0)
    assert result["median_site_relative_change_percent"] == 50.0  # +100, +40 and +50 percent: the middle one
    assert result["data_range"] == {"first": "2021-01", "last": "2024-12"}


def test_both_sources_answer_separately_for_a_country_that_has_both(http, built):
    body = country_change(http, "IT", "Nitrate", "a_from=2018-01&a_to=2018-12&b_from=2019-01&b_to=2019-12").json()
    assert body["origin"] == "real-mixed" and [r["source"] for r in body["results"]] == ["real-eea-waterbase", "real-sandbox"]
    waterbase, sandbox = body["results"]
    assert waterbase["status"] == "insufficient-data" and waterbase["origin"] == "real-eea-waterbase"  # no Waterbase data in 2018-2019
    assert sandbox["resolution"] == "annual-only" and sandbox["status"] == "ok" and sandbox["periods"]["a"]["n_unit"] == "aggregate-records"
    assert sandbox["periods"]["a"]["mean_of_site_means"] == 2.0 and sandbox["periods"]["b"]["mean_of_site_means"] == 2.5
    assert "annual-only" in sandbox["flags"] and "few-sites" in sandbox["flags"]
    only = country_change(http, "IT", "Nitrate", "a_from=2018-01&a_to=2018-12&b_from=2019-01&b_to=2019-12", "&source=real-sandbox").json()
    assert only["origin"] == "real-sandbox" and [r["source"] for r in only["results"]] == ["real-sandbox"]


def test_el_is_read_as_gr_and_a_country_with_no_data_in_the_periods_says_so(http, built):
    greek = country_change(http, "EL", "Nitrate", extra="&source=real-eea-waterbase").json()
    assert greek["scope"]["code"] == "GR" and greek["results"][0]["n_sites_considered"] == 0 and greek["results"][0]["status"] == "insufficient-data"
    assert greek["results"][0]["data_range"] == {"first": None, "last": None}  # the Greek site holds no nitrate at all: no range, not a guess


def test_a_parameter_no_source_holds_for_the_country_is_reported_not_invented(http, built):
    body = country_change(http, "NO", "Total%20phosphates", extra="&source=real-sandbox").json()
    assert body["results"] == [] and body["note"] and body["origin"] == "real-sandbox"


def test_country_errors(http, built):
    assert country_change(http, "ZZ", "Nitrate").status_code == 404
    assert country_change(http, "ZZ", "Nitrate", extra="&source=real-eea-waterbase").status_code == 404
    assert http.get("/countries/ITA/change?parameter=Nitrate&" + PERIODS).status_code == 422
    assert http.get("/countries/1T/change?parameter=Nitrate&" + PERIODS).status_code == 422
    assert country_change(http, "IT", "Unobtainium").status_code == 422
    assert country_change(http, "IT", "Nitrate", "a_from=2021-12&a_to=2021-01&b_from=2023-01&b_to=2023-12").status_code == 422
    assert country_change(http, "IT", "Nitrate", extra="&source=nowhere").status_code == 422
    assert country_change(http, "IT", "Turbidity", extra="&source=real-sandbox").status_code == 422  # unknown to the consulted source
    assert country_change(http, "IT", "Nitrate", extra="&language=zz").status_code == 422


def test_a_measurement_only_group_works_for_a_country_and_has_no_limit(http, built):
    [result] = country_change(http, "IT", "Turbidity", extra="&source=real-eea-waterbase").json()["results"]
    assert result["group"] == "solids-turbidity" and result["n_sites_paired"] == 1 and result["river_limit"]["a"]["limit"] is None
    assert result["periods"]["a"]["river_sites_judged"] == 0 and result["river_limit"]["a"]["limit_regime"] == "no-limit-regime"
    assert result["change_of_site_means"]["absolute"] == 6.0


# --- the sandbox: annual aggregates, never pretended monthly ---------------------------------------------------------------


def test_a_sandbox_site_is_compared_on_its_annual_aggregates_and_flagged(http, built):
    body = change(http, "Loc-Almyros", "Nitrate", "a_from=2018-01&a_to=2018-12&b_from=2019-01&b_to=2019-12").json()
    assert body["origin"] == body["source"] == "real-sandbox" and body["resolution"] == "annual-only" and body["attribution"] is None
    assert "annual-only" in body["flags"] and body["record_notes"]["statistics_used"] == ["median"]
    a, b = body["periods"]["a"], body["periods"]["b"]
    assert (a["n_samples"], a["n_unit"], a["mean"], b["mean"]) == (1, "aggregate-records", 3.0, 4.0) and a["n_months_with_data"] == 12
    assert body["change"] == {"absolute": 1.0, "relative_percent": 33.3333, "relative_percent_note": None, "direction": "increased"}
    assert body["min_samples_per_period"] == 1 and body["status"] == "ok"
    greek_limit = round(0.60 * NO3_PER_N, 6)
    assert a["assessment"]["limit"] == greek_limit and a["assessment"]["status"] == "exceeds-limit" and body["crossed_limit"] == "none"
    assert body["scope"]["country"] == "GR" and body["scope"]["regime"] == "surface" and body["data_range"] == {"first": "2018-01", "last": "2021-12"}


def test_a_sandbox_record_that_crosses_the_period_edge_is_left_out_and_a_censored_one_is_below_loq(http, built):
    crossing = change(http, "Loc-Almyros", "Nitrate", "a_from=2018-06&a_to=2019-05&b_from=2019-01&b_to=2019-12").json()
    assert crossing["periods"]["a"]["n_samples"] == 0 and crossing["periods"]["a"]["n_records_excluded_crossing_period_edge"] == 2
    assert "records-crossing-period-edge-excluded" in crossing["flags"] and crossing["status"] == "insufficient-data"
    censored = change(http, "Loc-Almyros", "Nitrate", "a_from=2020-01&a_to=2020-12&b_from=2021-01&b_to=2021-12").json()
    assert censored["periods"]["b"]["n_samples"] == 0 and censored["periods"]["b"]["n_below_loq"] == 1 and censored["periods"]["b"]["mean"] is None
    assert censored["periods"]["b"]["below_loq_share"] == 1.0 and "below-loq-excluded-bias-upward" in censored["periods"]["b"]["flags"]
    assert censored["change"]["direction"] is None and censored["periods"]["b"]["assessment"]["status"] == "indeterminate"


def test_a_sandbox_period_beyond_the_data_is_reported(http, built):
    body = change(http, "Loc-Almyros", "Nitrate", "a_from=2018-01&a_to=2018-12&b_from=2026-05&b_to=2026-05").json()
    assert "period-outside-data" in body["periods"]["b"]["flags"] and body["data_range"]["last"] == "2021-12"
    assert body["periods"]["b"]["n_samples"] == 0 and body["status"] == "insufficient-data"


def test_the_sandbox_site_errors(http, built):
    assert change(http, "Loc-Nowhere", "Nitrate").status_code == 404
    assert change(http, "Loc-Almyros", "Nitrate", "a_from=2018-12&a_to=2018-01&b_from=2019-01&b_to=2019-12").status_code == 422


# --- measurement records at monthly resolution -------------------------------------------------------------------------------


def test_monthly_resolution_returns_one_record_per_month_with_the_month(http, built):
    body = http.get(f"/sites/{S1}/measurements?parameter=Nitrate&resolution=monthly").json()
    assert body["resolution"] == "monthly" and body["origin"] == "real-eea-waterbase"
    first = body["records"][0]
    assert (first["year"], first["month"], first["n"], first["value"], first["min"], first["max"]) == (2021, 5, 2, 15.0, 10.0, 20.0)
    assert (first["period_start"], first["period_end"]) == ("2021-05-01", "2021-05-31") and first["statistic"] == "mean"
    assert first["observation_id"].endswith("|2021-05|mg{NO3}/L")
    assert [(r["year"], r["month"]) for r in body["records"]] == [(2021, 5), (2021, 6), (2023, 2), (2023, 6), (2023, 10), (2024, 12)]
    assert first["limit"] == pytest.approx(1.2 * NO3_PER_N, abs=1e-6) and first["status"] == "exceeds-limit"  # judged as before


def test_the_annual_view_is_still_the_default_and_has_no_month(http, built):
    body = http.get(f"/sites/{S1}/measurements?parameter=Nitrate").json()
    assert body["resolution"] == "annual" and [r["year"] for r in body["records"]] == [2021, 2023, 2024]
    assert all(r["month"] is None for r in body["records"]) and body["records"][0]["value"] == 20.0 and body["records"][0]["n"] == 3
    explicit = http.get(f"/sites/{S1}/measurements?parameter=Nitrate&resolution=annual").json()
    assert explicit["records"] == body["records"]


def test_monthly_responses_are_bounded_by_the_limit_and_the_window(http, built):
    body = http.get(f"/sites/{S1}/measurements?parameter=Nitrate&resolution=monthly&limit=2").json()
    assert body["returned"] == 2 and body["truncated"] is True and body["total_matching"] == 6
    windowed = http.get(f"/sites/{S1}/measurements?parameter=Nitrate&resolution=monthly&date_from=2023-01-01&date_to=2023-12-31").json()
    assert [r["month"] for r in windowed["records"]] == [2, 6, 10]
    assert http.get(f"/sites/{S1}/measurements?resolution=monthly&limit=501").status_code == 422
    assert http.get(f"/sites/{S1}/measurements?resolution=weekly").status_code == 422


def test_a_sandbox_site_has_no_monthly_resolution(http, built):
    response = http.get("/sites/Loc-Almyros/measurements?resolution=monthly")
    assert response.status_code == 422 and "period summaries" in response.json()["detail"]
    body = http.get("/sites/Loc-Almyros/measurements").json()
    assert body["resolution"] == "period-summary" and body["origin"] == "real-sandbox"
