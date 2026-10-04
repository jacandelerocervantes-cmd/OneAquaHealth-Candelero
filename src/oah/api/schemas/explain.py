"""Response model of the ``/explain/*`` routes."""
from __future__ import annotations

from typing import Any, Literal

from oah.api.schemas.language import LanguageFields

ExplanationStatus = Literal["answered", "withheld", "withheld-ungrounded"]


class ExplanationResponse(LanguageFields, extra="allow"):
    """An AI-generated explanation. Not verified; never a potability, health or regulatory determination.

    ``status``: ``answered`` (grounded and safe: ``explanation`` holds the text), ``withheld`` (unsafe: no text, the flags say
    why) or ``withheld-ungrounded`` (a number or unit could not be traced to the evidence: no text). In both withheld states
    ``explanation`` is null and ``evidence`` stays in the response, so a client can still show the data.
    """

    origin: str
    location_id: str | None = None
    specimen_id: str | None = None
    evidence: dict[str, Any]
    mode: Literal["describe", "assess"]
    status: ExplanationStatus
    explanation: str | None  # null when withheld
    model: str
    grounded: bool
    ungrounded_numbers: list[str]
    unit_mismatches: list[str]
    output_flags: list[str]
    unsafe: bool
    disclaimer: str
    evidence_sanitized: list[str]
    cached: bool
