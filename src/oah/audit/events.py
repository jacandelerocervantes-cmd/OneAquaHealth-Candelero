"""Audit logging dataclasses and factory functions."""
from __future__ import annotations

from dataclasses import dataclass
from uuid import uuid4
from oah.timeutil import format_utc, utc_now


@dataclass(frozen=True)
class AuditEvent:
    """An immutable audit trail record."""

    event_id: str
    timestamp: str
    actor: str
    action: str
    subject_id: str
    before_state: dict | None
    after_state: dict | None

    @classmethod
    def create(
        cls,
        actor: str,
        action: str,
        subject_id: str,
        before_state: dict | None,
        after_state: dict | None,
    ) -> AuditEvent:
        now_iso = format_utc(utc_now())
        event_id = str(uuid4())  # random: an id derived from public fields would be guessable
        return cls(
            event_id=event_id,
            timestamp=now_iso,
            actor=actor,
            action=action,
            subject_id=subject_id,
            before_state=before_state,
            after_state=after_state,
        )
