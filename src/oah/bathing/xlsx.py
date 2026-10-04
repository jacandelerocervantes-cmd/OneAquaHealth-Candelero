"""Streaming reader for ``.xlsx`` sheets with the standard library only (``zipfile`` + ``xml.etree`` ``iterparse``).

An xlsx file is a ZIP of XML parts. The bathing-water sheet is about 291 MB of XML, so it is never loaded whole: the
shared strings (a few MB) are read into a list, then the sheet is parsed event by event and each row is handed to the
caller and dropped (``sheetData`` is cleared after every row, so memory stays flat whatever the row count).

Supported cell kinds: shared strings (``t="s"``), inline strings (``t="inlineStr"``), formula strings (``t="str"``),
booleans, numbers (an integer-looking number is returned as ``int``, otherwise ``float``). Blank cells are omitted from
the XML; a row is returned as ``{column index (0 based): value}`` so missing cells are simply absent. Error cells
(``t="e"``) are returned as None. No third-party dependency, no network.
"""

from __future__ import annotations

import re
import tempfile
import zipfile
from collections.abc import Iterator
from contextlib import contextmanager
from pathlib import Path
from typing import IO, Any
from xml.etree.ElementTree import Element, iterparse

MAX_SHEET_BYTES = 2 * 1024**3  # uncompressed size of a sheet part this reader accepts (the real one is about 0.3 GB)
MAX_SHARED_STRINGS = 5_000_000
_RELATIONSHIPS = "{http://schemas.openxmlformats.org/officeDocument/2006/relationships}id"
_INTEGER = re.compile(r"^-?\d+$")
_COLUMN = re.compile(r"^([A-Za-z]+)")


class XlsxError(RuntimeError):
    """The file is not a workbook this reader can use (missing sheet, unreadable part, oversized part)."""


_LOCAL_NAMES: dict[str, str] = {}


def _local(tag: str) -> str:
    name = _LOCAL_NAMES.get(tag)
    if name is None:
        name = tag.rsplit("}", 1)[-1]
        if len(_LOCAL_NAMES) < 1000:  # a handful of distinct tags in a real workbook; bounded against a hostile one
            _LOCAL_NAMES[tag] = name
    return name


def column_index(reference: str) -> int | None:
    """``A1`` -> 0, ``B7`` -> 1, ``AA3`` -> 26; None when the reference has no column letters."""
    match = _COLUMN.match(reference)
    if match is None:
        return None
    index = 0
    for letter in match.group(1).upper():
        index = index * 26 + (ord(letter) - 64)
    return index - 1


def _text(element: Element) -> str:
    """The text of an ``si`` or ``is`` element: every ``t`` child and every rich-text run, but not phonetic hints."""
    parts: list[str] = []
    for child in element:
        name = _local(child.tag)
        if name == "t":
            parts.append(child.text or "")
        elif name == "r":
            parts.extend((t.text or "") for t in child if _local(t.tag) == "t")
    return "".join(parts)


def read_shared_strings(archive: zipfile.ZipFile) -> list[str]:
    """The shared string table (empty when the workbook has none)."""
    if "xl/sharedStrings.xml" not in archive.namelist():
        return []
    strings: list[str] = []
    with archive.open("xl/sharedStrings.xml") as stream:
        for _event, element in iterparse(stream, events=("end",)):
            if _local(element.tag) == "si":
                strings.append(_text(element))
                element.clear()
                if len(strings) > MAX_SHARED_STRINGS:
                    raise XlsxError("The shared string table is too large for this reader.")
    return strings


def sheet_part(archive: zipfile.ZipFile, sheet_name: str) -> str:
    """The archive path of the worksheet called ``sheet_name`` (through ``workbook.xml`` and its relationships)."""
    names = archive.namelist()
    if "xl/workbook.xml" not in names or "xl/_rels/workbook.xml.rels" not in names:
        raise XlsxError("The file has no workbook part; it is not an xlsx workbook.")
    relationship: str | None = None
    with archive.open("xl/workbook.xml") as stream:
        for _event, element in iterparse(stream, events=("end",)):
            if _local(element.tag) == "sheet" and element.get("name") == sheet_name:
                relationship = element.get(_RELATIONSHIPS)
                break
    if relationship is None:
        raise XlsxError(f"The workbook has no sheet named {sheet_name!r}.")
    target: str | None = None
    with archive.open("xl/_rels/workbook.xml.rels") as stream:
        for _event, element in iterparse(stream, events=("end",)):
            if _local(element.tag) == "Relationship" and element.get("Id") == relationship:
                target = element.get("Target")
                break
    if not target:
        raise XlsxError(f"The workbook has no relationship target for sheet {sheet_name!r}.")
    path = target.lstrip("/") if target.startswith("/") else f"xl/{target}"
    if path not in names:
        raise XlsxError(f"The sheet part {path!r} is missing from the file.")
    return path


def _number(text: str) -> int | float | None:
    if _INTEGER.match(text):
        return int(text)
    try:
        return float(text)
    except ValueError:
        return None


def _cell_value(cell: Element, strings: list[str]) -> Any:
    kind = cell.get("t")
    if kind == "inlineStr":
        for child in cell:
            if _local(child.tag) == "is":
                return _text(child) or None
        return None
    raw: str | None = None
    for child in cell:
        if _local(child.tag) == "v":
            raw = child.text
            break
    if raw is None or raw == "":
        return None
    if kind == "s":
        try:
            return strings[int(raw)] or None
        except (ValueError, IndexError):
            return None
    if kind in ("str", "d"):
        return raw
    if kind == "b":
        return raw.strip() == "1"
    if kind == "e":
        return None
    return _number(raw.strip())


def iter_sheet_rows(
    archive: zipfile.ZipFile, sheet_name: str, strings: list[str] | None = None
) -> Iterator[tuple[int, dict[int, Any]]]:
    """Yield ``(row number, {column index: value})`` for every row of the sheet, one at a time.

    Rows without any value are skipped. Memory use does not depend on the size of the sheet.
    """
    part = sheet_part(archive, sheet_name)
    if archive.getinfo(part).file_size > MAX_SHEET_BYTES:
        raise XlsxError("The sheet is larger than this reader accepts.")
    table = read_shared_strings(archive) if strings is None else strings
    sheet_data: Element | None = None
    with archive.open(part) as stream:
        row_number = 0
        for event, element in iterparse(stream, events=("start", "end")):
            name = _local(element.tag)
            if event == "start":
                if name == "sheetData":
                    sheet_data = element
                continue
            if name != "row":
                continue
            row_number = int(element.get("r") or row_number + 1)
            values: dict[int, Any] = {}
            for position, cell in enumerate(element):
                if _local(cell.tag) != "c":
                    continue
                index = column_index(cell.get("r") or "")
                value = _cell_value(cell, table)
                if value is not None:
                    values[position if index is None else index] = value
            if sheet_data is not None:
                sheet_data.clear()  # drop the finished rows; the parser keeps appending to the same element
            if values:
                yield row_number, values


@contextmanager
def open_workbook_in_archive(archive_path: Path, member_suffix: str, work_dir: Path) -> Iterator[zipfile.ZipFile]:
    """Open the ``.xlsx`` member of an outer ZIP as a ZIP, without reading it whole.

    A STORED member (the real archive) is opened in place; a compressed one is first copied to a scratch file under
    ``work_dir`` (removed afterwards), because ``zipfile`` needs a seekable file.
    """
    with zipfile.ZipFile(archive_path) as outer:
        matches = [info for info in outer.infolist() if info.filename.lower().endswith(member_suffix.lower())]
        if len(matches) != 1:
            raise XlsxError(f"Expected exactly one {member_suffix} in the archive, found {len(matches)}.")
        info = matches[0]
        if info.compress_type == zipfile.ZIP_STORED:
            with outer.open(info) as member, zipfile.ZipFile(member) as workbook:
                yield workbook
            return
        work_dir.mkdir(parents=True, exist_ok=True)
        scratch: IO[bytes]
        with tempfile.TemporaryFile(dir=work_dir) as scratch:
            with outer.open(info) as member:
                while chunk := member.read(1 << 20):
                    scratch.write(chunk)
            scratch.seek(0)
            with zipfile.ZipFile(scratch) as workbook:
                yield workbook
