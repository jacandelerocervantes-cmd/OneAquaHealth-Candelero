"""Human-review queue logic for non-singleton conformal prediction sets."""
from __future__ import annotations

from dataclasses import asdict, dataclass

from oah.audit import AuditEvent
from oah.store import ReviewStore
from oah.uncertainty import ConformalPredictionSet
from oah.timeutil import format_utc, utc_now


class AlreadyDecidedError(ValueError):
    """The item already has a human decision; changing it needs an explicit override."""


class InvalidLabelError(ValueError):
    """The label is neither in the item's prediction set nor the explicit ``other`` value."""


OTHER_LABEL = "other"  # a reviewer may reject every predicted label; that is recorded, not hidden


@dataclass(frozen=True)
class ReviewItem:
    """A human-review queue item for non-singleton conformal prediction sets."""

    specimen_id: str
    prediction_set: tuple[str, ...]
    probabilities: dict[str, float]
    status: str
    final_label: str | None = None
    reviewer_id: str | None = None
    decision_time: str | None = None
    tag: str = "synthetic"


def submit_to_queue(
    store: ReviewStore,
    prediction_set: ConformalPredictionSet,
    actor: str = "system-conformal-pipeline",
) -> ReviewItem:
    """Submit a non-singleton specimen prediction set to the human review queue.

    Raises:
        ValueError: If prediction_set is a singleton set (len == 1).
    """
    if len(prediction_set.prediction_set) == 1:
        raise ValueError(
            "Singleton prediction sets are processed autonomously and must not enter the human review queue."
        )

    item = ReviewItem(
        specimen_id=prediction_set.specimen_id,
        prediction_set=prediction_set.prediction_set,
        probabilities=prediction_set.probabilities,
        status="pending",
        tag=prediction_set.tag,
    )

    existing = store.get_review_item(item.specimen_id)
    if existing is not None and existing.status == "decided":
        raise AlreadyDecidedError(
            f"ReviewItem '{item.specimen_id}' already has a decision; resubmitting would erase it."
        )
    before_state = asdict(existing) if existing else None
    after_state = asdict(item)

    audit_event = AuditEvent.create(
        actor=actor,
        action="SUBMIT_TO_QUEUE",
        subject_id=item.specimen_id,
        before_state=before_state,
        after_state=after_state,
    )
    store.commit_with_audit(item, audit_event)  # one transaction: the item and its audit event
    return item


def decide_review_item(
    store: ReviewStore,
    specimen_id: str,
    final_label: str,
    reviewer_id: str,
    allow_override: bool = False,
) -> ReviewItem:
    """Record a human reviewer decision on a review queue item.

    The decision and its audit event are written in one transaction. ``final_label`` must be one of the
    item's predicted labels or ``other``. Changing an existing decision needs ``allow_override=True`` (an
    explicit, audited action: the audit trail keeps both decisions).

    Raises:
        ValueError: empty reviewer or unknown item.
        InvalidLabelError: label outside the prediction set (and not ``other``).
        AlreadyDecidedError: the item is decided and ``allow_override`` is False.
    """
    if not reviewer_id:
        raise ValueError("reviewer_id must be a valid non-empty string.")

    existing = store.get_review_item(specimen_id)
    if not existing:
        raise ValueError(f"ReviewItem '{specimen_id}' not found in review queue.")

    if existing.status == "decided" and not allow_override:
        raise AlreadyDecidedError(f"ReviewItem '{specimen_id}' is already decided; an override must be explicit.")
    if final_label != OTHER_LABEL and final_label not in existing.prediction_set:
        raise InvalidLabelError(
            f"final_label {final_label!r} is not in the prediction set {list(existing.prediction_set)} and is not {OTHER_LABEL!r}."
        )

    before_state = asdict(existing)
    now_str = format_utc(utc_now())

    updated = ReviewItem(
        specimen_id=existing.specimen_id,
        prediction_set=existing.prediction_set,
        probabilities=existing.probabilities,
        status="decided",
        final_label=final_label,
        reviewer_id=reviewer_id,
        decision_time=now_str,
        tag=existing.tag,
    )

    audit_event = AuditEvent.create(
        actor=reviewer_id,
        action="RECORD_DECISION" if existing.status != "decided" else "OVERRIDE_DECISION",
        subject_id=specimen_id,
        before_state=before_state,
        after_state=asdict(updated),
    )
    store.commit_with_audit(updated, audit_event)  # one transaction: the decision and its audit event
    return updated
