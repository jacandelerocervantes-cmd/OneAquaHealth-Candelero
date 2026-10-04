"""Extraction stage of the samples build: keyset pages saved one file each in a work directory, resumable and checked.

An interrupted build resumes from the last valid page file; a damaged, foreign or out-of-sequence page file is discarded
with the later ones.
"""
from __future__ import annotations

import hashlib
import json
import os
import re
from collections.abc import Callable
from dataclasses import dataclass
from pathlib import Path
from typing import Any

from oah.bathing_samples.client import COUNT_QUERY_TEMPLATE, PAGE_QUERY_TEMPLATE, DiscodataClient
from oah.bathing_samples.constants import TABLE


WORK_FORMAT = 1


class ExtractionError(RuntimeError):
    """The extraction cannot be trusted (count mismatch, unusable rows) and no store is written."""


class IncompleteExtraction(ExtractionError):
    """``max_pages`` stopped the extraction before the end of the data; the work directory is kept so a run can resume."""


def template_digest() -> str:
    """Identifies the query texts a page file was made with; a file made with other texts is not reused."""
    return hashlib.sha256(json.dumps([PAGE_QUERY_TEMPLATE, COUNT_QUERY_TEMPLATE, TABLE], sort_keys=True).encode()).hexdigest()


def _page_path(work_dir: Path, prefix: str, seq: int) -> Path:
    return work_dir / f"{prefix}-{seq:05d}.json"


def _marker_path(work_dir: Path, prefix: str) -> Path:
    return work_dir / f"{prefix}-complete.json"


def _write_json_atomic(path: Path, payload: dict[str, Any]) -> None:
    temporary = path.with_name(path.name + ".tmp")
    temporary.write_text(json.dumps(payload, sort_keys=True, separators=(",", ":")), encoding="utf-8")
    os.replace(temporary, path)


def _read_json(path: Path) -> dict[str, Any] | None:
    try:
        data = json.loads(path.read_text(encoding="utf-8"))
    except (OSError, ValueError):
        return None
    return data if isinstance(data, dict) else None


@dataclass
class ResumeState:
    pages: int
    last_uid: int
    rows: int
    complete: bool


def load_resume(work_dir: Path, prefix: str) -> ResumeState:
    """What the work directory already holds for ``prefix``: the valid chain of page files from the first one.

    A page that is unreadable, of another format, prefix or query, out of sequence, or whose first UID does not follow the
    previous page is deleted with all later pages and the completion marker. Nothing is trusted from a broken file.
    """
    digest = template_digest()
    pages = rows = last_uid = 0
    seq = 1
    while _page_path(work_dir, prefix, seq).is_file():
        path = _page_path(work_dir, prefix, seq)
        data = _read_json(path)
        body = data.get("rows") if data else None
        valid = (
            data is not None and data.get("format") == WORK_FORMAT and data.get("prefix") == prefix
            and data.get("template_sha256") == digest and data.get("seq") == seq and data.get("after_uid") == last_uid
            and isinstance(body, list) and body and isinstance(data.get("last_uid"), int) and data["last_uid"] > last_uid
            and isinstance(body[-1], dict) and body[-1].get("UID") == data["last_uid"]
        )
        if not valid:
            _discard_from(work_dir, prefix, seq)
            return ResumeState(pages, last_uid, rows, False)
        assert data is not None and isinstance(body, list)
        pages, rows, last_uid, seq = pages + 1, rows + len(body), int(data["last_uid"]), seq + 1
    marker = _read_json(_marker_path(work_dir, prefix))
    complete = bool(
        marker and marker.get("format") == WORK_FORMAT and marker.get("template_sha256") == digest
        and marker.get("last_uid") == last_uid and marker.get("rows") == rows
    )
    if marker is not None and not complete:
        _marker_path(work_dir, prefix).unlink(missing_ok=True)
    return ResumeState(pages, last_uid, rows, complete)


def _discard_from(work_dir: Path, prefix: str, seq: int) -> None:
    while _page_path(work_dir, prefix, seq).exists():
        _page_path(work_dir, prefix, seq).unlink(missing_ok=True)
        seq += 1
    _marker_path(work_dir, prefix).unlink(missing_ok=True)


def clear_work_dir(work_dir: Path) -> None:
    """Remove the files this build creates in ``work_dir`` (never anything else)."""
    if not work_dir.is_dir():
        return
    for path in work_dir.iterdir():
        if re.fullmatch(r"[A-Z]{2}-(?:\d{5}|complete)\.json(?:\.tmp)?|raw\.sqlite(?:-journal)?", path.name):
            path.unlink(missing_ok=True)


@dataclass
class PrefixResult:
    prefix: str
    pages: int
    rows: int
    complete: bool
    source_count: int


Progress = Callable[[str], None]


def extract_prefix(
    client: DiscodataClient, work_dir: Path, prefix: str, page_size: int, max_pages: int | None, progress: Progress
) -> PrefixResult:
    """Download the pages of one prefix into ``work_dir`` (resuming), then record completion when the data ended."""
    work_dir.mkdir(parents=True, exist_ok=True)
    state = load_resume(work_dir, prefix)
    source_count = client.count(prefix)
    progress(f"{prefix}: the service holds {source_count} rows; {state.pages} saved page(s) ({state.rows} rows) found")
    if not state.complete:
        digest = template_digest()
        fetched = 0
        for rows in client.iter_pages(prefix, page_size, after_uid=state.last_uid, max_pages=max_pages):
            seq = state.pages + 1
            last_uid = int(rows[-1]["UID"])
            _write_json_atomic(
                _page_path(work_dir, prefix, seq),
                {
                    "format": WORK_FORMAT, "prefix": prefix, "template_sha256": digest, "seq": seq,
                    "after_uid": state.last_uid, "last_uid": last_uid, "rows": rows,
                },
            )
            state = ResumeState(seq, last_uid, state.rows + len(rows), False)
            fetched += 1
            progress(f"{prefix}: page {seq} saved ({len(rows)} rows, {state.rows} so far)")
        if client.reached_end:
            _write_json_atomic(
                _marker_path(work_dir, prefix),
                {"format": WORK_FORMAT, "template_sha256": digest, "last_uid": state.last_uid, "rows": state.rows, "source_count": source_count},
            )
            state.complete = True
    return PrefixResult(prefix, state.pages, state.rows, state.complete, source_count)
