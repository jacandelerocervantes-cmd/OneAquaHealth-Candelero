"""Open-Meteo weather and discharge: request shape, monthly aggregation, flags, cache, graceful unavailability.

Every answer is scripted (``external_fakes``); nothing reaches the network.
"""
from __future__ import annotations

from datetime import date, timedelta

import httpx
import pytest
from external_fakes import FakeClock, Router, archive_handler, flood_handler, json_response, make_runtime

from oah.external import constants as c
from oah.external import openmeteo
from oah.external.envelope import ExternalInputError
from oah.external.openmeteo import discharge_context, month_key, request_units, window_months, weather_context
from oah.external.settings import ExternalSettings
from oah.external.sites import LocatedSite

TODAY = date(2026, 10, 3)
RIVER = LocatedSite("ITRIVER1", "PO - TEST", "waterbase-site", "real-eea-waterbase", "IT", 45.07, 7.69, "river")
LAKE = LocatedSite("ITLAKE1", "LAKE", "waterbase-site", "real-eea-waterbase", "IT", 45.5, 9.2, "lake")
BATHING = LocatedSite("IT001", "LIDO", "bathing-water", "real-eea-bathing-water", "IT", 45.3197, 7.9005, "coastal-or-transitional")


def archive_runtime(handler=None, **kwargs):
    runtime, router, clock = make_runtime(**kwargs)
    router.on(c.ARCHIVE_HOST, handler or archive_handler())
    return runtime, router, clock


def flood_runtime(handler=None, **kwargs):
    runtime, router, clock = make_runtime(**kwargs)
    router.on(c.FLOOD_HOST, handler or flood_handler())
    return runtime, router, clock


# --- helpers ------------------------------------------------------------------------------------------------------


def test_request_units_follow_the_providers_rule_for_long_requests() -> None:
    assert request_units(1, 2) == 1.0 and request_units(14, 2) == 1.0
    assert request_units(14, 15) == 1.5  # 2 weeks with 15 variables = 1.5 calls (pricing page example)
    assert request_units(28, 15) == 3.0  # 4 weeks = 3.0 calls (pricing page example)
    assert request_units(1096, 2) == pytest.approx(1096 / 14)


def test_window_months_counts_the_days_of_each_month_inside_the_window() -> None:
    assert window_months(date(2021, 3, 1), date(2021, 4, 10)) == [("2021-03", 31), ("2021-04", 10)]
    assert window_months(date(2020, 12, 30), date(2021, 1, 2)) == [("2020-12", 2), ("2021-01", 2)]
    assert window_months(date(2024, 2, 10), date(2024, 2, 20)) == [("2024-02", 11)]
    assert window_months(date(2024, 2, 1), date(2024, 2, 29)) == [("2024-02", 29)]
    assert month_key(date(2021, 3, 9)) == "2021-03"


# --- weather -----------------------------------------------------------------------------------------------------------


def test_weather_monthly_aggregates_and_request_shape() -> None:
    runtime, router, _ = archive_runtime(archive_handler(rain=lambda d: 1.0 if d.month == 3 else 0.5, temp=lambda d: float(d.day)))
    result = weather_context(runtime, RIVER, date(2021, 3, 1), date(2021, 4, 10), TODAY)
    assert result["status"] == "ok" and result["reason"] is None and result["cached"] is False
    assert result["origin"] == "external-open-meteo" and result["data_kind"] == "modelled-reanalysis"
    assert result["attribution"].startswith("Weather data by Open-Meteo.com") and result["attribution_url"] == "https://open-meteo.com/"
    march, april = result["months"]
    assert march == {
        "month": "2021-03", "days_in_window": 31, "precipitation_sum_mm": 31.0, "precipitation_n_days": 31,
        "precipitation_coverage": 1.0, "temperature_mean_c": 16.0, "temperature_n_days": 31, "temperature_coverage": 1.0, "flags": [],
    }
    assert april["precipitation_sum_mm"] == 5.0 and april["temperature_mean_c"] == 5.5 and april["days_in_window"] == 10
    assert result["n_days_expected"] == 41 and result["n_days_with_data"] == 41 and result["flags"] == []
    assert router.count() == 1
    sent = router.params()
    assert sent["latitude"] == ["45.07"] and sent["longitude"] == ["7.69"]
    assert sent["start_date"] == ["2021-03-01"] and sent["end_date"] == ["2021-04-10"]
    assert sent["daily"] == ["precipitation_sum,temperature_2m_mean"] and sent["models"] == ["era5"] and sent["timezone"] == ["GMT"]
    assert router.requests[0].url.host == c.ARCHIVE_HOST and router.requests[0].url.path == "/v1/archive"
    grid = result["grid"]
    assert grid["grid_latitude"] == 45.0 and grid["grid_longitude"] == 7.75 and grid["distance_km"] > 5
    assert "0.25" in grid["resolution_note"]
    assert result["data_limits"]["first_day"] == "1940-01-01" and result["data_limits"]["era5_delay_days"] == 5
    assert result["data_limits"]["latest_day_expected_final"] == "2026-09-28"


def test_coordinates_are_rounded_before_they_are_sent() -> None:
    runtime, router, _ = archive_runtime()
    site = LocatedSite("S", "S", "waterbase-site", "x", "IT", 45.07649, 7.68551, "river")
    weather_context(runtime, site, date(2021, 3, 1), date(2021, 3, 3), TODAY)
    assert router.params()["latitude"] == ["45.08"] and router.params()["longitude"] == ["7.69"]


def test_null_days_are_not_filled_and_lower_the_coverage() -> None:
    runtime, _, _ = archive_runtime(archive_handler(rain=lambda d: None if d.day <= 5 else 2.0, temp=lambda d: None if d.day <= 10 else 12.0))
    month = weather_context(runtime, RIVER, date(2021, 3, 1), date(2021, 3, 31), TODAY)["months"][0]
    assert month["precipitation_n_days"] == 26 and month["precipitation_sum_mm"] == 52.0
    assert month["precipitation_coverage"] == round(26 / 31, 3)
    assert month["temperature_n_days"] == 21 and month["temperature_mean_c"] == 12.0 and month["temperature_coverage"] == round(21 / 31, 3)
    assert month["flags"] == ["partial-month"]


def test_era5_delay_flag_when_the_period_ends_within_five_days_of_today() -> None:
    cutoff = TODAY - timedelta(days=5)
    runtime, router, _ = archive_runtime(archive_handler(rain=lambda d: None if d > cutoff else 1.0, temp=lambda d: None if d > cutoff else 15.0))
    result = weather_context(runtime, RIVER, date(2026, 9, 20), TODAY, TODAY)
    assert "era5-delay" in result["flags"] and result["status"] == "ok"
    september, october = result["months"]
    assert september["precipitation_n_days"] == 9 and september["flags"] == ["partial-month"]
    assert october["flags"] == ["period-outside-data"] and october["precipitation_sum_mm"] is None
    # an old period carries no delay flag
    old = weather_context(runtime, RIVER, date(2021, 1, 1), date(2021, 1, 31), TODAY)
    assert "era5-delay" not in old["flags"]
    assert router.count() == 2


def test_a_period_ending_after_today_is_clipped_and_flagged() -> None:
    runtime, router, _ = archive_runtime()
    result = weather_context(runtime, RIVER, date(2026, 9, 1), date(2027, 3, 1), TODAY)
    assert "period-end-clipped" in result["flags"] and "era5-delay" in result["flags"]
    assert router.params()["end_date"] == [TODAY.isoformat()]
    assert result["period"] == {"date_from": "2026-09-01", "date_to": "2027-03-01"}  # what was asked is reported as asked


def test_a_period_wholly_before_the_archive_or_after_today_is_no_data_and_sends_nothing() -> None:
    runtime, router, _ = archive_runtime()
    before = weather_context(runtime, RIVER, date(1930, 1, 1), date(1930, 6, 1), TODAY)
    after = weather_context(runtime, RIVER, date(2026, 10, 4), date(2026, 12, 1), TODAY)
    for result in (before, after):
        assert result["status"] == "no-data" and result["flags"] == ["period-outside-data"] and result["months"] == []
        assert result["data_limits"]["first_day"] == "1940-01-01"
    assert router.requests == []


def test_a_period_starting_before_the_archive_is_clipped_at_its_first_day() -> None:
    runtime, router, _ = archive_runtime()
    result = weather_context(runtime, RIVER, date(1939, 12, 25), date(1940, 1, 5), TODAY)
    assert "period-start-clipped" in result["flags"] and router.params()["start_date"] == ["1940-01-01"]
    assert result["months"][0]["month"] == "1940-01"


def test_all_null_answer_is_no_data() -> None:
    runtime, _, _ = archive_runtime(archive_handler(rain=lambda d: None, temp=lambda d: None))
    result = weather_context(runtime, RIVER, date(2021, 3, 1), date(2021, 3, 10), TODAY)
    assert result["status"] == "no-data" and "period-outside-data" in result["flags"] and result["n_days_with_data"] == 0
    assert result["months"][0]["flags"] == ["period-outside-data"]


def test_implausible_values_are_ignored_and_flagged() -> None:
    runtime, _, _ = archive_runtime(archive_handler(rain=lambda d: 5000.0 if d.day == 1 else 1.0, temp=lambda d: -999.0 if d.day == 2 else 10.0))
    result = weather_context(runtime, RIVER, date(2021, 3, 1), date(2021, 3, 10), TODAY)
    month = result["months"][0]
    assert "implausible-values-ignored" in result["flags"]
    assert month["precipitation_n_days"] == 9 and month["precipitation_sum_mm"] == 9.0
    assert month["temperature_n_days"] == 9 and month["temperature_mean_c"] == 10.0


@pytest.mark.parametrize("date_from, date_to", [(date(2021, 5, 2), date(2021, 5, 1)), (date(2018, 1, 1), date(2021, 1, 1))])
def test_invalid_periods_are_input_errors_and_send_nothing(date_from: date, date_to: date) -> None:
    runtime, router, _ = archive_runtime()
    with pytest.raises(ExternalInputError):
        weather_context(runtime, RIVER, date_from, date_to, TODAY)
    assert router.requests == []


def test_the_longest_period_is_accepted_and_charges_the_estimated_units() -> None:
    runtime, router, _ = archive_runtime()
    start = date(2018, 1, 1)
    end = start + timedelta(days=c.MAX_SPAN_DAYS - 1)
    result = weather_context(runtime, RIVER, start, end, TODAY)
    assert result["status"] == "ok" and result["n_days_expected"] == c.MAX_SPAN_DAYS
    spent = runtime.settings.open_meteo_daily - runtime.budget_remaining(c.PROVIDER_WEATHER)["per_day_remaining"]
    assert spent == pytest.approx(c.MAX_SPAN_DAYS / 14, abs=0.01)
    assert len(result["months"]) == 36
    assert router.count() == 1


def test_a_second_identical_question_is_answered_from_the_cache_and_a_nearby_point_shares_it() -> None:
    runtime, router, clock = archive_runtime(settings=ExternalSettings(cache_ttl_seconds=60.0, max_retries=0))
    first = weather_context(runtime, RIVER, date(2021, 3, 1), date(2021, 3, 10), TODAY)
    again = weather_context(runtime, RIVER, date(2021, 3, 1), date(2021, 3, 10), TODAY)
    near = LocatedSite("N", "N", "waterbase-site", "x", "IT", 45.071, 7.691, "river")
    nearby = weather_context(runtime, near, date(2021, 3, 1), date(2021, 3, 10), TODAY)
    assert first["cached"] is False and again["cached"] is True and nearby["cached"] is True
    assert router.count() == 1
    different = weather_context(runtime, RIVER, date(2021, 3, 1), date(2021, 3, 11), TODAY)
    assert different["cached"] is False and router.count() == 2
    clock.advance(61)
    expired = weather_context(runtime, RIVER, date(2021, 3, 1), date(2021, 3, 10), TODAY)
    assert expired["cached"] is False and router.count() == 3


def assert_unavailable(result: dict, reason: str) -> None:
    assert result["status"] == "external-unavailable" and result["reason"] == reason
    assert result["months"] == [] and result["origin"] == "external-open-meteo"
    assert result["attribution"] and result["data_note"]


def test_provider_problems_become_external_unavailable_never_an_exception() -> None:
    cases: list[tuple[str, object]] = [
        (c.REASON_RATE_LIMITED, lambda request: httpx.Response(429, headers={"retry-after": "30"})),
        (c.REASON_HTTP, lambda request: httpx.Response(503)),
        (c.REASON_BAD_RESPONSE, lambda request: httpx.Response(200, content=b"{broken", headers={"content-type": "application/json"})),
        (c.REASON_BAD_RESPONSE, lambda request: httpx.Response(200, content=b"<html/>", headers={"content-type": "text/html"})),
        (c.REASON_TOO_LARGE, lambda request: httpx.Response(200, content=b'{"x":"' + b"a" * (2 * 1024 * 1024) + b'"}', headers={"content-type": "application/json"})),
    ]
    for reason, handler in cases:
        runtime, _, _ = archive_runtime(handler)
        assert_unavailable(weather_context(runtime, RIVER, date(2021, 3, 1), date(2021, 3, 10), TODAY), reason)

    def timeout(request: httpx.Request) -> httpx.Response:
        raise httpx.ReadTimeout("slow", request=request)

    runtime, _, _ = archive_runtime(timeout)
    assert_unavailable(weather_context(runtime, RIVER, date(2021, 3, 1), date(2021, 3, 10), TODAY), c.REASON_TIMEOUT)


def test_budget_exhaustion_and_switches_are_graceful() -> None:
    runtime, router, _ = archive_runtime(settings=ExternalSettings(open_meteo_per_minute=2, max_retries=0))
    result = weather_context(runtime, RIVER, date(2018, 1, 1), date(2020, 12, 31), TODAY)  # ~78 units against 2
    assert_unavailable(result, c.REASON_BUDGET)
    assert router.requests == []
    for settings in (ExternalSettings(enabled=False), ExternalSettings(open_meteo_enabled=False)):
        runtime, router, _ = archive_runtime(settings=settings)
        assert_unavailable(weather_context(runtime, RIVER, date(2021, 3, 1), date(2021, 3, 10), TODAY), c.REASON_DISABLED)
        assert router.requests == []


def test_a_failure_is_not_cached_so_the_next_call_can_succeed() -> None:
    runtime, router, clock = archive_runtime()
    state = {"fail": True}
    ok = archive_handler()
    router.on(c.ARCHIVE_HOST, lambda request: httpx.Response(503) if state["fail"] else ok(request))
    assert weather_context(runtime, RIVER, date(2021, 3, 1), date(2021, 3, 3), TODAY)["status"] == "external-unavailable"
    state["fail"] = False
    clock.advance(31)  # past the failure cool-down, if one opened
    assert weather_context(runtime, RIVER, date(2021, 3, 1), date(2021, 3, 3), TODAY)["status"] == "ok"


@pytest.mark.parametrize(
    "payload",
    [
        {"error": True, "reason": "x"},
        {},
        {"daily": []},
        {"daily": {"time": [], "precipitation_sum": [], "temperature_2m_mean": []}},
        {"daily": {"time": ["2021-03-01"], "precipitation_sum": [1.0]}},  # a variable missing
        {"daily": {"time": ["2021-03-01"], "precipitation_sum": [1.0, 2.0], "temperature_2m_mean": [1.0]}},  # wrong length
        {"daily": {"time": ["nope"], "precipitation_sum": [1.0], "temperature_2m_mean": [1.0]}},
        {"daily": {"time": ["2021-03-01"], "precipitation_sum": ["wet"], "temperature_2m_mean": [1.0]}},
        {"daily": {"time": ["2021-03-01"], "precipitation_sum": [True], "temperature_2m_mean": [1.0]}},
        {"daily": {"time": ["2020-01-01"], "precipitation_sum": [1.0], "temperature_2m_mean": [1.0]}},  # outside the request
        {"daily": {"time": ["2021-03-02", "2021-03-01"], "precipitation_sum": [1.0, 1.0], "temperature_2m_mean": [1.0, 1.0]}},
        {"daily": {"time": ["2021-03-01"] * 2, "precipitation_sum": [1.0, 1.0], "temperature_2m_mean": [1.0, 1.0]}},
    ],
)
def test_a_payload_that_does_not_fit_the_request_is_a_bad_response(payload: dict) -> None:
    runtime, _, _ = archive_runtime(lambda request: json_response(payload))
    assert_unavailable(weather_context(runtime, RIVER, date(2021, 3, 1), date(2021, 3, 1), TODAY), c.REASON_BAD_RESPONSE)


def test_nan_inside_json_is_a_bad_response() -> None:
    body = b'{"daily": {"time": ["2021-03-01"], "precipitation_sum": [NaN], "temperature_2m_mean": [1.0]}}'
    runtime, _, _ = archive_runtime(lambda request: httpx.Response(200, content=body, headers={"content-type": "application/json"}))
    assert_unavailable(weather_context(runtime, RIVER, date(2021, 3, 1), date(2021, 3, 1), TODAY), c.REASON_BAD_RESPONSE)


def test_a_bathing_water_gets_weather_without_a_discharge_caveat_in_the_weather_flags() -> None:
    runtime, _, _ = archive_runtime()
    result = weather_context(runtime, BATHING, date(2021, 3, 1), date(2021, 3, 3), TODAY)
    assert result["status"] == "ok" and "site-not-a-river" not in result["flags"]


# --- discharge ----------------------------------------------------------------------------------------------------------


def test_discharge_monthly_means_request_shape_and_caveats() -> None:
    runtime, router, _ = flood_runtime(flood_handler(flow=lambda d: float(d.day)))
    result = discharge_context(runtime, RIVER, date(2021, 3, 1), date(2021, 4, 10), TODAY)
    assert result["status"] == "ok" and result["origin"] == "external-open-meteo" and result["data_kind"] == "modelled-river-discharge"
    assert result["attribution_verified"] is False
    march, april = result["months"]
    assert march["river_discharge_mean_m3s"] == 16.0 and march["n_days"] == 31 and march["coverage"] == 1.0 and march["flags"] == []
    assert april["river_discharge_mean_m3s"] == 5.5 and april["days_in_window"] == 10
    assert "nearest-cell-may-not-be-the-river" in result["flags"] and "site-not-a-river" not in result["flags"]
    sent = router.params()
    assert sent["models"] == ["consolidated_v4"] and sent["daily"] == ["river_discharge"] and "timezone" not in sent
    assert router.requests[0].url.host == c.FLOOD_HOST and router.requests[0].url.path == "/v1/flood"
    assert result["grid"]["distance_km"] is not None and "0.05" in result["grid"]["resolution_note"]
    assert result["data_range"] == {"first_day": "2021-03-01", "last_day": "2021-04-10"}
    assert result["data_limits"]["first_day"] == "1984-01-01" and result["data_limits"]["documented_history_end"] == "2022-07-31"


def test_discharge_months_after_the_documented_history_are_flagged_not_dropped() -> None:
    runtime, _, _ = flood_runtime()
    result = discharge_context(runtime, RIVER, date(2022, 6, 1), date(2022, 9, 30), TODAY)
    flags = {month["month"]: month["flags"] for month in result["months"]}
    assert flags == {"2022-06": [], "2022-07": [], "2022-08": ["beyond-documented-history"], "2022-09": ["beyond-documented-history"]}


def test_discharge_beyond_the_real_end_of_the_data_is_period_outside_data() -> None:
    last = date(2025, 3, 15)
    runtime, _, _ = flood_runtime(flood_handler(flow=lambda d: None if d > last else 80.0))
    result = discharge_context(runtime, RIVER, date(2025, 3, 1), date(2025, 5, 31), TODAY)
    assert result["status"] == "ok" and result["data_range"] == {"first_day": "2025-03-01", "last_day": "2025-03-15"}
    march, april, may = result["months"]
    assert march["flags"] == ["partial-month", "beyond-documented-history"] and march["n_days"] == 15
    assert april["flags"] == ["period-outside-data"] and april["river_discharge_mean_m3s"] is None and may["n_days"] == 0
    nothing = discharge_context(runtime, RIVER, date(2025, 6, 1), date(2025, 6, 30), TODAY)
    assert nothing["status"] == "no-data" and "period-outside-data" in nothing["flags"] and nothing["data_range"] is None


def test_discharge_period_limits_and_validation() -> None:
    runtime, router, _ = flood_runtime()
    before = discharge_context(runtime, RIVER, date(1981, 1, 1), date(1983, 12, 31), TODAY)
    assert before["status"] == "no-data" and "period-outside-data" in before["flags"] and router.requests == []
    clipped = discharge_context(runtime, RIVER, date(1983, 12, 20), date(1984, 1, 10), TODAY)
    assert "period-start-clipped" in clipped["flags"] and router.params()["start_date"] == ["1984-01-01"]
    future = discharge_context(runtime, RIVER, date(2026, 9, 1), date(2027, 1, 1), TODAY)
    assert "period-end-clipped" in future["flags"] and router.params()["end_date"] == [TODAY.isoformat()]
    with pytest.raises(ExternalInputError):
        discharge_context(runtime, RIVER, date(2021, 2, 1), date(2021, 1, 1), TODAY)
    with pytest.raises(ExternalInputError):
        discharge_context(runtime, RIVER, date(2015, 1, 1), date(2021, 1, 1), TODAY)


def test_a_lake_or_coastal_site_gets_the_not_a_river_flag() -> None:
    runtime, _, _ = flood_runtime()
    for site in (LAKE, BATHING):
        flags = discharge_context(runtime, site, date(2021, 3, 1), date(2021, 3, 5), TODAY)["flags"]
        assert "site-not-a-river" in flags and "nearest-cell-may-not-be-the-river" in flags
    unknown = LocatedSite("S", "S", "sandbox-site", "x", "GR", 35.3, 24.4, None)
    assert "site-not-a-river" not in discharge_context(runtime, unknown, date(2021, 3, 1), date(2021, 3, 5), TODAY)["flags"]


def test_discharge_cache_and_failures() -> None:
    runtime, router, _ = flood_runtime()
    first = discharge_context(runtime, RIVER, date(2021, 3, 1), date(2021, 3, 5), TODAY)
    again = discharge_context(runtime, RIVER, date(2021, 3, 1), date(2021, 3, 5), TODAY)
    assert (first["cached"], again["cached"], router.count()) == (False, True, 1)

    failing, _, _ = flood_runtime(lambda request: httpx.Response(429))
    result = discharge_context(failing, RIVER, date(2021, 3, 1), date(2021, 3, 5), TODAY)
    assert result["status"] == "external-unavailable" and result["reason"] == c.REASON_RATE_LIMITED
    assert "nearest-cell-may-not-be-the-river" in result["flags"] and result["months"] == []

    off, router_off, _ = flood_runtime(settings=ExternalSettings(glofas_enabled=False))
    assert discharge_context(off, RIVER, date(2021, 3, 1), date(2021, 3, 5), TODAY)["reason"] == c.REASON_DISABLED
    assert router_off.requests == []
    # the weather switch does not disable discharge and the other way round
    weather_off, router_w, _ = flood_runtime(settings=ExternalSettings(open_meteo_enabled=False))
    assert discharge_context(weather_off, RIVER, date(2021, 3, 1), date(2021, 3, 5), TODAY)["status"] == "ok"


def test_discharge_implausible_and_malformed_payloads() -> None:
    runtime, _, _ = flood_runtime(flood_handler(flow=lambda d: -5.0 if d.day == 1 else 10.0))
    result = discharge_context(runtime, RIVER, date(2021, 3, 1), date(2021, 3, 4), TODAY)
    assert "implausible-values-ignored" in result["flags"] and result["months"][0]["n_days"] == 3
    bad, _, _ = flood_runtime(lambda request: json_response({"daily": {"time": ["2021-03-01"]}}))
    assert discharge_context(bad, RIVER, date(2021, 3, 1), date(2021, 3, 1), TODAY)["reason"] == c.REASON_BAD_RESPONSE


def test_parse_daily_missing_grid_gives_no_distance() -> None:
    series = openmeteo.parse_daily(
        {"daily": {"time": ["2021-03-01"], "river_discharge": [1.0]}}, ("river_discharge",), date(2021, 3, 1), date(2021, 3, 1),
        {"river_discharge": (0.0, 10.0)},
    )
    assert series.grid_latitude is None and series.values["river_discharge"] == (1.0,)
    block = openmeteo._grid_block(series, 45.0, 7.0, "note")
    assert block["distance_km"] is None and block["resolution_note"] == "note"


def test_clock_and_router_helpers_are_consistent() -> None:
    clock = FakeClock(5.0)
    clock.advance(2.5)
    assert clock() == 7.5
    assert Router().count() == 0
