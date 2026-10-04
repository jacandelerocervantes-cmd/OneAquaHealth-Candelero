"""Unit tests for the human-review queue, SQLite ReviewStore, and append-only audit trail."""
import sqlite3
import pytest

from oah.paths import REPO_ROOT
from oah.review.queue import decide_review_item, submit_to_queue
from oah.store.review_store import ReviewStore
from oah.uncertainty.conformal import ConformalPredictionSet


@pytest.fixture
def temp_db_path(tmp_path):
    """Provide a temporary database path located outside the repository root."""
    return tmp_path / "test_oah_review.db"


def test_singleton_set_rejection_in_queue(temp_db_path):
    store = ReviewStore(temp_db_path)
    singleton_set = ConformalPredictionSet(
        specimen_id="SPEC-SINGLETON-01",
        prediction_set=("Baetidae",),
        probabilities={"Baetidae": 0.95, "Heptageniidae": 0.05},
        quantile_cutoff=0.20,
        probability_provider="dawid-skene",
        tag="synthetic",
    )
    with pytest.raises(ValueError, match="processed autonomously"):
        submit_to_queue(store, singleton_set)


def test_persistence_across_reopening_review_store(temp_db_path):
    store1 = ReviewStore(temp_db_path)
    multi_set = ConformalPredictionSet(
        specimen_id="SPEC-MULTI-01",
        prediction_set=("Baetidae", "Heptageniidae"),
        probabilities={"Baetidae": 0.55, "Heptageniidae": 0.45},
        quantile_cutoff=0.25,
        probability_provider="dawid-skene",
        tag="synthetic",
    )
    item = submit_to_queue(store1, multi_set, actor="system-test")
    assert item.status == "pending"

    decide_review_item(
        store=store1,
        specimen_id="SPEC-MULTI-01",
        final_label="Baetidae",
        reviewer_id="rev-alice",
    )

    store2 = ReviewStore(temp_db_path)
    retrieved_item = store2.get_review_item("SPEC-MULTI-01")
    assert retrieved_item is not None
    assert retrieved_item.status == "decided"
    assert retrieved_item.final_label == "Baetidae"
    assert retrieved_item.reviewer_id == "rev-alice"

    events = store2.list_audit_events("SPEC-MULTI-01")
    assert len(events) == 2
    assert events[0].action == "SUBMIT_TO_QUEUE"
    assert events[1].action == "RECORD_DECISION"


def test_store_has_no_update_or_delete_methods_for_audit_events():
    methods = [m for m in dir(ReviewStore) if not m.startswith("_")]
    for method_name in methods:
        assert "update_audit" not in method_name
        assert "delete_audit" not in method_name
        assert "remove_audit" not in method_name


def test_raw_sql_update_or_delete_on_audit_events_raises_sqlite_error(temp_db_path):
    store = ReviewStore(temp_db_path)
    multi_set = ConformalPredictionSet(
        specimen_id="SPEC-TRIGGER-01",
        prediction_set=("Baetidae", "Heptageniidae"),
        probabilities={"Baetidae": 0.60, "Heptageniidae": 0.40},
        quantile_cutoff=0.25,
        probability_provider="dawid-skene",
        tag="synthetic",
    )
    submit_to_queue(store, multi_set)

    events = store.list_audit_events("SPEC-TRIGGER-01")
    assert len(events) == 1
    event_id = events[0].event_id

    conn = store._get_connection()
    try:
        with pytest.raises((sqlite3.OperationalError, sqlite3.IntegrityError), match="append-only: UPDATE is prohibited"):
            conn.execute(
                "UPDATE audit_events SET actor = 'malicious' WHERE event_id = ?",
                (event_id,),
            )
        with pytest.raises((sqlite3.OperationalError, sqlite3.IntegrityError), match="append-only: DELETE is prohibited"):
            conn.execute(
                "DELETE FROM audit_events WHERE event_id = ?",
                (event_id,),
            )
    finally:
        conn.close()


def test_database_path_inside_repo_raises_value_error():
    inside_repo_path = REPO_ROOT / "oah_review.db"
    with pytest.raises(ValueError, match="live outside the repository root"):
        ReviewStore(inside_repo_path)


def test_review_items_and_prediction_sets_carry_synthetic_tag(temp_db_path):
    store = ReviewStore(temp_db_path)
    pred_set = ConformalPredictionSet(
        specimen_id="SPEC-TAG-01",
        prediction_set=("Baetidae", "Gammaridae"),
        probabilities={"Baetidae": 0.50, "Gammaridae": 0.50},
        quantile_cutoff=0.25,
        probability_provider="dawid-skene",
        tag="synthetic",
    )
    assert pred_set.tag == "synthetic"
    item = submit_to_queue(store, pred_set)
    assert item.tag == "synthetic"
    retrieved = store.get_review_item("SPEC-TAG-01")
    assert retrieved is not None
    assert retrieved.tag == "synthetic"


def test_multiple_decisions_append_new_audit_events(temp_db_path):
    store = ReviewStore(temp_db_path)
    multi_set = ConformalPredictionSet(
        specimen_id="SPEC-REVISION-01",
        prediction_set=("Baetidae", "Heptageniidae"),
        probabilities={"Baetidae": 0.52, "Heptageniidae": 0.48},
        quantile_cutoff=0.25,
        probability_provider="dawid-skene",
        tag="synthetic",
    )
    submit_to_queue(store, multi_set)

    decide_review_item(store, "SPEC-REVISION-01", "Baetidae", "rev-bob")
    decide_review_item(store, "SPEC-REVISION-01", "Heptageniidae", "rev-supervisor", allow_override=True)

    events = store.list_audit_events("SPEC-REVISION-01")
    assert len(events) == 3
    assert events[0].action == "SUBMIT_TO_QUEUE"
    assert events[1].action == "RECORD_DECISION"
    assert events[1].after_state["final_label"] == "Baetidae"
    assert events[2].action == "OVERRIDE_DECISION"
    assert events[2].after_state["final_label"] == "Heptageniidae"
