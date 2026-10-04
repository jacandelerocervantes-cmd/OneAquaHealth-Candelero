"""Bathing-water SAMPLES in the API: the samples route, the period comparison (one bathing water, one country), the history
link and the /countries blocks. SYNTHETIC stores (``samples_fixtures``, ``bathing_fixtures``); every expected number is
computed by hand in the test and the data is not real. No test opens a network connection.
"""

from __future__ import annotations

import json
import socket
from pathlib import Path
from typing import Any

import pytest
from bathing_fixtures import HEADER, row
from bathing_fixtures import build_fixture_store as build_classification_store
from fastapi.testclient import TestClient
from samples_fixtures import build_fixture_store as build_samples_store

import oah.api.app as app_module
import oah.api.deps as deps_module
from oah.api.rate_limit import RateLimiter
from oah.i18n.strings import load_strings

ORIGIN = "real-eea-bathing-samples"


@pytest.fixture(autouse=True)
def _world(monkeypatch):
    monkeypatch.setattr(deps_module, "get_rate_limiter", lambda: RateLimiter(10_000, 60.0))
    monkeypatch.setattr(deps_module, "get_cached_observations", lambda: [])
    monkeypatch.setattr(deps_module, "get_cached_locations", lambda: [])

    def refuse(*_a: Any, **_k: Any):
        raise AssertionError("a bathing-water request must not open a network connection")

    monkeypatch.setattr(socket, "create_connection", refuse)


@pytest.fixture()
def http() -> TestClient:
    return TestClient(app_module.app)


@pytest.fixture()
def samples_only(tmp_path: Path, monkeypatch) -> Path:
    path = build_samples_store(tmp_path)
    monkeypatch.setenv("OAH_BATHING_SAMPLES_STORE", str(path))
    monkeypatch.setenv("OAH_BATHING_WATER_STORE", str(tmp_path / "no-classification.sqlite"))
    return path


@pytest.fixture()
def both(tmp_path: Path, monkeypatch) -> Path:
    classes = build_classification_store(
        tmp_path,
        rows=[
            HEADER,
            row("IT", "ITSYN001", 2022, "1 - Excellent", name="SYNTHETIC SAMPLE BEACH"),
            row("IT", "ITSYN009", 2022, "2 - Good", name="SYNTHETIC BEACH WITHOUT SAMPLES"),
            row("EL", "ELSYN001", 2023, "1 - Excellent", name="SYNTHETIC GREEK BEACH"),
        ],
    )
    path = build_samples_store(tmp_path)
    monkeypatch.setenv("OAH_BATHING_WATER_STORE", str(classes))
    monkeypatch.setenv("OAH_BATHING_SAMPLES_STORE", str(path))
    return path


def _get(http: TestClient, path: str) -> dict[str, Any]:
    response = http.get(path)
    assert response.status_code == 200, response.text
    body: dict[str, Any] = response.json()
    return body


# --- GET /bathing-waters/{id}/samples -------------------------------------------------------------------------------------


def test_the_samples_are_labelled_a_measurement_with_notices_unit_and_attribution(http, both):
    body = _get(http, "/bathing-waters/ITSYN001/samples")
    assert body["origin"] == ORIGIN and body["language"] == "en"
    assert body["attribution"].endswith("(EEA CC BY 4.0)") and body["unit"] == "cfu/100ml" and "table metadata" in body["unit_statement"]
    assert "individual sample results" in body["notice"] and "not a classification" in body["notice"]
    assert "No threshold or limit is applied" in body["no_threshold_notice"] and "below the limit of detection" in body["flagged_values_note"]
    assert body["bathing_samples"]["state"] == "ready" and body["data_freshness"] == {
        "status": "snapshot", "as_of": "2026-10-03T00:00:00Z", "age_seconds": None,
    }
    assert body["bathing_water"] == {"id": "ITSYN001", "country": "IT", "name": "SYNTHETIC SAMPLE BEACH", "type": "coastalBathingWater"}
    assert body["data_range"] == {"first_sample_date": "2020-05-10", "last_sample_date": "2022-08-25", "first_season": 2020, "last_season": 2022}
    assert (body["total_matching"], body["returned"], body["limit"], body["truncated"]) == (11, 11, 200, False)
    assert body["filters"] == {"date_from": None, "date_to": None, "season": None, "order": "asc"}
    text = json.dumps(body)
    for forbidden in ("limit_basis", "crossed_limit", "exceeds", "within-limit", "compliant\":", "threshold_value"):
        assert forbidden not in text


def test_the_summary_covers_all_matching_samples_with_exact_statistics(http, both):
    summary = _get(http, "/bathing-waters/ITSYN001/samples")["summary"]
    assert summary["escherichia_coli"] == {
        "n_samples_in_range": 11, "n_quantified": 9, "n_confirmed_high": 1, "n_detection_limit": 1, "n_missing": 1, "n_unrecognised": 0,
        "min": 7, "max": 900, "mean": round(1607 / 9, 6), "median": 40.0,
    }
    assert summary["intestinal_enterococci"] == {
        "n_samples_in_range": 11, "n_quantified": 10, "n_confirmed_high": 0, "n_detection_limit": 0, "n_missing": 1, "n_unrecognised": 0,
        "min": 1, "max": 9, "mean": 5.2, "median": 5.5,  # 1 2 3 4 5 6 7 7 8 9
    }
    # a page of two samples still summarises all eleven
    page = _get(http, "/bathing-waters/ITSYN001/samples?limit=2")
    assert page["returned"] == 2 and page["total_matching"] == 11 and page["truncated"] is True and "truncated" in page["flags"]
    assert page["summary"]["escherichia_coli"]["n_samples_in_range"] == 11


def test_a_flagged_value_is_never_shown_as_a_plain_number(http, both):
    samples = {s["sample_date"]: s for s in _get(http, "/bathing-waters/ITSYN001/samples?date_from=2022-08-01&date_to=2022-08-31")["samples"]}
    assert set(samples) == {"2022-08-10", "2022-08-20", "2022-08-25"}
    below = samples["2022-08-10"]["escherichia_coli"]
    assert below == {"value": None, "reported_value": 1, "status": "limitOfDetectionValue", "kind": "detection-limit"}
    missing = samples["2022-08-20"]
    assert missing["escherichia_coli"] == {"value": None, "reported_value": None, "status": "missingValue", "kind": "missing"}  # the placeholder 0 is not shown
    assert missing["intestinal_enterococci"]["value"] is None and missing["sample_status"] == "missingSample"
    confirmed = samples["2022-08-25"]
    assert confirmed["escherichia_coli"] == {"value": 900, "reported_value": 900, "status": "confirmedValue", "kind": "confirmed-high"}
    assert confirmed["has_remarks"] is True and confirmed["sample_status"] == "confirmationSample" and confirmed["observation_status"] == "A"
    assert samples["2022-08-10"]["intestinal_enterococci"] == {"value": 8, "reported_value": 8, "status": None, "kind": "quantified"}


def test_unrecognised_and_invalid_values_are_labelled_too(http, samples_only):
    greek = {s["sample_date"]: s for s in _get(http, "/bathing-waters/ELSYN002/samples")["samples"]}
    assert greek["2023-07-15"]["escherichia_coli"] == {"value": None, "reported_value": None, "status": None, "kind": "invalid"}
    assert greek["2023-07-15"]["intestinal_enterococci"] == {"value": None, "reported_value": 5, "status": "weirdStatus", "kind": "unknown-status"}
    assert greek["2023-06-15"]["intestinal_enterococci"]["kind"] == "missing"
    flags = _get(http, "/bathing-waters/ELSYN002/samples")["flags"]
    assert "unrecognised-status-values-excluded" in flags and "missing-values-excluded" in flags


def test_filters_order_and_limit(http, both):
    body = _get(http, "/bathing-waters/ITSYN001/samples?date_from=2022-06-01&date_to=2022-08-10&order=desc")
    assert [s["sample_date"] for s in body["samples"]] == ["2022-08-10", "2022-07-10", "2022-06-10"] and body["filters"]["order"] == "desc"
    assert body["filters"]["date_from"] == "2022-06-01" and body["filters"]["date_to"] == "2022-08-10"
    assert _get(http, "/bathing-waters/ITSYN001/samples?season=2021")["total_matching"] == 1
    assert _get(http, "/bathing-waters/ITSYN001/samples?limit=500")["limit"] == 500
    assert _get(http, "/bathing-waters/ITSYN001/samples?date_from=2023-01-01")["flags"] == ["no-samples-in-range", "range-outside-data"]
    assert _get(http, "/bathing-waters/ITSYN001/samples?date_to=2019-12-31")["flags"] == ["no-samples-in-range", "range-outside-data"]
    inside = _get(http, "/bathing-waters/ITSYN001/samples?date_from=2020-09-01&date_to=2020-12-31")
    assert inside["total_matching"] == 0 and inside["flags"] == ["no-samples-in-range"] and inside["summary"]["escherichia_coli"]["median"] is None


@pytest.mark.parametrize(
    "query",
    ["date_from=2022-13-01", "date_from=yesterday", "date_from=2022-06-01&date_to=2022-01-01", "season=1800", "season=2101", "season=abc",
     "limit=0", "limit=501", "limit=ten", "order=sideways", "language=xx-unknown", "language=x"],
)
def test_bad_parameters_are_a_422(http, both, query):
    assert http.get(f"/bathing-waters/ITSYN001/samples?{query}").status_code == 422


def test_an_unknown_or_hostile_identifier_is_a_404_and_nothing_is_executed(http, both):
    for bw_id in ("NOPE", "x" * 300, "%27%3B%20DROP%20TABLE%20samples%3B%20--", "ITSYN001%25"):
        assert http.get(f"/bathing-waters/{bw_id}/samples").status_code == 404, bw_id
    assert _get(http, "/bathing-waters/ITSYN001/samples")["total_matching"] == 11


def test_el_identifiers_are_greek_and_stored_as_gr(http, both):
    body = _get(http, "/bathing-waters/ELSYN001/samples")
    assert body["bathing_water"]["country"] == "GR" and body["bathing_water"]["name"] == "SYNTHETIC GREEK BEACH" and body["total_matching"] == 4
    assert body["samples"][0]["sample_status"] == "preSeasonSample"
    assert body["summary"]["escherichia_coli"]["n_detection_limit"] == 1 and body["summary"]["escherichia_coli"]["n_quantified"] == 3


def test_a_bathing_water_with_no_samples_is_a_200_with_a_flag(http, both):
    body = _get(http, "/bathing-waters/ITSYN009/samples")
    assert body["bathing_water"]["name"] == "SYNTHETIC BEACH WITHOUT SAMPLES" and body["total_matching"] == 0 and body["samples"] == []
    assert body["data_range"] is None and body["flags"] == ["no-samples-for-bathing-water"]


def test_a_sampled_bathing_water_missing_from_the_classification_is_still_served(http, samples_only):
    body = _get(http, "/bathing-waters/ITSYN001/samples")
    assert body["bathing_water"] == {"id": "ITSYN001", "country": "IT", "name": "ITSYN001", "type": None} and body["total_matching"] == 11


def test_without_a_store_the_state_is_said_and_the_404_names_it(http, tmp_path: Path, monkeypatch):
    monkeypatch.setenv("OAH_BATHING_SAMPLES_STORE", str(tmp_path / "absent.sqlite"))
    classes = build_classification_store(tmp_path, rows=[HEADER, row("IT", "ITSYN001", 2022, "1 - Excellent")])
    monkeypatch.setenv("OAH_BATHING_WATER_STORE", str(classes))
    body = _get(http, "/bathing-waters/ITSYN001/samples")
    assert body["bathing_samples"]["state"] == "not-built" and "build_bathing_samples_store.py" in body["bathing_samples"]["detail"]
    assert body["samples"] == [] and body["flags"] == ["store-not-ready"] and body["origin"] == ORIGIN
    missing = http.get("/bathing-waters/UNKNOWN1/samples")
    assert missing.status_code == 404 and "not-built" in missing.json()["detail"]


def test_a_corrupt_store_is_reported_not_raised(http, tmp_path: Path, monkeypatch):
    broken = tmp_path / "broken.sqlite"
    broken.write_bytes(b"garbage" * 100)
    monkeypatch.setenv("OAH_BATHING_SAMPLES_STORE", str(broken))
    monkeypatch.setenv("OAH_BATHING_WATER_STORE", str(build_classification_store(tmp_path, rows=[HEADER, row("IT", "ITSYN001", 2022, "1 - Excellent")])))
    assert _get(http, "/bathing-waters/ITSYN001/samples")["bathing_samples"]["state"] == "unreadable"
    assert _get(http, "/countries")["bathing_samples"]["state"] == "unreadable"


def test_the_notices_follow_the_requested_language(http, both):
    italian = _get(http, "/bathing-waters/ITSYN001/samples?language=it")
    strings = load_strings("it")
    assert italian["language"] == "it" and italian["notice"] == strings.get("bathing_samples_notice")
    assert italian["no_threshold_notice"] == strings.get("bathing_no_threshold_notice") and italian["flagged_values_note"] == strings.get("bathing_flagged_values_note")
    assert italian["notice"] != _get(http, "/bathing-waters/ITSYN001/samples")["notice"]
    assert _get(http, "/bathing-waters/ITSYN001/samples?language=es")["language"] == "es-MX"
    assert _get(http, "/bathing-waters/ITSYN001/samples?language=EL")["language"] == "el"  # the language Greek, not the country code


def test_the_routes_are_protected_like_the_others(http, both, monkeypatch):
    monkeypatch.setenv("OAH_API_KEY", "secret")
    monkeypatch.delenv("OAH_INSECURE_NO_AUTH", raising=False)
    for path in ("/bathing-waters/ITSYN001/samples", "/bathing-waters/ITSYN001/samples/change?a_from=2020-05&a_to=2020-08&b_from=2022-05&b_to=2022-08",
                 "/bathing-waters/samples/change?country=IT&a_from=2020-05&a_to=2020-08&b_from=2022-05&b_to=2022-08"):
        assert http.get(path).status_code == 401
    assert http.get("/bathing-waters/ITSYN001/samples", headers={"X-API-Key": "secret"}).status_code == 200


# --- the history link and /countries ----------------------------------------------------------------------------------------


def test_the_history_says_whether_samples_exist_and_the_last_sample_date(http, both):
    link = _get(http, "/bathing-waters/ITSYN001")["samples"]
    assert link == {
        "state": "ready", "available": True, "n_samples": 11, "first_sample_date": "2020-05-10", "last_sample_date": "2022-08-25",
        "first_season": 2020, "last_season": 2022, "path": "/bathing-waters/ITSYN001/samples",
    }
    none = _get(http, "/bathing-waters/ITSYN009")["samples"]
    assert none["available"] is False and none["n_samples"] == 0 and none["last_sample_date"] is None and none["path"] is None and none["state"] == "ready"


def test_the_history_link_without_a_samples_store(http, tmp_path: Path, monkeypatch):
    monkeypatch.setenv("OAH_BATHING_SAMPLES_STORE", str(tmp_path / "absent.sqlite"))
    monkeypatch.setenv("OAH_BATHING_WATER_STORE", str(build_classification_store(tmp_path, rows=[HEADER, row("IT", "ITSYN001", 2022, "1 - Excellent")])))
    link = _get(http, "/bathing-waters/ITSYN001")["samples"]
    assert link["state"] == "not-built" and link["available"] is False and link["path"] is None


def test_countries_gain_the_samples_range_and_counts(http, both):
    body = _get(http, "/countries")
    assert body["bathing_samples"]["state"] == "ready" and body["bathing_samples"]["attribution"].endswith("(EEA CC BY 4.0)")
    blocks = {c["code"]: c["bathing_water"] for c in body["countries"] if c["bathing_water"]}
    italy = blocks["IT"]["samples"]
    assert italy == {
        "origin": ORIGIN, "bathing_waters_with_samples": 4, "n_samples": 27, "n_quantified": {"escherichia_coli": 25, "intestinal_enterococci": 26},
        "first_sample_date": "2020-05-10", "last_sample_date": "2022-08-25", "first_season": 2020, "last_season": 2022, "unit": "cfu/100ml",
        "attribution": italy["attribution"], "content": "individual-samples-no-thresholds",
    }
    greece = blocks["GR"]["samples"]
    assert greece["n_samples"] == 6 and greece["bathing_waters_with_samples"] == 2 and greece["first_season"] == greece["last_season"] == 2023
    assert blocks["IT"]["content"] == "classification-only"  # the classification block is unchanged
    assert "NO" not in blocks  # Norway has no row in either dataset


def test_countries_without_a_samples_store_have_a_null_samples_block(http, tmp_path: Path, monkeypatch):
    monkeypatch.setenv("OAH_BATHING_SAMPLES_STORE", str(tmp_path / "absent.sqlite"))
    monkeypatch.setenv("OAH_BATHING_WATER_STORE", str(build_classification_store(tmp_path, rows=[HEADER, row("IT", "ITSYN001", 2022, "1 - Excellent")])))
    body = _get(http, "/countries")
    assert body["bathing_samples"]["state"] == "not-built"
    assert [c["bathing_water"]["samples"] for c in body["countries"] if c["bathing_water"]] == [None]


# --- GET /bathing-waters/{id}/samples/change --------------------------------------------------------------------------------

PERIODS = "a_from=2020-05&a_to=2020-08&b_from=2022-05&b_to=2022-08"


def test_one_bathing_water_change_is_exact_for_both_indicators(http, both):
    body = _get(http, f"/bathing-waters/ITSYN001/samples/change?{PERIODS}")
    assert body["origin"] == ORIGIN and body["scope"] == {"type": "bathing-water", "id": "ITSYN001", "code": None, "name": "SYNTHETIC SAMPLE BEACH", "country": "IT"}
    assert "No significance is tested" in body["change_notice"] and body["unit"] == "cfu/100ml"
    coli = body["indicators"]["escherichia_coli"]
    assert coli["status"] == "ok" and coli["min_samples_per_period"] == 3 and coli["unit"] == "cfu/100ml"
    a, b = coli["periods"]["a"], coli["periods"]["b"]
    assert (a["n_samples"], a["mean"], a["median"], a["min"], a["max"]) == (4, 25.0, 25.0, 10.0, 40.0)
    assert (b["n_samples"], b["mean"], b["median"], b["min"], b["max"]) == (4, 375.0, 250.0, 100.0, 900.0)  # 100 200 300 and the confirmed 900
    assert (b["n_detection_limit"], b["n_missing"], b["n_confirmed_high"], b["n_unrecognised"]) == (1, 1, 1, 0)
    assert (a["n_detection_limit"], a["n_missing"]) == (0, 0) and a["flags"] == [] and a["meets_minimum_samples"] is True
    assert b["flags"] == ["confirmed-high-values-included", "detection-limit-values-excluded", "missing-values-excluded"]
    assert coli["change"] == {"absolute": 350.0, "relative_percent": 1400.0, "relative_percent_note": None, "direction": "increased"}
    assert coli["change_of_median"] == {"absolute": 225.0, "relative_percent": 900.0, "relative_percent_note": None, "direction": "increased"}
    assert coli["data_range"] == {"first": "2020-05", "last": "2022-08"}
    enterococci = body["indicators"]["intestinal_enterococci"]
    assert (enterococci["periods"]["a"]["mean"], enterococci["periods"]["a"]["median"]) == (2.5, 2.5)
    assert (enterococci["periods"]["b"]["n_samples"], enterococci["periods"]["b"]["mean"], enterococci["periods"]["b"]["median"]) == (5, 7.0, 7.0)
    assert enterococci["change"]["absolute"] == 4.5 and enterococci["change"]["relative_percent"] == 180.0
    assert enterococci["periods"]["b"]["n_missing"] == 1 and enterococci["periods"]["b"]["n_detection_limit"] == 0


def test_no_limit_no_crossing_and_no_significance_anywhere_in_a_comparison(http, both):
    text = json.dumps(_get(http, f"/bathing-waters/ITSYN001/samples/change?{PERIODS}"))
    for forbidden in ("crossed_limit", "limit_basis", "limit_regime", "\"assessment\"", "within-limit", "exceeds-limit", "p_value", "significan\":", "below-loq"):
        assert forbidden not in text
    assert "no limit crossing" in text.lower() or "no limit crossing is reported" in text


def test_a_period_beyond_the_data_is_reported_with_the_data_range_and_never_shifted(http, both):
    body = _get(http, "/bathing-waters/ITSYN001/samples/change?a_from=2021-05&a_to=2021-05&b_from=2026-05&b_to=2026-05")
    coli = body["indicators"]["escherichia_coli"]
    a, b = coli["periods"]["a"], coli["periods"]["b"]
    assert (b["start"], b["end"]) == ("2026-05", "2026-05") and b["n_samples"] == 0 and b["mean"] is None and b["median"] is None
    assert "period-outside-data" in b["flags"] and "period-outside-data" not in a["flags"]
    assert (a["n_samples"], a["mean"], a["median"]) == (1, 7.0, 7.0) and a["meets_minimum_samples"] is False
    assert coli["status"] == "insufficient-data" and coli["data_range"] == {"first": "2020-05", "last": "2022-08"}
    assert coli["change"]["absolute"] is None and coli["change"]["relative_percent_note"] == "comparison-missing"
    assert "period-outside-data" in coli["flags"] and "relative-change-undefined" in coli["flags"]


def test_a_period_with_months_outside_the_sampling_season_is_flagged_partial(http, both):
    body = _get(http, "/bathing-waters/ITSYN001/samples/change?a_from=2020-01&a_to=2020-12&b_from=2022-01&b_to=2022-12")
    coli = body["indicators"]["escherichia_coli"]
    assert coli["periods"]["a"]["months_in_period"] == 12 and coli["periods"]["a"]["n_months_with_data"] == 4
    assert "partial-period" in coli["periods"]["a"]["flags"] and coli["periods"]["a"]["n_samples"] == 4


def test_too_few_samples_is_insufficient_data_but_the_numbers_are_still_given(http, both):
    body = _get(http, "/bathing-waters/ITSYN003/samples/change?a_from=2020-05&a_to=2020-08&b_from=2022-05&b_to=2022-08")
    coli = body["indicators"]["escherichia_coli"]
    assert coli["status"] == "insufficient-data" and coli["periods"]["b"]["n_samples"] == 2 and coli["periods"]["b"]["mean"] == 12.0
    assert coli["periods"]["b"]["meets_minimum_samples"] is False and coli["change"]["direction"] == "increased"  # given, with the status saying why it is weak


def test_overlapping_periods_are_flagged(http, both):
    body = _get(http, "/bathing-waters/ITSYN001/samples/change?a_from=2020-05&a_to=2022-08&b_from=2022-05&b_to=2022-08")
    assert "periods-overlap" in body["indicators"]["escherichia_coli"]["flags"]


@pytest.mark.parametrize(
    "query",
    ["a_from=2020-5&a_to=2020-08&b_from=2022-05&b_to=2022-08", "a_from=2020-08&a_to=2020-05&b_from=2022-05&b_to=2022-08",
     "a_from=2020-05&a_to=2020-08&b_from=2022-13&b_to=2022-08", "a_from=1800-01&a_to=2020-08&b_from=2022-05&b_to=2022-08",
     "a_from=1900-01&a_to=2100-12&b_from=2022-05&b_to=2022-08", "a_from=2020-05&a_to=2020-08&b_from=2022-05",
     "a_from=2020-05&a_to=2020-08&b_from=2022-05&b_to=2022-08&language=nope"],
)
def test_bad_periods_are_a_422(http, both, query):
    assert http.get(f"/bathing-waters/ITSYN001/samples/change?{query}").status_code == 422


def test_an_unknown_bathing_water_in_a_comparison_is_a_404(http, both):
    assert http.get(f"/bathing-waters/NOPE/samples/change?{PERIODS}").status_code == 404
    assert http.get(f"/bathing-waters/ITSYN009/samples/change?{PERIODS}").status_code == 200  # known, no samples: all periods empty


def test_a_comparison_without_a_store_answers_with_the_state(http, tmp_path: Path, monkeypatch):
    monkeypatch.setenv("OAH_BATHING_SAMPLES_STORE", str(tmp_path / "absent.sqlite"))
    monkeypatch.setenv("OAH_BATHING_WATER_STORE", str(build_classification_store(tmp_path, rows=[HEADER, row("IT", "ITSYN001", 2022, "1 - Excellent")])))
    body = _get(http, f"/bathing-waters/ITSYN001/samples/change?{PERIODS}")
    assert body["bathing_samples"]["state"] == "not-built" and body["indicators"]["escherichia_coli"]["periods"]["a"]["n_samples"] == 0
    assert "no-data-for-scope" in body["indicators"]["escherichia_coli"]["flags"]


def test_the_change_notices_follow_the_language(http, both):
    body = _get(http, f"/bathing-waters/ITSYN001/samples/change?{PERIODS}&language=de")
    assert body["change_notice"] == load_strings("de").get("bathing_samples_change_notice") and body["language"] == "de"


# --- GET /bathing-waters/samples/change (a country) --------------------------------------------------------------------------


def test_a_country_comparison_uses_paired_bathing_waters_only_and_is_exact(http, both):
    body = _get(http, f"/bathing-waters/samples/change?country=IT&{PERIODS}")
    assert body["scope"] == {"type": "country", "id": None, "code": "IT", "name": None, "country": "IT"} and body["flags"] == []
    coli = body["indicators"]["escherichia_coli"]
    assert (coli["n_sites_considered"], coli["n_sites_paired"], coli["n_sites_excluded"]) == (4, 2, 2)
    assert coli["exclusion_reasons"] == {"absent-in-period-b": 1, "insufficient-samples": 1}
    a, b = coli["periods"]["a"], coli["periods"]["b"]
    assert (a["n_sites"], a["n_samples"], a["mean_of_site_means"], a["median_of_site_medians"]) == (2, 7, 42.5, 42.5)  # sites 25 and 60
    assert (b["n_sites"], b["n_samples"], b["mean_of_site_means"], b["median_of_site_medians"]) == (2, 7, 190.5, 128.0)  # sites 375 and 6; medians 250 and 6
    assert coli["change_of_site_means"] == {"absolute": 148.0, "relative_percent": 348.2353, "relative_percent_note": None, "direction": "increased"}
    assert coli["change_of_site_medians"] == {"absolute": 85.5, "relative_percent": 201.1765, "relative_percent_note": None, "direction": "increased"}
    assert coli["median_site_relative_change_percent"] == 655.0  # the per-site changes are +1400 and -90
    assert (coli["sites_increased"], coli["sites_decreased"], coli["sites_unchanged"]) == (1, 1, 0)
    assert "few-sites" in coli["flags"] and coli["few_sites_threshold"] == 5 and coli["status"] == "ok"
    assert (b["n_detection_limit_all_sites"], b["n_missing_all_sites"], b["n_confirmed_high_all_sites"]) == (1, 1, 1)
    assert a["n_detection_limit_all_sites"] == 0 and coli["data_range"] == {"first": "2020-05", "last": "2022-08"}
    assert "confirmed-high-values-included" in b["flags"] and "detection-limit-values-excluded" in b["flags"]
    text = json.dumps(body)
    assert "crossed_limit" not in text and "river_limit" not in text and "limit_basis" not in text


def test_the_same_set_of_bathing_waters_is_used_in_both_periods(http, both):
    coli = _get(http, f"/bathing-waters/samples/change?country=IT&{PERIODS}")["indicators"]["escherichia_coli"]
    assert coli["periods"]["a"]["n_sites"] == coli["periods"]["b"]["n_sites"] == coli["n_sites_paired"]
    # ITSYN002 (samples in period A only) and ITSYN003 (two samples in period B) never enter either period
    assert coli["periods"]["a"]["n_samples"] == 7 and coli["periods"]["b"]["n_samples"] == 7


def test_a_country_period_beyond_the_data_is_reported_never_shifted(http, both):
    body = _get(http, "/bathing-waters/samples/change?country=IT&a_from=2021-05&a_to=2021-05&b_from=2026-05&b_to=2026-05")
    coli = body["indicators"]["escherichia_coli"]
    assert coli["status"] == "insufficient-data" and coli["n_sites_paired"] == 0 and "period-outside-data" in coli["periods"]["b"]["flags"]
    assert coli["data_range"] == {"first": "2020-05", "last": "2022-08"}


def test_el_is_read_as_gr_and_norway_and_an_empty_store_have_no_samples(http, both):
    greek = _get(http, "/bathing-waters/samples/change?country=el&a_from=2023-05&a_to=2023-06&b_from=2023-07&b_to=2023-08")
    assert greek["scope"]["code"] == "GR" and greek["flags"] == []
    assert greek["indicators"]["escherichia_coli"]["data_range"] == {"first": "2023-05", "last": "2023-07"}
    norway = _get(http, f"/bathing-waters/samples/change?country=NO&{PERIODS}")
    assert norway["flags"] == ["no-samples-for-country"] and norway["scope"]["code"] == "NO"
    assert norway["indicators"]["escherichia_coli"]["n_sites_considered"] == 0 and "no-data-for-scope" in norway["indicators"]["escherichia_coli"]["flags"]


def test_a_country_comparison_without_a_store_says_so(http, tmp_path: Path, monkeypatch):
    monkeypatch.setenv("OAH_BATHING_SAMPLES_STORE", str(tmp_path / "absent.sqlite"))
    body = _get(http, f"/bathing-waters/samples/change?country=IT&{PERIODS}")
    assert body["flags"] == ["store-not-ready"] and body["bathing_samples"]["state"] == "not-built"


@pytest.mark.parametrize(
    "query",
    ["country=ITA&" + PERIODS, "country=1&" + PERIODS, PERIODS, "country=IT&a_from=2020-08&a_to=2020-05&b_from=2022-05&b_to=2022-08", "country=IT&" + PERIODS + "&language=nope"],
)
def test_a_country_comparison_validates_its_input(http, both, query):
    assert http.get(f"/bathing-waters/samples/change?{query}").status_code == 422


def test_the_country_route_is_not_taken_for_a_bathing_water_identifier(http, both):
    assert http.get(f"/bathing-waters/samples/change?country=IT&{PERIODS}").status_code == 200
    assert http.get("/bathing-waters/samples").status_code == 404  # one segment: a bathing water called "samples", unknown
    assert http.get("/bathing-waters/change?country=IT&season_a=2020&season_b=2022").status_code == 200  # the earlier route is untouched
