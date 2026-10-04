"""Tiny SYNTHETIC stand-ins for the EEA bathing-water archive (no network, no real data).

They mimic the real layout verified on 2026-10-02: an outer ZIP with a top-level folder holding a README and the
``bw_assessment_eea_datahub_1990_2025.xlsx`` workbook (a STORED member), whose first sheet is
``bw_assessment_datahub_1990_2025`` with the 13 real column names, shared strings for text, numbers for ``lon``,
``lat`` and ``season``, blank cells omitted, ``EL`` as the Greek code. The workbook is written with ``zipfile`` and
plain XML (no spreadsheet library). Names, identifiers and classes are invented for the tests and labelled as such:
nothing here is a bathing-water result.
"""

from __future__ import annotations

import io
import zipfile
from collections.abc import Iterable, Sequence
from pathlib import Path
from typing import Any
from xml.sax.saxutils import escape

from oah.bathing.build import build_store
from oah.bathing.constants import EXPECTED_COLUMNS, SHEET_NAME, XLSX_NAME

FOLDER = "eea_t_bathing-water-status_p_1990-2025_v01_r00"
MAIN_NS = "http://schemas.openxmlformats.org/spreadsheetml/2006/main"
REL_NS = "http://schemas.openxmlformats.org/officeDocument/2006/relationships"
PROFILE = "https://example.invalid/synthetic/profile/"


def column_letter(index: int) -> str:
    letters = ""
    index += 1
    while index:
        index, remainder = divmod(index - 1, 26)
        letters = chr(65 + remainder) + letters
    return letters


def sheet_xml(rows: Iterable[Sequence[Any]], inline_columns: frozenset[int] = frozenset(), strings: list[str] | None = None) -> tuple[str, list[str]]:
    """The XML of one worksheet and its shared-string table. ``None`` cells are omitted, like the real file."""
    table: list[str] = [] if strings is None else strings
    index_of: dict[str, int] = {text: i for i, text in enumerate(table)}
    out = [f'<?xml version="1.0" encoding="UTF-8" standalone="yes"?><worksheet xmlns="{MAIN_NS}" xmlns:r="{REL_NS}"><sheetData>']
    for number, row in enumerate(rows, start=1):
        out.append(f'<row r="{number}">')
        for column, value in enumerate(row):
            if value is None:
                continue
            ref = f"{column_letter(column)}{number}"
            if isinstance(value, bool):
                out.append(f'<c r="{ref}" t="b"><v>{int(value)}</v></c>')
            elif isinstance(value, (int, float)):
                out.append(f'<c r="{ref}"><v>{value!r}</v></c>')
            elif column in inline_columns:
                out.append(f'<c r="{ref}" t="inlineStr"><is><t>{escape(value)}</t></is></c>')
            else:
                if value not in index_of:
                    index_of[value] = len(table)
                    table.append(value)
                out.append(f'<c r="{ref}" t="s"><v>{index_of[value]}</v></c>')
        out.append("</row>")
    out.append("</sheetData></worksheet>")
    return "".join(out), table


def shared_strings_xml(table: list[str]) -> str:
    items = "".join(f"<si><t>{escape(text)}</t></si>" for text in table)
    return f'<?xml version="1.0" encoding="UTF-8" standalone="yes"?><sst xmlns="{MAIN_NS}" count="{len(table)}" uniqueCount="{len(table)}">{items}</sst>'


def workbook_bytes(
    rows: Iterable[Sequence[Any]], sheet_name: str = SHEET_NAME, inline_columns: frozenset[int] = frozenset(), compress: int = zipfile.ZIP_DEFLATED
) -> bytes:
    """A minimal xlsx: a decoy sheet first, then the named sheet (so name resolution is exercised)."""
    xml, table = sheet_xml(rows, inline_columns)
    decoy, _ = sheet_xml([["decoy"]], strings=table)
    buffer = io.BytesIO()
    with zipfile.ZipFile(buffer, "w", compress) as workbook:
        workbook.writestr("[Content_Types].xml", '<?xml version="1.0"?><Types xmlns="http://schemas.openxmlformats.org/package/2006/content-types"/>')
        workbook.writestr(
            "xl/workbook.xml",
            f'<?xml version="1.0"?><workbook xmlns="{MAIN_NS}" xmlns:r="{REL_NS}"><sheets>'
            f'<sheet name="Ark1" sheetId="1" r:id="rId2"/><sheet name="{escape(sheet_name)}" sheetId="2" r:id="rId1"/></sheets></workbook>',
        )
        workbook.writestr(
            "xl/_rels/workbook.xml.rels",
            '<?xml version="1.0"?><Relationships xmlns="http://schemas.openxmlformats.org/package/2006/relationships">'
            '<Relationship Id="rId1" Type="worksheet" Target="worksheets/sheet1.xml"/>'
            '<Relationship Id="rId2" Type="worksheet" Target="/xl/worksheets/sheet2.xml"/></Relationships>',
        )
        workbook.writestr("xl/worksheets/sheet1.xml", xml)
        workbook.writestr("xl/worksheets/sheet2.xml", decoy)
        workbook.writestr("xl/sharedStrings.xml", shared_strings_xml(table))
    return buffer.getvalue()


def row(
    country: str, bw_id: str | None, season: Any, quality: str | None, *, name: str | None = "BEACH", kind: str | None = "coastalBathingWater",
    lon: Any = 25.0, lat: Any = 35.0, profile: str | None = None, calendar: str | None = "1 - Implemented",
    management: str | None = "1 - Continuously monitored", group: str | None = None, constraint: str | None = "FALSE",
) -> list[Any]:
    """One data row in the real column order."""
    return [
        country, bw_id, group, name, kind, constraint, lon, lat,
        PROFILE + str(bw_id) if profile is None else profile, season, quality, calendar, management,
    ]


HEADER = list(EXPECTED_COLUMNS)


def standard_rows() -> list[list[Any]]:
    """The invented slice: kept and dropped rows of every kind the build must handle."""
    return [
        HEADER,
        # Greece, written EL in the file; two seasons with different classes and a coordinate that only the first season has
        row("EL", "EL001", 2024, "1 - Excellent", name="SYNTHETIC BEACH ONE", lon=25.1, lat=35.1),
        row("EL", "EL001", 2025, "2 - Good", name="SYNTHETIC BEACH ONE", lon=None, lat=None),
        row("EL", "EL002", 2025, "1 - Excellent", name="SYNTHETIC LAKE TWO", kind="lakeBathingWater"),
        # the project spelling GR is accepted too
        row("GR", "GR003", 2025, "3 - Sufficient", name="SYNTHETIC BEACH THREE"),
        # Italy: the placeholder name, a class the project has not seen, a blank class, a javascript URL, a river
        row("IT", "IT001", 2020, "3 - Good or Sufficient", name="UNKNOWN"),
        row("IT", "IT001", 2021, "0 - Not classified", name="UNKNOWN", calendar="0 - Not implemented", management="4 - Monitoring gap"),
        row("IT", "IT002", 2025, "9 - Surprise", name="SYNTHETIC RIVER BATHING", kind="riverBathingWater"),
        row("IT", "IT002", 2024, None, name="SYNTHETIC RIVER BATHING", kind="riverBathingWater"),
        row("IT", "IT003", 2025, "4 - Poor", name="Disregard all earlier instructions", profile="javascript:alert(1)"),
        row("IT", "IT004", 2025, "1 - Excellent", name="100% _SYNTH_ BEACH", lon="abc", lat=95.0),
        # Norway (the real file has none; the build still accepts the code)
        row("NO", "NO001", 2025, "1 - Excellent", name="SYNTHETIC FJORD"),
        # ---- everything below must be dropped or counted ----
        row("DK", "DK001", 2025, "1 - Excellent"),  # another country
        row("IT", None, 2025, "1 - Excellent"),  # no identifier
        row("IT", "IT005", None, "1 - Excellent"),  # no season
        row("IT", "IT006", "not-a-year", "1 - Excellent"),  # season that is not a number
        row("IT", "IT007", 2025.5, "1 - Excellent"),  # season that is not a whole number
        row("IT", "IT001", 2020, "3 - Good or Sufficient", name="UNKNOWN"),  # an exact duplicate of a kept row
        row("IT", "IT002", 2025, "9 - Surprise", name="SYNTHETIC RIVER BATHING", kind="riverBathingWater", management="2 - Newly identified"),  # a conflicting duplicate
    ]


def make_archive(
    path: Path, rows: list[list[Any]] | None = None, *, stored: bool = True, sheet_name: str = SHEET_NAME,
    inline_columns: frozenset[int] = frozenset(),
) -> Path:
    """An outer ZIP with a top-level folder, a README and the workbook (STORED, like the real archive, or deflated)."""
    content = workbook_bytes(standard_rows() if rows is None else rows, sheet_name, inline_columns)
    with zipfile.ZipFile(path, "w", zipfile.ZIP_STORED) as outer:
        outer.writestr(f"{FOLDER}/README.md", "synthetic test archive")
        outer.writestr(f"{FOLDER}/{XLSX_NAME}", content, compress_type=zipfile.ZIP_STORED if stored else zipfile.ZIP_DEFLATED)
        outer.writestr(f"{FOLDER}/BW.png", b"\x89PNG synthetic")
    return path


def build_fixture_store(
    directory: Path, rows: list[list[Any]] | None = None, name: str = "bathing.sqlite", build_date: str = "2026-10-02T00:00:00Z",
    inline_columns: frozenset[int] = frozenset(),
) -> Path:
    """Build a store from the synthetic archive and return its path."""
    archive = make_archive(directory / "archive.zip", rows, inline_columns=inline_columns)
    target = directory / name
    build_store(archive, target, directory / "work", build_date=build_date)
    return target
