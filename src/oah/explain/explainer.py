"""Grounded natural-language explanations over already-computed OneAquaHealth findings.

This module adds NO new business logic: every explanation is generated from
data already produced and already tested elsewhere in oah.* (the CCME WQI
result in oah.indices, or a pending item from oah.review's human-review
queue). The LLM call is a single, non-agentic Claude Messages API request.
See oah.explain.grounding for the deterministic post-hoc validation this
module always runs on the model's output before returning it.

Two modes (oah.explain.prompts.Mode): "describe" (the original, strictly factual mode) and
"assess" (an interpretive concern-level + recommendation reading on the same evidence). Both
are grounding-checked identically -- the check only flags invented numbers, so a qualitative
judgment in "assess" mode is never itself flagged, only a fabricated number would be.
"""
from __future__ import annotations

from dataclasses import dataclass
from typing import Any, Mapping
from uuid import uuid4

import anthropic

from oah.config import load_settings
from oah.explain import audit
from oah.explain.errors import wrap_anthropic_error
from oah.explain.grounding import check_grounding
from oah.explain.prompts import ASSESS_SYSTEM_PROMPT, DESCRIBE_SYSTEM_PROMPT, Mode, build_user_prompt, system_prompt_for_mode
from oah.explain.safety import guard_output, sanitize_evidence

_MAX_OUTPUT_TOKENS = 1024


@dataclass(frozen=True)
class Explanation:
    kind: str
    mode: Mode
    text: str
    model: str
    grounded: bool
    ungrounded_numbers: tuple[str, ...]
    unit_mismatches: tuple[str, ...] = ()
    input_tokens: int | None = None
    output_tokens: int | None = None
    evidence_sanitized: tuple[str, ...] = ()  # what sanitize_evidence changed before the prompt was built
    output_flags: tuple[str, ...] = ()  # guard_output flags: unsafe to render or hijack-like output


def explain(
    kind: str,
    evidence: Mapping[str, Any],
    *,
    client: Any,
    model: str | None = None,
    mode: Mode = "describe",
) -> Explanation:
    """Call Claude once to explain (or assess) `evidence`, then validate the result is grounded.

    `client` is always injected by the caller (never constructed here), so unit
    tests can supply a fake with no real network access -- the same pattern
    this project already uses for the sandbox client and the review store.
    """
    resolved_model = model or load_settings().llm_model
    evidence, sanitized_notes = sanitize_evidence(evidence)  # ValueError if the evidence is oversized or too deep
    call_id = uuid4().hex
    # The dispatch is audited BEFORE anything leaves the process; if it cannot be recorded, nothing is sent.
    audit.record(
        "dispatch",
        call_id=call_id,
        kind=kind,
        mode=mode,
        model=resolved_model,
        evidence_sha256=audit.evidence_digest(evidence),
        evidence_sanitized=list(sanitized_notes),
    )
    try:
        response = client.messages.create(
            model=resolved_model,
            max_tokens=_MAX_OUTPUT_TOKENS,
            system=system_prompt_for_mode(mode),
            messages=[{"role": "user", "content": build_user_prompt(kind, evidence, mode)}],
        )
    except anthropic.APIError as error:
        audit.record("error", call_id=call_id, error_type=type(error).__name__)
        raise wrap_anthropic_error(error) from error
    text = "".join(block.text for block in response.content if block.type == "text").strip()
    grounding = check_grounding(text, evidence)
    flags = guard_output(text, mode, (DESCRIBE_SYSTEM_PROMPT, ASSESS_SYSTEM_PROMPT))
    usage = getattr(response, "usage", None)
    audit.record(
        "result",
        call_id=call_id,
        input_tokens=getattr(usage, "input_tokens", None),
        output_tokens=getattr(usage, "output_tokens", None),
        grounded=grounding.grounded,
        output_flags=list(flags),
    )
    return Explanation(
        kind=kind,
        mode=mode,
        text=text,
        model=resolved_model,
        grounded=grounding.grounded,
        ungrounded_numbers=grounding.ungrounded_numbers,
        unit_mismatches=grounding.unit_mismatches,
        input_tokens=getattr(getattr(response, "usage", None), "input_tokens", None),
        output_tokens=getattr(getattr(response, "usage", None), "output_tokens", None),
        evidence_sanitized=sanitized_notes,
        output_flags=flags,
    )
