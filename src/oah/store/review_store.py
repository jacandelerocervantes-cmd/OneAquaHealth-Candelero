"""SQLite database access layer for human review queue and audit trail."""
from __future__ import annotations

import hashlib
import json
from contextlib import closing
from pathlib import Path
import sqlite3
from typing import TYPE_CHECKING
from oah.audit import AuditEvent
from oah.paths import REPO_ROOT, review_db_path

if TYPE_CHECKING:
    from oah.review.queue import ReviewItem


class ReviewStore:
    """Sole database access layer for review items and audit events using SQLite."""

    def __init__(self, db_path: Path | str | None = None) -> None:
        if db_path is None:
            self.db_path = review_db_path()
        else:
            self.db_path = Path(db_path).resolve()

        if REPO_ROOT in self.db_path.parents or self.db_path == REPO_ROOT:
            raise ValueError(f"Database path '{self.db_path}' must live outside the repository root.")

        self.db_path.parent.mkdir(parents=True, exist_ok=True)
        self._init_db()

    def _get_connection(self) -> sqlite3.Connection:
        conn = sqlite3.connect(self.db_path)
        conn.row_factory = sqlite3.Row
        return conn

    def _init_db(self) -> None:
        with self._get_connection() as conn:
            cursor = conn.cursor()
            cursor.execute(
                """
                CREATE TABLE IF NOT EXISTS review_items (
                    specimen_id TEXT PRIMARY KEY,
                    prediction_set_json TEXT NOT NULL,
                    probabilities_json TEXT NOT NULL,
                    status TEXT NOT NULL,
                    final_label TEXT,
                    reviewer_id TEXT,
                    decision_time TEXT,
                    tag TEXT NOT NULL
                )
                """
            )
            cursor.execute(
                """
                CREATE TABLE IF NOT EXISTS audit_events (
                    event_id TEXT PRIMARY KEY,
                    timestamp TEXT NOT NULL,
                    actor TEXT NOT NULL,
                    action TEXT NOT NULL,
                    subject_id TEXT NOT NULL,
                    before_state_json TEXT,
                    after_state_json TEXT
                )
                """
            )
            cursor.execute(
                """
                CREATE TRIGGER IF NOT EXISTS prevent_audit_update
                BEFORE UPDATE ON audit_events
                BEGIN
                    SELECT RAISE(FAIL, 'audit_events table is append-only: UPDATE is prohibited');
                END;
                """
            )
            cursor.execute(
                """
                CREATE TRIGGER IF NOT EXISTS prevent_audit_delete
                BEFORE DELETE ON audit_events
                BEGIN
                    SELECT RAISE(FAIL, 'audit_events table is append-only: DELETE is prohibited');
                END;
                """
            )
            existing_columns = {row["name"] for row in cursor.execute("PRAGMA table_info(audit_events)")}
            for column in ("prev_hash", "event_hash"):  # databases created before the hash chain get the columns
                if column not in existing_columns:
                    cursor.execute(f"ALTER TABLE audit_events ADD COLUMN {column} TEXT")
            conn.commit()

    @staticmethod
    def _upsert_item(cursor: sqlite3.Cursor, item: ReviewItem) -> None:
        cursor.execute(
            """
            INSERT INTO review_items (
                specimen_id, prediction_set_json, probabilities_json,
                status, final_label, reviewer_id, decision_time, tag
            ) VALUES (?, ?, ?, ?, ?, ?, ?, ?)
            ON CONFLICT(specimen_id) DO UPDATE SET
                prediction_set_json=excluded.prediction_set_json,
                probabilities_json=excluded.probabilities_json,
                status=excluded.status,
                final_label=excluded.final_label,
                reviewer_id=excluded.reviewer_id,
                decision_time=excluded.decision_time,
                tag=excluded.tag
            """,
            (
                item.specimen_id,
                json.dumps(list(item.prediction_set)),
                json.dumps(item.probabilities),
                item.status,
                item.final_label,
                item.reviewer_id,
                item.decision_time,
                item.tag,
            ),
        )

    @staticmethod
    def _event_fields(event: AuditEvent) -> tuple[str, ...]:
        return (
            event.event_id,
            event.timestamp,
            event.actor,
            event.action,
            event.subject_id,
            json.dumps(event.before_state, sort_keys=True) if event.before_state is not None else "",
            json.dumps(event.after_state, sort_keys=True) if event.after_state is not None else "",
        )

    @classmethod
    def _chain_hash(cls, previous: str | None, event: AuditEvent) -> str:
        payload = json.dumps([previous or "", *cls._event_fields(event)], ensure_ascii=True)
        return hashlib.sha256(payload.encode("utf-8")).hexdigest()

    @classmethod
    def _insert_audit(cls, cursor: sqlite3.Cursor, event: AuditEvent) -> None:
        """Append an event chained to the previous one (call inside a transaction that reads the tail)."""
        cursor.execute("SELECT event_hash FROM audit_events ORDER BY rowid DESC LIMIT 1")
        tail = cursor.fetchone()
        previous = tail["event_hash"] if tail else None
        cursor.execute(
            """
            INSERT INTO audit_events (
                event_id, timestamp, actor, action, subject_id,
                before_state_json, after_state_json, prev_hash, event_hash
            ) VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?)
            """,
            (
                event.event_id,
                event.timestamp,
                event.actor,
                event.action,
                event.subject_id,
                json.dumps(event.before_state) if event.before_state is not None else None,
                json.dumps(event.after_state) if event.after_state is not None else None,
                previous,
                cls._chain_hash(previous, event),
            ),
        )

    def commit_with_audit(self, item: ReviewItem | None, event: AuditEvent) -> None:
        """Write the review item and its audit event in ONE transaction: both persist or neither does."""
        with closing(self._get_connection()) as conn:
            conn.isolation_level = None  # explicit transaction control
            cursor = conn.cursor()
            cursor.execute("BEGIN IMMEDIATE")
            try:
                if item is not None:
                    self._upsert_item(cursor, item)
                self._insert_audit(cursor, event)
                cursor.execute("COMMIT")
            except BaseException:
                cursor.execute("ROLLBACK")
                raise

    def verify_audit_chain(self) -> tuple[bool, int, str | None]:
        """Recompute the audit hash chain: ``(ok, hashed_events_checked, first_bad_event_id)``.

        Detects an edited, reordered or removed event that is followed by a later one. It cannot detect the
        removal of the most recent events (no external anchor) and skips events written before the chain
        existed (they carry no hash).
        """
        with closing(self._get_connection()) as conn:
            rows = conn.execute("SELECT * FROM audit_events ORDER BY rowid ASC").fetchall()
        previous: str | None = None
        checked = 0
        for row in rows:
            if row["event_hash"] is None:
                continue
            event = AuditEvent(
                event_id=row["event_id"],
                timestamp=row["timestamp"],
                actor=row["actor"],
                action=row["action"],
                subject_id=row["subject_id"],
                before_state=json.loads(row["before_state_json"]) if row["before_state_json"] else None,
                after_state=json.loads(row["after_state_json"]) if row["after_state_json"] else None,
            )
            if row["prev_hash"] != previous or row["event_hash"] != self._chain_hash(previous, event):
                return False, checked, row["event_id"]
            previous = row["event_hash"]
            checked += 1
        return True, checked, None

    def save_review_item(self, item: ReviewItem) -> None:
        """Insert or update a review queue item in the database."""
        with closing(self._get_connection()) as conn:
            self._upsert_item(conn.cursor(), item)
            conn.commit()

    def get_review_item(self, specimen_id: str) -> ReviewItem | None:
        """Fetch a single review queue item by specimen ID."""
        from oah.review.queue import ReviewItem

        with self._get_connection() as conn:
            cursor = conn.cursor()
            cursor.execute(
                "SELECT * FROM review_items WHERE specimen_id = ?",
                (specimen_id,),
            )
            row = cursor.fetchone()
            if not row:
                return None
            return ReviewItem(
                specimen_id=row["specimen_id"],
                prediction_set=tuple(json.loads(row["prediction_set_json"])),
                probabilities=json.loads(row["probabilities_json"]),
                status=row["status"],
                final_label=row["final_label"],
                reviewer_id=row["reviewer_id"],
                decision_time=row["decision_time"],
                tag=row["tag"],
            )

    def list_review_items(self, status: str | None = None) -> list[ReviewItem]:
        """List review queue items, optionally filtered by status."""
        from oah.review.queue import ReviewItem

        with self._get_connection() as conn:
            cursor = conn.cursor()
            if status:
                cursor.execute(
                    "SELECT * FROM review_items WHERE status = ? ORDER BY specimen_id",
                    (status,),
                )
            else:
                cursor.execute("SELECT * FROM review_items ORDER BY specimen_id")
            rows = cursor.fetchall()
            return [
                ReviewItem(
                    specimen_id=row["specimen_id"],
                    prediction_set=tuple(json.loads(row["prediction_set_json"])),
                    probabilities=json.loads(row["probabilities_json"]),
                    status=row["status"],
                    final_label=row["final_label"],
                    reviewer_id=row["reviewer_id"],
                    decision_time=row["decision_time"],
                    tag=row["tag"],
                )
                for row in rows
            ]

    def add_audit_event(self, event: AuditEvent) -> None:
        """Insert an immutable, hash-chained audit event into the database."""
        self.commit_with_audit(None, event)

    def list_audit_events(self, subject_id: str | None = None) -> list[AuditEvent]:
        """List audit events, optionally filtered by subject ID."""
        with self._get_connection() as conn:
            cursor = conn.cursor()
            if subject_id:
                cursor.execute(
                    "SELECT * FROM audit_events WHERE subject_id = ? ORDER BY timestamp ASC",
                    (subject_id,),
                )
            else:
                cursor.execute("SELECT * FROM audit_events ORDER BY timestamp ASC")
            rows = cursor.fetchall()
            return [
                AuditEvent(
                    event_id=row["event_id"],
                    timestamp=row["timestamp"],
                    actor=row["actor"],
                    action=row["action"],
                    subject_id=row["subject_id"],
                    before_state=json.loads(row["before_state_json"]) if row["before_state_json"] else None,
                    after_state=json.loads(row["after_state_json"]) if row["after_state_json"] else None,
                )
                for row in rows
            ]
