"""Unit tests for consent tracking and validation."""

from datetime import datetime, timezone
import pytest

from oah.privacy.consent import ConsentRecord, is_active


def test_consent_record_validation():
    t1 = datetime(2026, 1, 1, 10, 0, tzinfo=timezone.utc)
    t2 = datetime(2026, 1, 1, 9, 0, tzinfo=timezone.utc)

    with pytest.raises(ValueError):
        ConsentRecord(
            subject_pseudonym="subject-1",
            scope="water_quality",
            granted_at=t1,
            revoked_at=t2,
        )


def test_consent_is_active_lifecycle():
    t_granted = datetime(2026, 1, 1, 0, 0, tzinfo=timezone.utc)
    t_revoked = datetime(2026, 6, 1, 0, 0, tzinfo=timezone.utc)

    record = ConsentRecord(
        subject_pseudonym="subject-1",
        scope="water_quality",
        granted_at=t_granted,
        revoked_at=t_revoked,
    )

    t_before = datetime(2025, 12, 31, 23, 59, tzinfo=timezone.utc)
    t_active = datetime(2026, 3, 1, 12, 0, tzinfo=timezone.utc)
    t_after = datetime(2026, 6, 1, 0, 0, tzinfo=timezone.utc)

    assert is_active(record, t_before) is False
    assert is_active(record, t_active) is True
    assert is_active(record, t_after) is False


def test_consent_without_revocation():
    t_granted = datetime(2026, 1, 1, 0, 0, tzinfo=timezone.utc)
    record = ConsentRecord(
        subject_pseudonym="subject-2",
        scope="water_quality",
        granted_at=t_granted,
    )

    t_query = datetime(2030, 1, 1, 0, 0, tzinfo=timezone.utc)
    assert is_active(record, t_query) is True
