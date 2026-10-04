"""Audit batch C: atomic decisions, hash-chained audit trail, no silent overwrite, validated labels."""

import sqlite3

import pytest

from oah.review import AlreadyDecidedError, InvalidLabelError, decide_review_item, submit_to_queue
from oah.store import ReviewStore
from oah.uncertainty import ConformalPredictionSet


def _set(specimen="S1", labels=("A", "B")):
    return ConformalPredictionSet(specimen, labels, {label: 1 / len(labels) for label in labels}, 0.5, "one-coin", "synthetic")


@pytest.fixture()
def store(tmp_path):
    return ReviewStore(tmp_path / "review.db")


def test_a_decided_item_cannot_be_resubmitted_or_silently_redecided(store):
    submit_to_queue(store, _set())
    decide_review_item(store, "S1", "A", "rev-1")
    with pytest.raises(AlreadyDecidedError):
        submit_to_queue(store, _set())
    with pytest.raises(AlreadyDecidedError):
        decide_review_item(store, "S1", "B", "rev-2")
    item = store.get_review_item("S1")
    assert item.final_label == "A" and item.reviewer_id == "rev-1"
    assert [e.action for e in store.list_audit_events("S1")] == ["SUBMIT_TO_QUEUE", "RECORD_DECISION"]


def test_an_explicit_override_is_audited_and_keeps_both_decisions(store):
    submit_to_queue(store, _set())
    decide_review_item(store, "S1", "A", "rev-1")
    decide_review_item(store, "S1", "B", "rev-2", allow_override=True)
    events = store.list_audit_events("S1")
    assert events[-1].action == "OVERRIDE_DECISION"
    assert events[-1].before_state["final_label"] == "A" and events[-1].after_state["final_label"] == "B"


def test_the_label_must_be_in_the_prediction_set_or_other(store):
    submit_to_queue(store, _set())
    with pytest.raises(InvalidLabelError):
        decide_review_item(store, "S1", "Z", "rev-1")
    assert store.get_review_item("S1").status == "pending"
    decided = decide_review_item(store, "S1", "other", "rev-1")
    assert decided.final_label == "other"


def test_a_failing_audit_insert_rolls_back_the_decision(store, monkeypatch):
    submit_to_queue(store, _set())

    def boom(cursor, event):
        raise sqlite3.OperationalError("disk full")

    monkeypatch.setattr(ReviewStore, "_insert_audit", staticmethod(boom))
    with pytest.raises(sqlite3.OperationalError):
        decide_review_item(store, "S1", "A", "rev-1")
    item = store.get_review_item("S1")
    assert item.status == "pending" and item.final_label is None  # no decision without its audit event


def test_the_audit_chain_verifies_and_detects_tampering(store):
    submit_to_queue(store, _set("S1"))
    submit_to_queue(store, _set("S2"))
    decide_review_item(store, "S1", "A", "rev-1")
    assert store.verify_audit_chain() == (True, 3, None)

    with sqlite3.connect(store.db_path) as conn:  # an attacker with file access drops the trigger and edits history
        conn.execute("DROP TRIGGER prevent_audit_update")
        conn.execute("UPDATE audit_events SET actor = 'someone-else' WHERE action = 'RECORD_DECISION'")
    ok, checked, bad = store.verify_audit_chain()
    assert ok is False and bad is not None and checked == 2


def test_removing_a_middle_event_breaks_the_chain(store):
    for name in ("S1", "S2", "S3"):
        submit_to_queue(store, _set(name))
    with sqlite3.connect(store.db_path) as conn:
        conn.execute("DROP TRIGGER prevent_audit_delete")
        conn.execute("DELETE FROM audit_events WHERE subject_id = 'S2'")
    assert store.verify_audit_chain()[0] is False


def test_event_ids_are_unique_per_event(store):
    submit_to_queue(store, _set("S1"))
    submit_to_queue(store, _set("S1"))
    ids = [event.event_id for event in store.list_audit_events("S1")]
    assert len(ids) == len(set(ids)) == 2


def test_databases_created_before_the_chain_are_migrated(tmp_path):
    path = tmp_path / "old.db"
    with sqlite3.connect(path) as conn:
        conn.execute(
            "CREATE TABLE audit_events (event_id TEXT PRIMARY KEY, timestamp TEXT NOT NULL, actor TEXT NOT NULL, "
            "action TEXT NOT NULL, subject_id TEXT NOT NULL, before_state_json TEXT, after_state_json TEXT)"
        )
        conn.execute("INSERT INTO audit_events VALUES ('old-1', '2026-01-01T00:00:00+00:00', 'a', 'X', 'S0', NULL, NULL)")
    store = ReviewStore(path)
    submit_to_queue(store, _set("S1"))
    assert store.verify_audit_chain() == (True, 1, None)  # the legacy event carries no hash and is skipped
    assert len(store.list_audit_events()) == 2
