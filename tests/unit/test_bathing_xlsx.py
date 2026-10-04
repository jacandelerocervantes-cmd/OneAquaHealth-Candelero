"""The standard-library xlsx reader: cell kinds, sheet lookup, streaming. Workbooks are SYNTHETIC (built in the test)."""

from __future__ import annotations

import io
import tracemalloc
import zipfile
from pathlib import Path

import pytest
from bathing_fixtures import MAIN_NS, REL_NS, column_letter, make_archive, sheet_xml, shared_strings_xml, workbook_bytes

from oah.bathing import xlsx
from oah.bathing.xlsx import XlsxError, column_index, iter_sheet_rows, open_workbook_in_archive, read_shared_strings, sheet_part


def _workbook(rows, **kwargs) -> zipfile.ZipFile:
    return zipfile.ZipFile(io.BytesIO(workbook_bytes(rows, **kwargs)))


def test_column_references_become_zero_based_indexes():
    assert [column_index(ref) for ref in ("A1", "B7", "Z2", "AA3", "AB10", "m5")] == [0, 1, 25, 26, 27, 12]
    assert column_index("12") is None and column_index("") is None
    assert [column_letter(i) for i in (0, 25, 26, 27, 701, 702)] == ["A", "Z", "AA", "AB", "ZZ", "AAA"]


def test_rows_come_back_with_their_columns_and_blank_cells_are_absent():
    rows = [["h1", "h2", "h3", "h4"], ["a", None, 3, 4.5], [None, None, None, None], ["x", "y", None, True]]
    with _workbook(rows, sheet_name="data") as workbook:
        read = list(iter_sheet_rows(workbook, "data"))
    assert read == [(1, {0: "h1", 1: "h2", 2: "h3", 3: "h4"}), (2, {0: "a", 2: 3, 3: 4.5}), (4, {0: "x", 1: "y", 3: True})]
    assert isinstance(read[1][1][2], int) and isinstance(read[1][1][3], float)  # an integer-looking number is an int


def test_inline_strings_shared_strings_and_escaped_text_are_read():
    rows = [["plain", "A & B <c>", "ünïcode — dash"], ["x", "y", "z"]]
    with _workbook(rows, sheet_name="data", inline_columns=frozenset({1})) as workbook:
        assert next(iter_sheet_rows(workbook, "data"))[1] == {0: "plain", 1: "A & B <c>", 2: "ünïcode — dash"}
        assert read_shared_strings(workbook)[0] == "plain"
        assert "A & B <c>" not in read_shared_strings(workbook)  # that column was written inline


def test_rich_text_runs_are_joined_and_phonetic_hints_are_ignored():
    sst = (
        f'<sst xmlns="{MAIN_NS}"><si><r><t>Rich </t></r><r><t>text</t></r></si>'
        '<si><t>base</t><rPh><t>PHONETIC</t></rPh></si></sst>'
    )
    buffer = io.BytesIO()
    with zipfile.ZipFile(buffer, "w") as workbook:
        workbook.writestr("xl/sharedStrings.xml", sst)
    with zipfile.ZipFile(buffer) as workbook:
        assert read_shared_strings(workbook) == ["Rich text", "base"]


def test_a_workbook_without_shared_strings_reads_as_an_empty_table():
    buffer = io.BytesIO()
    with zipfile.ZipFile(buffer, "w") as workbook:
        workbook.writestr("xl/other.xml", "<a/>")
    with zipfile.ZipFile(buffer) as workbook:
        assert read_shared_strings(workbook) == []


def test_the_sheet_is_found_by_name_through_the_workbook_relationships():
    with _workbook([["only"]], sheet_name="target") as workbook:
        assert sheet_part(workbook, "target") == "xl/worksheets/sheet1.xml"
        assert sheet_part(workbook, "Ark1") == "xl/worksheets/sheet2.xml"  # an absolute relationship target
        with pytest.raises(XlsxError, match="no sheet named"):
            sheet_part(workbook, "absent")


def test_a_file_that_is_not_a_workbook_is_refused():
    buffer = io.BytesIO()
    with zipfile.ZipFile(buffer, "w") as workbook:
        workbook.writestr("readme.txt", "no workbook here")
    with zipfile.ZipFile(buffer) as workbook, pytest.raises(XlsxError, match="not an xlsx"):
        sheet_part(workbook, "x")


def test_a_relationship_that_points_nowhere_is_a_clear_error():
    buffer = io.BytesIO()
    with zipfile.ZipFile(buffer, "w") as workbook:
        workbook.writestr(
            "xl/workbook.xml", f'<workbook xmlns="{MAIN_NS}" xmlns:r="{REL_NS}"><sheets><sheet name="s" r:id="rId9"/></sheets></workbook>'
        )
        workbook.writestr("xl/_rels/workbook.xml.rels", '<Relationships xmlns="x"><Relationship Id="rId1" Target="a.xml"/></Relationships>')
    with zipfile.ZipFile(buffer) as workbook, pytest.raises(XlsxError, match="no relationship target"):
        sheet_part(workbook, "s")
    buffer = io.BytesIO()
    with zipfile.ZipFile(buffer, "w") as workbook:
        workbook.writestr(
            "xl/workbook.xml", f'<workbook xmlns="{MAIN_NS}" xmlns:r="{REL_NS}"><sheets><sheet name="s" r:id="rId1"/></sheets></workbook>'
        )
        workbook.writestr("xl/_rels/workbook.xml.rels", '<Relationships xmlns="x"><Relationship Id="rId1" Target="worksheets/gone.xml"/></Relationships>')
    with zipfile.ZipFile(buffer) as workbook, pytest.raises(XlsxError, match="missing from the file"):
        sheet_part(workbook, "s")


def test_odd_cells_do_not_break_the_reader():
    table = ["zero"]
    xml = (
        f'<worksheet xmlns="{MAIN_NS}"><sheetData><row r="3">'
        '<c r="A3" t="s"><v>99</v></c><c r="B3" t="s"><v>x</v></c><c r="C3" t="e"><v>#DIV/0!</v></c>'
        '<c r="D3" t="str"><v>formula text</v></c><c r="E3"><v>not-a-number</v></c><c r="F3"><v></v></c>'
        '<c r="G3" t="b"><v>0</v></c><c r="H3" t="inlineStr"><is></is></c><c t="s"><v>0</v></c>'
        "</row></sheetData></worksheet>"
    )
    buffer = io.BytesIO()
    with zipfile.ZipFile(buffer, "w") as workbook:
        workbook.writestr(
            "xl/workbook.xml", f'<workbook xmlns="{MAIN_NS}" xmlns:r="{REL_NS}"><sheets><sheet name="s" r:id="rId1"/></sheets></workbook>'
        )
        workbook.writestr("xl/_rels/workbook.xml.rels", '<Relationships xmlns="x"><Relationship Id="rId1" Target="worksheets/s.xml"/></Relationships>')
        workbook.writestr("xl/worksheets/s.xml", xml)
        workbook.writestr("xl/sharedStrings.xml", shared_strings_xml(table))
    with zipfile.ZipFile(buffer) as workbook:
        rows = list(iter_sheet_rows(workbook, "s"))
    # out-of-range or non-numeric shared string index, error cell, empty cells: None (absent); the unreferenced cell keeps its position
    assert rows == [(3, {3: "formula text", 6: False, 8: "zero"})]


def test_an_oversized_sheet_is_refused(monkeypatch):
    monkeypatch.setattr(xlsx, "MAX_SHEET_BYTES", 10)
    with _workbook([["a", "b"], ["c", "d"]], sheet_name="data") as workbook, pytest.raises(XlsxError, match="larger"):
        list(iter_sheet_rows(workbook, "data"))


def test_a_huge_shared_string_table_is_refused(monkeypatch):
    monkeypatch.setattr(xlsx, "MAX_SHARED_STRINGS", 3)
    with _workbook([[f"v{i}" for i in range(10)]], sheet_name="data") as workbook, pytest.raises(XlsxError, match="too large"):
        read_shared_strings(workbook)


def test_a_large_sheet_is_streamed_not_loaded_whole():
    """~12 MB of sheet XML is read with a small, flat memory peak: each finished row is dropped as the parser goes."""
    rows = [[f"row-{i}", f"name {i % 50}", float(i) + 0.25, i, "coastalBathingWater", "1 - Excellent"] for i in range(60_000)]
    xml, table = sheet_xml(rows)
    assert len(xml) > 8_000_000
    buffer = io.BytesIO()
    with zipfile.ZipFile(buffer, "w", zipfile.ZIP_DEFLATED) as workbook:
        workbook.writestr(
            "xl/workbook.xml", f'<workbook xmlns="{MAIN_NS}" xmlns:r="{REL_NS}"><sheets><sheet name="big" r:id="rId1"/></sheets></workbook>'
        )
        workbook.writestr("xl/_rels/workbook.xml.rels", '<Relationships xmlns="x"><Relationship Id="rId1" Target="worksheets/big.xml"/></Relationships>')
        workbook.writestr("xl/worksheets/big.xml", xml)
        workbook.writestr("xl/sharedStrings.xml", shared_strings_xml(table))
    del xml, rows
    with zipfile.ZipFile(buffer) as workbook:
        strings = read_shared_strings(workbook)
        count = 0
        last = {}
        tracemalloc.start()
        try:
            for number, cells in iter_sheet_rows(workbook, "big", strings):
                count += 1
                last = cells
            _current, peak = tracemalloc.get_traced_memory()
        finally:
            tracemalloc.stop()
    assert count == 60_000 and last[0] == "row-59999" and last[3] == 59_999
    assert peak < 2_000_000, f"peak {peak} bytes: the sheet is being accumulated instead of streamed"


def test_the_workbook_member_of_a_stored_archive_is_opened_in_place(tmp_path: Path):
    archive = make_archive(tmp_path / "a.zip")
    with open_workbook_in_archive(archive, ".xlsx", tmp_path / "work") as workbook:
        assert sheet_part(workbook, "bw_assessment_datahub_1990_2025").endswith("sheet1.xml")
    assert not (tmp_path / "work").exists()  # no scratch copy was needed


def test_a_compressed_member_is_copied_to_scratch_space_and_cleaned_up(tmp_path: Path):
    archive = make_archive(tmp_path / "a.zip", stored=False)
    work = tmp_path / "work"
    with open_workbook_in_archive(archive, ".xlsx", work) as workbook:
        assert next(iter_sheet_rows(workbook, "bw_assessment_datahub_1990_2025"))[0] == 1
    assert list(work.iterdir()) == []


def test_zero_or_two_workbooks_in_the_archive_is_an_error(tmp_path: Path):
    empty = tmp_path / "none.zip"
    with zipfile.ZipFile(empty, "w") as archive:
        archive.writestr("README.md", "x")
    with pytest.raises(XlsxError, match="exactly one"), open_workbook_in_archive(empty, ".xlsx", tmp_path / "w"):
        pass
    two = tmp_path / "two.zip"
    with zipfile.ZipFile(two, "w") as archive:
        archive.writestr("a.xlsx", b"x")
        archive.writestr("b.xlsx", b"x")
    with pytest.raises(XlsxError, match="exactly one"), open_workbook_in_archive(two, ".xlsx", tmp_path / "w"):
        pass
