"""The chat agent: a bounded Anthropic Messages API tool-use loop over the read-only tools of ``oah.chat.tools``.

Bounds, all enforced here and never left to the model: at most ``max_steps`` model calls, at most ``max_tool_calls``
tool executions, a wall-clock deadline, a bounded output size per call, and a bounded size per tool result. When any
of them is reached the answer is a fixed "could not answer within the budget" text, never a partial guess.

The final answer is checked against the concatenation of the tool results (the only evidence) with the same
deterministic checks as the explanation layer (``check_grounding``, ``guard_output``). An unsafe answer is withheld
(``withheld``) and so is one that is not grounded (``withheld-ungrounded``); only a grounded, safe answer is ``answered``. A withheld result also carries a compact
evidence summary of the tool results (``oah.chat.evidence``).
Every dispatch, model call, tool call, tool result and error is appended to the hash-chained audit log
(``oah.explain.audit``) as digests and counts; if a record cannot be written the conversation stops (``OSError``
propagates) before the next call leaves the process.
"""
from __future__ import annotations

import time
from collections.abc import Callable, Mapping, Sequence
from dataclasses import dataclass, field
from typing import Any, Literal
from uuid import uuid4

import anthropic

from oah.chat.causation import FLAG as CAUSAL_CLAIM_FLAG
from oah.chat.causation import causal_claim_flags
from oah.chat.evidence import build_evidence
from oah.chat.external_tools import EXTERNAL_TOOL_NAMES
from oah.chat.prompts import (
    BUDGET_EXCEEDED_ANSWER,
    CHAT_LEAK_CHECK_SIZED,
    CHAT_SYSTEM_PROMPT,
    NO_ANSWER_TEXT,
    build_user_turn,
)
from oah.chat.tools import (
    MAX_CITATIONS,
    ToolContext,
    ToolOutcome,
    allowed_tools,
    citations_for,
    origin_for,
    run_tool,
    tool_definitions,
)
from oah.explain import audit
from oah.explain.errors import wrap_anthropic_error
from oah.explain.grounding import check_grounding
from oah.explain.safety import UNSAFE_OUTPUT_FLAGS, guard_output, sanitize_text

MAX_MESSAGE_CHARS = 500
MAX_HISTORY_TURNS = 6
MAX_HISTORY_TURN_CHARS = 500
MAX_OUTPUT_TOKENS = 1024  # per model call
MAX_TOOL_CALLS_PER_STEP = 4
PER_CALL_TIMEOUT_SECONDS = 30.0

ChatStatus = Literal["answered", "budget-exceeded", "withheld", "withheld-ungrounded", "no-answer"]


@dataclass(frozen=True)
class ChatLimits:
    max_steps: int
    timeout_seconds: float
    max_output_tokens: int = MAX_OUTPUT_TOKENS
    max_tool_calls: int | None = None  # default: twice the steps

    @property
    def tool_call_budget(self) -> int:
        return self.max_tool_calls if self.max_tool_calls is not None else 2 * self.max_steps


@dataclass(frozen=True)
class ChatResult:
    status: ChatStatus
    answer: str | None
    steps: list[dict[str, Any]]
    citations: list[dict[str, Any]]
    grounded: bool
    ungrounded_numbers: tuple[str, ...]
    unit_mismatches: tuple[str, ...]
    output_flags: tuple[str, ...]
    unsafe: bool
    model: str
    model_calls: int
    input_tokens: int | None
    output_tokens: int | None
    input_notes: tuple[str, ...] = ()
    origin: str = "real-sandbox"
    evidence_digest: str = field(default="", repr=False)
    # compact data the agent consulted, built from the tool results (never from model text); only for a withheld answer
    evidence: list[dict[str, Any]] | None = None
    evidence_truncated: bool = False


def clean_inputs(message: str, history: Sequence[Mapping[str, str]]) -> tuple[str, list[dict[str, str]], list[str]]:
    """Bounded, cleaned question and history. Prior turns that look like instructions are replaced, not passed on."""
    notes: list[str] = []
    text, message_notes = sanitize_text(message, MAX_MESSAGE_CHARS, remove_instructions=False)
    notes.extend(f"question: {note}" for note in message_notes)
    turns: list[dict[str, str]] = []
    for position, turn in enumerate(list(history)[-MAX_HISTORY_TURNS:]):
        cleaned, turn_notes = sanitize_text(str(turn.get("text", "")), MAX_HISTORY_TURN_CHARS, remove_instructions=True)
        notes.extend(f"history[{position}]: {note}" for note in turn_notes)
        role = "assistant" if turn.get("role") == "assistant" else "user"
        turns.append({"role": role, "text": cleaned})
    return text, turns, notes


def _block_dict(block: Any) -> dict[str, Any]:
    """An SDK content block as a plain dict, so the next request never carries SDK objects."""
    if block.type == "tool_use":
        return {"type": "tool_use", "id": str(block.id), "name": str(block.name), "input": block.input}
    return {"type": "text", "text": str(getattr(block, "text", ""))}


def _tokens(response: Any) -> tuple[int | None, int | None]:
    usage = getattr(response, "usage", None)
    return getattr(usage, "input_tokens", None), getattr(usage, "output_tokens", None)


def _add(total: int | None, value: int | None) -> int | None:
    if value is None:
        return total
    return value if total is None else total + value


def run_chat(
    message: str,
    country: str | None,
    index: str | None,
    history: Sequence[Mapping[str, str]],
    *,
    client: Any,
    ctx: ToolContext,
    model: str,
    limits: ChatLimits,
    reserve_model_call: Callable[[], bool],
    clock: Callable[[], float] = time.monotonic,
) -> ChatResult:
    """Run one conversation. Raises ``LLMRequestError`` for a provider failure and ``OSError`` for an audit failure."""
    question, turns, input_notes = clean_inputs(message, history)
    allowed = allowed_tools(index)
    tools = tool_definitions(allowed)
    messages: list[dict[str, Any]] = [{"role": "user", "content": build_user_turn(question, country, index, turns)}]
    call_id = uuid4().hex
    deadline = clock() + limits.timeout_seconds
    audit.record(
        "chat-dispatch",
        call_id=call_id,
        model=model,
        country=country,
        index=index,
        question_sha256=audit.text_digest(question),
        question_chars=len(question),  # digest and length only: no text of the question is ever written to the audit trail
        history_turns=len(turns),
        input_notes=input_notes,
        max_steps=limits.max_steps,
        tools=list(allowed),
    )

    steps: list[dict[str, Any]] = []
    outcomes: list[ToolOutcome] = []
    model_calls = tool_calls = 0
    input_tokens: int | None = None
    output_tokens: int | None = None
    final_text: str | None = None

    for step in range(1, limits.max_steps + 1):
        if clock() >= deadline or not reserve_model_call():
            break
        is_last = step == limits.max_steps
        audit.record("chat-model-call", call_id=call_id, step=step, messages_sha256=audit.evidence_digest({"m": messages}))
        try:
            response = client.messages.create(
                model=model,
                max_tokens=limits.max_output_tokens,
                system=CHAT_SYSTEM_PROMPT,
                messages=messages,
                tools=tools,
                tool_choice={"type": "none"} if is_last else {"type": "auto"},
                timeout=max(1.0, min(PER_CALL_TIMEOUT_SECONDS, deadline - clock())),
            )
        except anthropic.APIError as error:
            audit.record("chat-error", call_id=call_id, step=step, error_type=type(error).__name__)
            raise wrap_anthropic_error(error) from error
        model_calls += 1
        step_in, step_out = _tokens(response)
        input_tokens, output_tokens = _add(input_tokens, step_in), _add(output_tokens, step_out)
        blocks = list(response.content)
        tool_uses = [block for block in blocks if block.type == "tool_use"]
        if not tool_uses:
            final_text = "".join(str(getattr(block, "text", "")) for block in blocks if block.type == "text").strip()
            break
        if is_last:
            break  # the model asked for another tool although none was allowed: out of budget
        messages.append({"role": "assistant", "content": [_block_dict(block) for block in blocks if block.type in ("text", "tool_use")]})
        results: list[dict[str, Any]] = []
        for position, block in enumerate(tool_uses):
            name, raw = str(block.name), block.input
            if tool_calls >= limits.tool_call_budget or position >= MAX_TOOL_CALLS_PER_STEP or clock() >= deadline:
                outcome = ToolOutcome(
                    name=name[:40], ok=False, arguments={}, summary="error",
                    content='{"error": "Tool budget exhausted; answer from what you already have or say you cannot."}',
                    error="Tool budget exhausted.",
                )
            else:
                tool_calls += 1
                audit.record(
                    "chat-tool-call", call_id=call_id, step=step, tool=name[:40],
                    arguments_sha256=audit.evidence_digest({"a": raw if isinstance(raw, Mapping) else None}),
                )
                outcome = run_tool(ctx, name, raw, allowed)
                audit.record(
                    "chat-tool-result", call_id=call_id, step=step, tool=outcome.name, ok=outcome.ok,
                    result_sha256=audit.text_digest(outcome.content), result_chars=len(outcome.content),
                    sanitized_notes=len(outcome.notes),
                    error_sha256=audit.text_digest(outcome.error) if outcome.error else None,  # a message may echo model text
                )
            outcomes.append(outcome)
            steps.append(
                {"step": step, "tool": outcome.name, "arguments": outcome.arguments, "ok": outcome.ok,
                 "summary": outcome.summary if outcome.ok else (outcome.error or "error")}
            )
            results.append(
                {"type": "tool_result", "tool_use_id": str(block.id), "content": outcome.content, "is_error": not outcome.ok}
            )
        messages.append({"role": "user", "content": results})

    evidence = {"tool_results": [outcome.result for outcome in outcomes if outcome.ok and outcome.result is not None]}
    citations: list[dict[str, Any]] = []
    for outcome in outcomes:
        for citation in citations_for(outcome):
            if citation not in citations and len(citations) < MAX_CITATIONS:
                citations.append(citation)

    status: ChatStatus
    answer: str | None
    grounded = True
    ungrounded: tuple[str, ...] = ()
    mismatches: tuple[str, ...] = ()
    flags: tuple[str, ...] = ()
    if final_text is None:
        status, answer = "budget-exceeded", BUDGET_EXCEEDED_ANSWER
    elif not final_text:
        status, answer = "no-answer", NO_ANSWER_TEXT
    else:
        check = check_grounding(final_text, evidence)
        grounded, ungrounded, mismatches = check.grounded, check.ungrounded_numbers, check.unit_mismatches
        flags = guard_output(final_text, "describe", CHAT_LEAK_CHECK_SIZED)
        if any(outcome.ok and outcome.name in EXTERNAL_TOOL_NAMES for outcome in outcomes):
            # weather, flow and species records are context only: a causal claim about them is withheld like any unsafe answer
            flags = (*flags, *causal_claim_flags(final_text))
        if set(flags) & (UNSAFE_OUTPUT_FLAGS | {CAUSAL_CLAIM_FLAG}):
            status, answer = "withheld", None
        elif not grounded:
            # numbers or units that cannot be traced to the tool results: the text is not returned (the grounding rule itself is
            # unchanged); the citations and steps stay in the result so the caller can still show the data that was consulted
            status, answer = "withheld-ungrounded", None
        else:
            status, answer = "answered", final_text
    unsafe = status == "withheld"
    withheld_evidence: list[dict[str, Any]] | None = None
    withheld_truncated = False
    if status in ("withheld", "withheld-ungrounded"):
        withheld_evidence, withheld_truncated = build_evidence(outcomes)  # data consulted, shown instead of the withheld text
    evidence_digest = audit.evidence_digest(evidence)
    audit.record(
        "chat-result",
        call_id=call_id,
        status=status,
        steps=model_calls,
        tool_calls=tool_calls,
        input_tokens=input_tokens,
        output_tokens=output_tokens,
        grounded=grounded,
        ungrounded_count=len(ungrounded),
        output_flags=list(flags),
        evidence_sha256=evidence_digest,
        answer_sha256=audit.text_digest(final_text) if final_text else None,
    )
    return ChatResult(
        status=status,
        answer=answer,
        steps=steps,
        citations=citations,
        grounded=grounded,
        ungrounded_numbers=tuple(ungrounded),
        unit_mismatches=tuple(mismatches),
        output_flags=tuple(flags),
        unsafe=unsafe,
        model=model,
        model_calls=model_calls,
        input_tokens=input_tokens,
        output_tokens=output_tokens,
        input_notes=tuple(input_notes),
        origin=origin_for(outcomes),
        evidence_digest=evidence_digest,
        evidence=withheld_evidence,
        evidence_truncated=withheld_truncated,
    )
