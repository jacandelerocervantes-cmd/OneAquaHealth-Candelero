"""The Waterbase store build: filters, aggregation, BOM, below-LOQ handling, atomic and deterministic writes."""

from __future__ import annotations

import json
import math
import sqlite3
from pathlib import Path

import pytest
from waterbase_fixtures import (
    AMMONIUM,
    HEADER,
    NITRATE,
    NITRITE,
    OXYGEN,
    PH,
    TOTAL_P,
    build_fixture_store,
    disaggregated_lines,
    make_archive,
    obs,
    standard_rows,
    standard_spatial,
)

from oah.waterbase.build import (
    aggregate_disaggregated,
    build_store,
    compute_sha256,
    read_sha256_sidecar,
    read_spatial,
    sevenzip_lines,
    zip_lines,
)
from oah.paths import sevenzip_executable


def _aggregates(rows=None, min_year=2010):
    return aggregate_disaggregated(disaggregated_lines(rows), min_year)


def test_rows_are_aggregated_per_site_determinand_matrix_unit_year_and_month():
    aggregates, _ = _aggregates()
    # [n, sum, min, max, n_below_loq, n_lower_reliability]; the samples of March and September 2015 stay apart
    march = ("IT", "IT01-001025", "RW", NITRATE[0], "W", "mg{NO3}/L", 2015, 3)
    september = ("IT", "IT01-001025", "RW", NITRATE[0], "W", "mg{NO3}/L", 2015, 9)
    assert aggregates[march] == [1.0, 1.0, 1.0, 1.0, 0.0, 0.0]
    assert aggregates[september] == [1.0, 3.0, 3.0, 3.0, 0.0, 1.0]
    assert aggregates[("IT", "IT01-001025", "RW", NITRATE[0], "W", "mg{NO3}/L", 2016, 1)][0] == 1.0  # the multi-line record


def test_two_samples_of_the_same_month_are_summed_and_a_bad_month_is_dropped():
    rows = [
        obs(NITRATE, "1.0", date="20150312"), obs(NITRATE, "4.0", date="20150330"),
        obs(NITRATE, "9.0", date="20151312"),  # month 13
        obs(NITRATE, "9.0", date="20150012"),  # month 0
        obs(NITRATE, "2.0", date="2015-07-04"),  # the dashed spelling is read too
    ]
    aggregates, counters = _aggregates(rows)
    key = ("IT", "IT01-001025", "RW", NITRATE[0], "W", "mg{NO3}/L", 2015, 3)
    assert aggregates[key] == [2.0, 5.0, 1.0, 4.0, 0.0, 0.0]
    assert ("IT", "IT01-001025", "RW", NITRATE[0], "W", "mg{NO3}/L", 2015, 7) in aggregates
    assert counters["dropped_bad_date"] == 2 and len(aggregates) == 2


def test_ph_values_outside_the_scale_are_dropped_and_counted_and_never_aggregated():
    rows = [
        obs(PH, "7.4", date="20150312"), obs(PH, "8.2", date="20150320"),
        obs(PH, "74", date="20150321"), obs(PH, "-1", date="20150322"), obs(PH, "14.5", date="20150323"),
        obs(PH, "0", date="20150401"), obs(PH, "14", date="20150402"),  # the bounds themselves are kept
        obs(NITRATE, "74", date="20150312"),  # no other determinand is bounded
        obs(PH, "99", date="20160101"),  # a month holding only an implausible value creates no group
    ]
    aggregates, counters = _aggregates(rows)
    march = aggregates[("IT", "IT01-001025", "RW", PH[0], "W", "[pH]", 2015, 3)]
    assert march == pytest.approx([2.0, 15.6, 7.4, 8.2, 0.0, 0.0])
    assert aggregates[("IT", "IT01-001025", "RW", PH[0], "W", "[pH]", 2015, 4)][:4] == [2.0, 14.0, 0.0, 14.0]
    assert aggregates[("IT", "IT01-001025", "RW", NITRATE[0], "W", "mg{NO3}/L", 2015, 3)][3] == 74.0
    assert ("IT", "IT01-001025", "RW", PH[0], "W", "[pH]", 2016, 1) not in aggregates
    assert counters["dropped_implausible_value"] == 4


def test_the_plausible_ranges_are_stored_in_the_provenance_filters():
    from oah.waterbase.mapping import PLAUSIBLE_RANGES

    assert PLAUSIBLE_RANGES == {"EEA_3152-01-0": (0.0, 14.0)}


def test_el_is_stored_as_gr_and_the_other_country_codes_are_kept():
    aggregates, _ = _aggregates()
    assert {key[0] for key in aggregates} == {"GR", "IT", "NO"}
    assert not any(key[0] == "EL" for key in aggregates)


def test_below_loq_values_are_counted_and_never_used_as_a_value():
    aggregates, counters = _aggregates()
    quantified = aggregates[("GR", "EL000123", "RW", AMMONIUM[0], "W", "mg{NH4}/L", 2015, 3)]
    assert quantified == [1.0, 0.05, 0.05, 0.05, 0.0, 0.0]
    for month in (4, 5):  # the two LOQ rows (0.01) are counted in their own months and are not in sum, min or max
        assert aggregates[("GR", "EL000123", "RW", AMMONIUM[0], "W", "mg{NH4}/L", 2015, month)] == [0.0, 0.0, math.inf, -math.inf, 1.0, 0.0]
    only_loq = aggregates[("GR", "EL000123", "RW", NITRITE[0], "W", "mg{NO2}/L", 2017, 1)]
    assert only_loq[0] == 0.0 and only_loq[4] == 1.0 and only_loq[2] == float("inf")  # n=0: no min or max to report
    assert counters["rows_below_loq"] == 3


def test_lower_reliability_records_are_counted_not_dropped():
    aggregates, counters = _aggregates()
    june = aggregates[("GR", "EL000123", "RW", OXYGEN[0], "W", "mg/L", 2015, 6)]
    assert june[0] == 1.0 and june[5] == 1.0  # one V record, still in the mean
    assert counters["rows_lower_reliability"] == 2  # the U nitrate and the V oxygen record


def test_every_filter_drops_its_rows_and_counts_them():
    _, counters = _aggregates()
    assert counters["dropped_category"] == 2  # groundwater and coastal
    assert counters["dropped_matrix"] == 1
    assert counters["dropped_determinand"] == 1
    assert counters["dropped_missing_value_status"] == 2  # L and M
    assert counters["dropped_no_numeric_value"] == 2  # "NA" and "nan"
    assert counters["dropped_no_unit_or_site"] == 1
    assert counters["dropped_bad_date"] == 1
    assert counters["dropped_before_min_year"] == 1
    assert counters["rows_scanned"] == len(standard_rows())
    assert counters["rows_country_kept"] == len(standard_rows()) - 1  # the DE row is only counted as scanned
    kept = counters["rows_aggregated"] + counters["rows_below_loq"]
    dropped = sum(value for key, value in counters.items() if key.startswith("dropped_"))
    assert kept + dropped == counters["rows_country_kept"]


def test_the_minimum_year_is_a_parameter():
    aggregates, _ = _aggregates(min_year=2016)
    assert {key[6] for key in aggregates} == {2016, 2017}
    aggregates, _ = _aggregates(min_year=2000)
    assert 2008 in {key[6] for key in aggregates}


def test_a_quoted_field_spanning_two_lines_is_one_record_and_its_continuation_is_not_a_record():
    aggregates, counters = _aggregates()
    assert not any(key[1] == "not-a-record" for key in aggregates)
    assert counters["rows_scanned"] == len(standard_rows())  # the physical line count is larger


def test_a_header_without_the_bom_or_with_it_is_read_and_a_changed_layout_is_refused():
    lines = disaggregated_lines()
    assert lines[0].startswith(b"\xef\xbb\xbfcountryCode")  # the real files start with a BOM
    plain = [lines[0].removeprefix(b"\xef\xbb\xbf"), *lines[1:]]
    assert aggregate_disaggregated(plain)[0] == aggregate_disaggregated(lines)[0]
    renamed = [lines[0].replace(b"resultUom", b"unit"), *lines[1:]]
    with pytest.raises(ValueError, match="resultUom"):
        aggregate_disaggregated(renamed)
    with pytest.raises(ValueError):
        aggregate_disaggregated([])


def test_short_rows_are_counted_as_malformed():
    lines = disaggregated_lines([obs(NITRATE, "1.0")])
    lines.append(b"IT,only,three\r\n")
    _, counters = aggregate_disaggregated(lines)
    assert counters["rows_malformed"] == 1


def test_the_spatial_table_gives_names_coordinates_and_flags():
    import io

    spatial = read_spatial(io.StringIO(_spatial_text()))
    assert spatial[("IT", "IT01-001025")].lat == 44.65 and spatial[("IT", "IT01-001025")].water_body_name == "PO"
    assert spatial[("IT", "IT02-LAKE1")].name is None  # the placeholder UNKNOWN is not a name
    greek = spatial[("GR", "EL000123")]
    assert greek.lat is None and greek.lon is None and greek.confidentiality == "N"
    assert ("GR", "") not in spatial  # a water-body row has no site identifier


def _spatial_text() -> str:
    import csv
    import io

    from waterbase_fixtures import SPATIAL_HEADER

    out = io.StringIO()
    writer = csv.writer(out, lineterminator="\r\n")
    writer.writerow(SPATIAL_HEADER)
    writer.writerows(standard_spatial())
    return out.getvalue()


def test_a_site_listed_twice_keeps_the_row_with_coordinates():
    import io

    from waterbase_fixtures import SPATIAL_HEADER, spatial

    import csv

    out = io.StringIO()
    writer = csv.writer(out, lineterminator="\r\n")
    writer.writerow(SPATIAL_HEADER)
    writer.writerow(spatial("IT", "S1", "first", "riverWaterBody", "A", "", ""))
    writer.writerow(spatial("IT", "S1", "second", "riverWaterBody", "A", "45.0", "9.0"))
    writer.writerow(spatial("IT", "S2", "bad", "riverWaterBody", "A", "123.0", "9.0"))  # latitude out of range
    found = read_spatial(io.StringIO(out.getvalue()))
    assert found[("IT", "S1")].name == "second" and found[("IT", "S1")].lat == 45.0
    assert found[("IT", "S2")].lat is None and found[("IT", "S2")].lon is None


def test_the_store_has_the_tables_indexes_and_provenance(tmp_path: Path):
    target = build_fixture_store(tmp_path)
    connection = sqlite3.connect(target)
    try:
        tables = {row[0] for row in connection.execute("SELECT name FROM sqlite_master WHERE type='table'")}
        assert {"sites", "measurements", "provenance"} <= tables
        indexes = {row[0] for row in connection.execute("SELECT name FROM sqlite_master WHERE type='index' AND name LIKE 'idx_%'")}
        assert indexes == {"idx_sites_country"}  # the measurements table is read through its primary key (no second copy)
        assert {"country_ranges", "country_determinands"} <= tables
        provenance = dict(connection.execute("SELECT key, value FROM provenance"))
        assert provenance["licence"].startswith("CC BY 4.0") and provenance["build_date_utc"] == "2026-10-02T00:00:00Z"
        assert provenance["attribution"] == "EEA Waterbase - Water Quality ICM 2026 (CC BY 4.0)"
        assert provenance["archive_sha256_source"] == "none"  # a synthetic archive has no sidecar file
        filters = json.loads(provenance["filters"])
        assert filters["min_year"] == 2010 and filters["water_body_categories"] == ["LW", "RW"]
        assert filters["matrices"] == ["W", "W-DIS"] and "EEA_3152-01-0" in filters["determinand_codes"]
        counts = json.loads(provenance["row_counts"])
        assert counts["sites"] == 5 and counts["rows_scanned"] == len(standard_rows())
        assert counts["sites_without_spatial_row"] == 1 and counts["sites_without_location"] == 2
        sites = {row[0]: row for row in connection.execute("SELECT site_id, country, category, name, lat, confidentiality FROM sites")}
        assert sites["EL000123"][1:] == ("GR", "RW", "ALMYROS WELL FIELD", None, "N")
        assert sites["IT02-LAKE1"][2] == "LW" and sites["IT02-LAKE1"][3] is None
        assert sites["IT99-NOSPATIAL"][3] is None
        all_loq = connection.execute(
            "SELECT n, sum_value, min, max, n_below_loq, month FROM measurements WHERE determinand = ? AND year = 2017", [NITRITE[0]]
        ).fetchone()
        assert all_loq == (0, 0.0, None, None, 1, 1)
        assert provenance["schema_version"] == "3"
        ranges = dict(connection.execute("SELECT country, first_month || '/' || last_month FROM country_ranges"))
        assert ranges == {"GR": "2015-03/2017-01", "IT": "2015-03/2016-01", "NO": "2015-03/2015-06"}
    finally:
        connection.close()
    assert not list(tmp_path.glob("*.tmp"))


def test_the_build_is_deterministic_and_atomic(tmp_path: Path):
    first = build_fixture_store(tmp_path, name="a.sqlite")
    second = build_fixture_store(tmp_path, name="b.sqlite")

    def dump(path: Path) -> list[object]:
        connection = sqlite3.connect(path)
        try:
            return [
                list(connection.execute("SELECT * FROM measurements ORDER BY site_id, determinand, matrix, unit, year, month")),
                list(connection.execute("SELECT * FROM sites ORDER BY site_id")),
                list(connection.execute("SELECT * FROM provenance ORDER BY key")),
            ]
        finally:
            connection.close()

    assert dump(first) == dump(second)  # same input and build date, same store
    # a failing rebuild leaves the previous store untouched and no temporary file behind
    before = first.read_bytes()
    broken = make_archive(tmp_path / "broken.zip", rows=[obs(NITRATE, "1.0", country="DE")])
    with pytest.raises(RuntimeError, match="No row survived"):
        build_store(broken, first, tmp_path / "work", stream_factory=zip_lines)
    assert first.read_bytes() == before and not list(tmp_path.glob("*.tmp"))


def test_the_scratch_copies_are_removed(tmp_path: Path):
    build_fixture_store(tmp_path)
    assert list((tmp_path / "work").iterdir()) == []


def test_a_missing_archive_is_a_clear_error(tmp_path: Path):
    with pytest.raises(FileNotFoundError, match="docs/waterbase_store.md"):
        build_store(tmp_path / "nope.zip", tmp_path / "s.sqlite", tmp_path / "work", stream_factory=zip_lines)


def test_an_archive_without_the_inner_tables_is_refused(tmp_path: Path):
    import zipfile

    path = tmp_path / "wrong.zip"
    with zipfile.ZipFile(path, "w") as archive:
        archive.writestr("folder/README.md", "x")
    with pytest.raises(RuntimeError, match="no WISE6_SpatialObjects"):
        build_store(path, tmp_path / "s.sqlite", tmp_path / "work", stream_factory=zip_lines)


def _provenance(path: Path) -> dict[str, str]:
    connection = sqlite3.connect(path)
    try:
        return dict(connection.execute("SELECT key, value FROM provenance"))
    finally:
        connection.close()


def test_the_published_hash_is_read_from_the_sidecar_and_can_be_computed(tmp_path: Path):
    archive = make_archive(tmp_path / "archive.zip")
    sidecar = archive.with_name(archive.name + ".sha256")
    sidecar.write_text(f"{'AB' * 32}  archive.zip\n", encoding="utf-8")
    assert read_sha256_sidecar(archive) == "ab" * 32
    target = tmp_path / "s.sqlite"
    build_store(archive, target, tmp_path / "work", stream_factory=zip_lines)
    stored = _provenance(target)
    assert stored["archive_sha256"] == "ab" * 32 and stored["archive_sha256_source"] == "sidecar file"
    build_store(archive, target, tmp_path / "work", stream_factory=zip_lines, compute_hash=True)
    stored = _provenance(target)
    assert stored["archive_sha256"] == compute_sha256(archive) and stored["archive_sha256_source"] == "computed"


@pytest.mark.skipif(sevenzip_executable() is None, reason="7-Zip is not installed on this machine")
def test_the_seven_zip_stream_gives_the_same_aggregates_as_python(tmp_path: Path):
    archive = make_archive(tmp_path / "archive.zip")
    import zipfile

    with zipfile.ZipFile(archive) as outer:
        inner = tmp_path / "inner.zip"
        name = next(n for n in outer.namelist() if n.endswith("WISE6_DisaggregatedData-csv.zip"))
        inner.write_bytes(outer.read(name))
    executable = sevenzip_executable()
    assert executable is not None
    with sevenzip_lines(executable, inner) as lines:
        from_seven_zip = aggregate_disaggregated(lines)[0]
    assert from_seven_zip == aggregate_disaggregated(disaggregated_lines())[0]
    garbage = tmp_path / "garbage.zip"
    garbage.write_bytes(b"not a zip archive at all")
    with pytest.raises(RuntimeError, match="7-Zip failed"):
        with sevenzip_lines(executable, garbage) as lines:
            list(lines)


def test_the_header_columns_the_build_needs_are_the_real_ones():
    assert HEADER[0] == "countryCode" and "metadata_observationStatus" in HEADER and len(HEADER) == 28
    assert TOTAL_P[0] == "CAS_7723-14-0"
