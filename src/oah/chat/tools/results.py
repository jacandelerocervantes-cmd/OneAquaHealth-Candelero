"""Result helpers shared by the chat tools: the size bound, units attached to numbers, and the outcome type."""
from __future__ import annotations

import json
from dataclasses import dataclass
from typing import Any

from oah.explain.safety import MAX_ITEMS


MAX_TOOL_RESULT_CHARS = 12_000


_BATHING_SNAPSHOT = {"status": "snapshot", "as_of": None}  # a published edition, not a live feed


def _json_size(value: Any) -> int:
    return len(json.dumps(value, sort_keys=True, default=str))


def _shrink_list(result: dict[str, Any], key: str, max_chars: int) -> None:
    """Drop trailing items until the result fits; the counts and ``truncated`` then say what happened."""
    items = result[key]
    if len(items) > MAX_ITEMS:
        del items[MAX_ITEMS:]
        result["truncated"] = True
    while items and _json_size(result) > max_chars:
        del items[int(len(items) * 0.8) if len(items) > 1 else 0 :]
        result["truncated"] = True
    result["returned"] = len(items)


def _amount(value: Any, unit: Any, **extra: Any) -> dict[str, Any] | None:
    """A number together with ITS unit, so the grounding check pairs each figure with the right unit."""
    if value is None:
        return None
    return {"amount": value, "unit": unit, **{k: v for k, v in extra.items() if v is not None}}


@dataclass(frozen=True)
class ToolOutcome:
    name: str
    ok: bool
    arguments: dict[str, Any]
    summary: str
    content: str  # the text returned to the model as the tool result
    result: dict[str, Any] | None = None  # the sanitised result (None on error); the evidence for grounding
    notes: tuple[str, ...] = ()  # what sanitisation changed
    error: str | None = None
