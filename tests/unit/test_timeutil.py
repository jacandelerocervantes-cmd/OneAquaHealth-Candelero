"""The unified time policy: UTC internally, FHIR precision kept, daylight saving changes never silent.

All dates are the 2026 European clock changes (the last Sundays of March and October), checked against the
IANA data: Athens moves 03:00 -> 04:00 on 2026-03-29 and 04:00 -> 03:00 on 2026-10-25; Rome moves
02:00 -> 03:00 and 03:00 -> 02:00 on the same dates.
"""
from datetime import UTC, date, datetime, timedelta, timezone

import pytest
from hypothesis import given
from hypothesis import strategies as st

from oah import timeutil as t

ATHENS, ROME = "Europe/Athens", "Europe/Rome"


def _utc(*args):
    return datetime(*args, tzinfo=UTC)


# --- one clock, one format, never naive -------------------------------------------------------------------


def test_the_clock_is_aware_and_utc():
    now = t.utc_now()
    assert now.tzinfo is not None and now.utcoffset() == timedelta(0)


def test_a_naive_datetime_is_never_an_instant():
    with pytest.raises(t.TimeError):
        t.require_aware(datetime(2026, 9, 26, 12, 0))
    with pytest.raises(t.TimeError):
        t.format_utc(datetime(2026, 9, 26, 12, 0))


def test_every_offset_serialises_to_the_same_utc_text():
    cairo = datetime(2026, 9, 26, 14, 0, tzinfo=timezone(timedelta(hours=2)))
    assert t.format_utc(cairo) == t.format_utc(_utc(2026, 9, 26, 12, 0)) == "2026-09-26T12:00:00+00:00"


def test_epoch_units_are_explicit():
    assert t.from_epoch_seconds(1_800_000_000) == t.from_epoch_millis(1_800_000_000_000)
    assert t.from_epoch_seconds(0) == _utc(1970, 1, 1)


# --- FHIR parsing keeps precision -------------------------------------------------------------------------


def test_an_instant_with_z_or_an_offset_is_exact():
    z = t.parse_fhir_time("2026-09-26T10:00:00Z")
    plus = t.parse_fhir_time("2026-09-26T13:00:00+03:00")
    assert z.precision == "second" and z.tz_source == "explicit"
    assert z.instant == plus.instant == _utc(2026, 9, 26, 10, 0)


def test_fractions_of_a_second_are_kept_exactly():
    assert t.parse_fhir_time("2026-09-26T10:00:00.123456Z").instant == _utc(2026, 9, 26, 10, 0, 0, 123456)
    assert t.parse_fhir_time("2026-09-26T10:00:00.5Z").instant == _utc(2026, 9, 26, 10, 0, 0, 500000)


def test_a_date_without_a_timezone_is_a_utc_interval_and_says_so():
    day = t.parse_fhir_time("2026-09-26")
    assert (day.precision, day.tz_source) == ("day", "none")
    assert (day.start, day.end) == (_utc(2026, 9, 26), _utc(2026, 9, 27))
    assert day.instant is None


def test_a_date_with_a_site_timezone_is_that_sites_local_day():
    day = t.parse_fhir_time("2026-09-26", site_tz=ATHENS)  # Athens is UTC+3 in September
    assert (day.start, day.end) == (_utc(2026, 9, 25, 21), _utc(2026, 9, 26, 21))
    assert day.tz_source == "site"


def test_a_local_day_is_23_hours_when_the_clocks_go_forward_and_25_when_they_go_back():
    spring = t.parse_fhir_time("2026-03-29", site_tz=ATHENS)
    autumn = t.parse_fhir_time("2026-10-25", site_tz=ATHENS)
    assert spring.end - spring.start == timedelta(hours=23)
    assert autumn.end - autumn.start == timedelta(hours=25)
    rome_spring = t.parse_fhir_time("2026-03-29", site_tz=ROME)
    assert rome_spring.end - rome_spring.start == timedelta(hours=23)


def test_month_and_year_precision_including_december_and_leap_february():
    assert t.parse_fhir_time("2026-12").end == _utc(2027, 1, 1)
    assert t.parse_fhir_time("2028-02").end - t.parse_fhir_time("2028-02").start == timedelta(days=29)
    year = t.parse_fhir_time("2026")
    assert (year.precision, year.start, year.end) == ("year", _utc(2026, 1, 1), _utc(2027, 1, 1))


@pytest.mark.parametrize("bad", ["", "tomorrow", "26-09", "2026-13-01", "2026-02-30", "2026-09-26T25:00:00Z", "2026-09-26 10:00:00Z"])
def test_invalid_values_are_rejected(bad):
    with pytest.raises(t.TimeError):
        t.parse_fhir_time(bad)


def test_a_time_of_day_without_an_offset_is_never_guessed():
    with pytest.raises(t.TimeError, match="no offset"):
        t.parse_fhir_time("2026-09-26T10:00:00")
    assert t.parse_fhir_time("2026-09-26T10:00:00", site_tz=ATHENS).instant == _utc(2026, 9, 26, 7, 0)


# --- clock changes are never silent -----------------------------------------------------------------------


def test_a_local_time_skipped_by_the_spring_change_is_reported():
    with pytest.raises(t.NonexistentLocalTime):
        t.parse_fhir_time("2026-03-29T03:30:00", site_tz=ATHENS)
    with pytest.raises(t.NonexistentLocalTime):
        t.parse_fhir_time("2026-03-29T02:30:00", site_tz=ROME)


def test_a_skipped_time_can_be_shifted_forward_explicitly():
    athens = t.parse_fhir_time("2026-03-29T03:30:00", site_tz=ATHENS, on_gap="shift-forward")
    assert athens.instant == _utc(2026, 3, 29, 1, 30)  # 04:30 EEST
    rome = t.parse_fhir_time("2026-03-29T02:30:00", site_tz=ROME, on_gap="shift-forward")
    assert rome.instant == _utc(2026, 3, 29, 1, 30)  # 03:30 CEST


def test_a_local_time_that_happens_twice_is_reported():
    with pytest.raises(t.AmbiguousLocalTime):
        t.parse_fhir_time("2026-10-25T03:30:00", site_tz=ATHENS)
    with pytest.raises(t.AmbiguousLocalTime):
        t.parse_fhir_time("2026-10-25T02:30:00", site_tz=ROME)


def test_the_caller_can_choose_which_occurrence_is_meant():
    early = t.parse_fhir_time("2026-10-25T03:30:00", site_tz=ATHENS, on_ambiguous="earliest").instant
    late = t.parse_fhir_time("2026-10-25T03:30:00", site_tz=ATHENS, on_ambiguous="latest").instant
    assert (early, late) == (_utc(2026, 10, 25, 0, 30), _utc(2026, 10, 25, 1, 30))
    assert late - early == timedelta(hours=1)


def test_times_next_to_a_change_are_not_flagged():
    assert t.parse_fhir_time("2026-03-29T02:59:59", site_tz=ATHENS).instant == _utc(2026, 3, 29, 0, 59, 59)
    assert t.parse_fhir_time("2026-03-29T04:00:00", site_tz=ATHENS).instant == _utc(2026, 3, 29, 1, 0)
    assert t.parse_fhir_time("2026-10-25T02:59:59", site_tz=ATHENS).instant == _utc(2026, 10, 24, 23, 59, 59)


# --- arithmetic --------------------------------------------------------------------------------------------


def test_elapsed_time_is_true_elapsed_time_across_a_clock_change():
    start = t.to_local(_utc(2026, 3, 28, 22), ATHENS)  # 2026-03-29 00:00 local (EET)
    end = t.to_local(_utc(2026, 3, 29, 21), ATHENS)  # 2026-03-30 00:00 local (EEST)
    assert (start.date(), end.date()) == (date(2026, 3, 29), date(2026, 3, 30))
    assert t.elapsed(start, end) == timedelta(hours=23)
    assert end.replace(tzinfo=None) - start.replace(tzinfo=None) == timedelta(hours=24)  # the wall clock lies


def test_adding_local_days_keeps_the_wall_clock_hour():
    noon = t.parse_fhir_time("2026-03-28T12:00:00", site_tz=ATHENS).instant
    local = t.to_local(noon, ATHENS)
    next_day = t.add_local_days(local, 1)
    assert next_day.hour == 12 and next_day.day == 29
    assert t.elapsed(local, next_day) == timedelta(hours=23)


def test_local_display_never_changes_the_instant():
    instant = _utc(2026, 7, 1, 12)
    assert t.to_local(instant, ATHENS) == instant and t.to_local(instant, ATHENS).hour == 15


# --- zones -------------------------------------------------------------------------------------------------


def test_pilot_countries_have_a_timezone_and_others_are_refused():
    assert t.site_timezone("EL") == t.site_timezone("gr") == ATHENS
    assert t.site_timezone("IT") == ROME
    with pytest.raises(t.TimeError):
        t.site_timezone("FR")


def test_an_unknown_timezone_is_a_clear_error():
    with pytest.raises(t.TimeError, match="Unknown timezone"):
        t.zone("Mars/Olympus")


@given(st.datetimes(min_value=datetime(1970, 1, 1), max_value=datetime(2100, 1, 1), timezones=st.timezones()))
def test_any_aware_instant_round_trips_through_text(value):
    text = t.format_utc(value)
    assert t.parse_fhir_time(text).instant == t.to_utc(value)
