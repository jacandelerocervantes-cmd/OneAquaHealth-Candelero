"""Data subject consent tracking and validation.

Data subject consent records specify granted and optional revocation timestamps.
"""

from __future__ import annotations

from dataclasses import dataclass
from datetime import datetime


@dataclass(frozen=True)
class ConsentRecord:
    """Immutable data subject consent record.

    Attributes:
        subject_pseudonym: Pseudonymous subject identifier.
        scope: Consent domain or scope string (e.g. 'water_quality_citizen_science').
        granted_at: Timestamp when consent was granted.
        revoked_at: Optional timestamp when consent was revoked.
    """

    subject_pseudonym: str
    scope: str
    granted_at: datetime
    revoked_at: datetime | None = None

    def __post_init__(self) -> None:
        if self.revoked_at is not None and self.revoked_at < self.granted_at:
            raise ValueError(
                f"revoked_at ({self.revoked_at}) cannot be prior to granted_at ({self.granted_at})."
            )


def is_active(consent: ConsentRecord, at_time: datetime) -> bool:
    """Determine whether a consent record is active at a given timestamp.

    A consent record is active at at_time if:
        at_time >= granted_at AND (revoked_at is None OR at_time < revoked_at).

    Args:
        consent: ConsentRecord instance.
        at_time: Query timestamp.

    Returns:
        True if consent is active at at_time, False otherwise.
    """
    if at_time < consent.granted_at:
        return False

    if consent.revoked_at is not None and at_time >= consent.revoked_at:
        return False

    return True
