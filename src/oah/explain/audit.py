"""Append-only audit trail of every request sent to the external LLM provider.

What was sent to a third party must be reconstructible, but the trail itself must not leak: a record holds the event
name, the model, token counts, counts, flags and SHA-256 DIGESTS (and character counts) of the evidence, the question,
the tool results and the answer. It never holds user text (no question, no excerpt of it), model text, evidence, a client
address or a key. A call whose dispatch cannot be recorded is not sent (the caller lets the OSError propagate), so a
missing or unwritable log closes the path instead of hiding it.

Two copies of each record exist, both digest-only:

* the hash-chained JSONL file under the data directory (``oah.paths.llm_audit_path``): tamper-evident (``verify_all``),
  rotated by size, with at most ``MAX_ROTATED_FILES`` rotated files kept (the oldest is deleted first). On a platform
  whose file system is in memory (Cloud Run) this file is lost when the instance restarts;
* one structured JSON line per record on stdout (``emit_to_stdout``), which a log collector keeps (Cloud Logging reads a
  JSON line with a ``severity`` and a ``message``). This is the durable copy; it is not chained.
"""
from __future__ import annotations

import hashlib
import json
import sys
import threading
from collections.abc import Mapping
from datetime import timezone
from pathlib import Path
from typing import Any

from oah.paths import llm_audit_path
from oah.timeutil import format_utc, utc_now

_LOCK = threading.Lock()


def evidence_digest(evidence: Mapping[str, Any]) -> str:
    """Stable SHA-256 of the evidence, independent of key order."""
    canonical = json.dumps(evidence, sort_keys=True, default=str, ensure_ascii=False)
    return hashlib.sha256(canonical.encode("utf-8")).hexdigest()


# Event names of the chat agent (oah.chat), appended to the same chain as the explanation events
# ("dispatch", "result", "error", "cache-hit"). Fields are digests, counts and flags, never full text.
CHAT_EVENTS = frozenset(
    {
        "chat-dispatch", "chat-model-call", "chat-tool-call", "chat-tool-result", "chat-error", "chat-result", "chat-cache-hit",
        "chat-revision",
    }
)


def text_digest(text: str) -> str:
    return hashlib.sha256(text.encode("utf-8")).hexdigest()


MAX_LOG_BYTES = 5 * 1024 * 1024  # rotate the log when it grows past this size
# Rotated files kept on disk next to the current one (oldest removed first). The disk may be memory (Cloud Run), so the
# bound is small: at most MAX_ROTATED_FILES * MAX_LOG_BYTES (about 20 MiB) plus the current file. The stdout copy is the durable one.
MAX_ROTATED_FILES = 4
STDOUT_MESSAGE = "oah-llm-audit"


def _canonical(line: Mapping[str, Any]) -> str:
    return json.dumps(line, sort_keys=True, ensure_ascii=False)


def _chain_hash(previous: str, line: Mapping[str, Any]) -> str:
    """SHA-256 over the previous hash and the record content (without its own hash)."""
    body = {key: value for key, value in line.items() if key != "hash"}
    return hashlib.sha256((previous + "|" + _canonical(body)).encode("utf-8")).hexdigest()


def _last_hash(path: Path) -> str:
    """Hash of the last chained record of ``path`` (empty when the file is missing, empty or unchained)."""
    if not path.is_file() or path.stat().st_size == 0:
        return ""
    with path.open("rb") as handle:
        handle.seek(max(0, path.stat().st_size - 16384))
        tail = handle.read().decode("utf-8", errors="replace").splitlines()
    for text in reversed(tail):
        try:
            value = json.loads(text)
        except json.JSONDecodeError:
            continue
        if isinstance(value, dict) and isinstance(value.get("hash"), str):
            return value["hash"]
    return ""


def rotated_files(path: Path) -> list[Path]:
    """The rotated files next to ``path``, oldest first (the stamp in the name sorts chronologically)."""
    return sorted(path.parent.glob(f"{path.stem}.*{path.suffix}"))


def _next_rotated_path(path: Path) -> Path:
    """Name for the file about to be rotated: it always sorts AFTER every rotated file that exists.

    The name is ``<stem>.<UTC stamp>-<sequence><suffix>`` with a fixed-width stamp. Several rotations can share one clock
    tick (the Windows clock advances in steps of about 15 ms), so the sequence is the successor of the newest existing
    name with the same stamp, never the first free number: after the oldest file of a tick was pruned, "first free"
    would give the NEWEST file the smallest sequence, so it would sort first and be pruned or verified out of order. A clock
    that moved backwards keeps the stamp of the newest file for the same reason.
    """
    now = utc_now().astimezone(timezone.utc)
    stamp = now.strftime("%Y%m%dT%H%M%S%f") + "Z"
    sequence = 0
    existing = rotated_files(path)
    if existing:
        newest_stem = existing[-1].name[len(path.stem) + 1 : len(existing[-1].name) - len(path.suffix)]
        newest_stamp, _, newest_sequence = newest_stem.rpartition("-")
        if newest_stamp >= stamp and newest_sequence.isdigit():
            stamp, sequence = newest_stamp, int(newest_sequence) + 1
    candidate = path.with_name(f"{path.stem}.{stamp}-{sequence:06d}{path.suffix}")
    while candidate.exists():  # never overwrite, whatever the names on disk look like
        sequence += 1
        candidate = path.with_name(f"{path.stem}.{stamp}-{sequence:06d}{path.suffix}")
    return candidate


def _prune_rotated(path: Path) -> None:
    """Delete the oldest rotated files beyond ``MAX_ROTATED_FILES``. A failure to delete never blocks the audit write."""
    excess = rotated_files(path)[: max(0, len(rotated_files(path)) - max(0, MAX_ROTATED_FILES))]
    for old in excess:
        try:
            old.unlink()
        except OSError:
            continue


def emit_to_stdout(line: Mapping[str, Any]) -> None:
    """Write one structured JSON line (digest-only content, never user text or a key) to stdout for the log collector.

    ``severity`` and ``message`` are the fields Cloud Logging recognises; the record itself is under ``audit``. A closed or
    broken stdout never stops the audit write, which is the rule that matters.
    """
    payload = {"severity": "INFO", "message": STDOUT_MESSAGE, "audit": dict(line)}
    try:
        sys.stdout.write(json.dumps(payload, sort_keys=True, ensure_ascii=True, default=str) + "\n")
        sys.stdout.flush()
    except (OSError, ValueError):
        return


def record(event: str, **fields: Any) -> None:
    """Append one hash-chained JSON line to the LLM audit log; raises OSError if it cannot be written.

    Each record stores ``prev_hash`` and its own ``hash``, so an edited, reordered or removed record that is
    followed by a later one is detectable (``verify_chain``). The log rotates by size; the first record of the
    new file carries the last hash of the rotated one, so the chain continues across files, and only the newest
    ``MAX_ROTATED_FILES`` rotated files are kept. The chain cannot detect removal of the newest records (no external
    anchor). After the file write the same record is emitted as one JSON line on stdout (``emit_to_stdout``).
    """
    line: dict[str, Any] = {"timestamp": format_utc(utc_now()), "event": event, **fields}
    path = llm_audit_path()
    with _LOCK:
        path.parent.mkdir(parents=True, exist_ok=True)
        previous = _last_hash(path)
        if path.is_file() and path.stat().st_size >= MAX_LOG_BYTES:
            path.replace(_next_rotated_path(path))
            _prune_rotated(path)
        line["prev_hash"] = previous
        line["hash"] = _chain_hash(previous, line)
        with path.open("a", encoding="utf-8") as handle:
            handle.write(_canonical(line) + "\n")
    emit_to_stdout(line)


def _first_chained_prev_hash(path: Path) -> str:
    """The ``prev_hash`` of the first chained record of ``path`` (empty when there is none or it is unreadable)."""
    try:
        for text in path.read_text(encoding="utf-8").splitlines():
            try:
                value = json.loads(text)
            except json.JSONDecodeError:
                return ""
            if isinstance(value, dict) and "hash" in value:
                return str(value.get("prev_hash") or "")
    except OSError:
        return ""
    return ""


def verify_chain(path: Path, anchor: str = "") -> tuple[bool, int, int | None]:
    """Recompute the chain of one log file: ``(ok, records_checked, first_bad_line_number)``.

    ``anchor`` is the last hash of the previous (rotated) file, or empty for the first file. Lines written
    before the chain existed carry no hash and are skipped.
    """
    previous, checked = anchor, 0
    for number, text in enumerate(path.read_text(encoding="utf-8").splitlines(), start=1):
        try:
            value = json.loads(text)
        except json.JSONDecodeError:
            return False, checked, number
        if not isinstance(value, dict) or "hash" not in value:
            continue
        if value.get("prev_hash") != previous or value["hash"] != _chain_hash(previous, value):
            return False, checked, number
        previous = value["hash"]
        checked += 1
    return True, checked, None


def verify_all() -> tuple[bool, int, str | None]:
    """Verify the rotated files (oldest first) and the current one as a single chain.

    When the oldest rotated files were deleted (``MAX_ROTATED_FILES``), the first file kept starts from the hash its first
    record names as its predecessor: every record that remains is still checked against its own hash and against the one
    before it, so an edit or a removal inside what remains is found. What cannot be told apart is a deliberate
    deletion of the oldest files from a pruning, which is the documented limit of a chain without an external anchor.
    """
    path = llm_audit_path()
    rotated = rotated_files(path)
    files = rotated + ([path] if path.is_file() else [])
    anchor, total = "", 0
    for position, file in enumerate(files):
        start = _first_chained_prev_hash(file) if position == 0 and rotated else anchor
        ok, checked, bad = verify_chain(file, start)
        total += checked
        if not ok:
            return False, total, f"{file.name}:{bad}"
        anchor = _last_hash(file) or anchor
    return True, total, None
