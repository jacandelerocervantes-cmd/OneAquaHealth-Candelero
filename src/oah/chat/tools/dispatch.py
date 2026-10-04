"""Running one tool call: argument check, handler, sanitising, size bound; and the one-line summary for the trace."""
from __future__ import annotations

import json
import re
from collections.abc import Callable, Mapping, Sequence
from typing import Any

from oah.chat import external_tools
from oah.chat.errors import ToolError
from oah.chat.tools.bathing import _compare_bathing_seasons, _get_bathing_water_history, _list_bathing_waters
from oah.chat.tools.comparison import _compare_periods
from oah.chat.tools.context import ToolContext
from oah.chat.tools.definitions import TOOL_DEFINITIONS
from oah.chat.tools.results import MAX_TOOL_RESULT_CHARS, ToolOutcome, _json_size
from oah.chat.tools.samples import _compare_bathing_concentrations, _get_bathing_samples
from oah.chat.tools.sites import (
    _get_qc_summary,
    _get_site_index,
    _get_site_measurements,
    _list_countries,
    _list_sites,
)
from oah.chat.tools.validation import _check_arguments, trace_arguments
from oah.explain.safety import sanitize_evidence


_HANDLERS: dict[str, Callable[[ToolContext, Mapping[str, Any]], dict[str, Any]]] = {
    "list_countries": _list_countries,
    "list_sites": _list_sites,
    "get_site_index": _get_site_index,
    "get_site_measurements": _get_site_measurements,
    "get_qc_summary": _get_qc_summary,
    "list_bathing_waters": _list_bathing_waters,
    "get_bathing_water_history": _get_bathing_water_history,
    "compare_periods": _compare_periods,
    "compare_bathing_seasons": _compare_bathing_seasons,
    "get_bathing_samples": _get_bathing_samples,
    "compare_bathing_concentrations": _compare_bathing_concentrations,
    **external_tools.HANDLERS,
}


def _comparison_status(result: Mapping[str, Any]) -> str:
    if "status" in result:
        return str(result["status"])
    found = [str(item.get("status")) for item in result.get("results", [])]
    return ", ".join(found) if found else "no data"


def _summary(name: str, result: Mapping[str, Any]) -> str:
    if name == "list_countries":
        return f"{len(result['countries'])} countries"
    if name == "list_sites":
        return f"{result['returned']} of {result['total_sites']} sites"
    if name == "get_site_index":
        return f"status {result.get('status')}"
    if name == "get_site_measurements":
        return f"{result['returned']} of {result['total_matching']} records"
    if name == "list_bathing_waters":
        return f"{result['returned']} of {result['total_bathing_waters']} bathing waters"
    if name == "get_bathing_water_history":
        return f"{result['returned']} seasons"
    if name == "compare_periods":
        return f"comparison status {_comparison_status(result)}"
    if name == "compare_bathing_seasons":
        return f"{result.get('comparable', 0)} comparable of {result.get('paired_bathing_waters', 0)} paired bathing waters"
    if name == "get_bathing_samples":
        return f"{result.get('returned', 0)} of {result.get('total_matching', 0)} samples"
    if name == "compare_bathing_concentrations":
        found = [str(item.get("status")) for item in (result.get("indicators") or {}).values()]
        return f"comparison status {', '.join(found) if found else 'no data'}"
    if name in external_tools.EXTERNAL_TOOL_NAMES:
        return external_tools.summary(name, result)
    return f"{result.get('total_observations', 0)} observations checked"


def _escape(text: str) -> str:
    return text.replace("<", "\\u003c").replace(">", "\\u003e")


def _failure(name: str, raw: Any, message: str) -> ToolOutcome:
    return ToolOutcome(
        name=name,
        ok=False,
        arguments=trace_arguments(name, raw),
        summary="error",
        content=json.dumps({"error": message}),
        error=message,
    )


def run_tool(ctx: ToolContext, name: str, raw: Any, allowed: Sequence[str]) -> ToolOutcome:
    """Validate, run and bound one tool call. Never raises for a bad call: the model gets the error as the result."""
    if name not in TOOL_DEFINITIONS or name not in allowed:
        shown = re.sub(r"\W", "", str(name))[:40] or "unknown"  # the model's own text: bounded and stripped
        return _failure(shown, {}, "That tool is not available.")
    try:
        arguments = _check_arguments(name, raw)
        result = _HANDLERS[name](ctx, arguments)
        result = {"origin": "real-sandbox", "data_freshness": _freshness_note(ctx), **result}  # a handler may override
        clean, notes = sanitize_evidence(result)
        if _json_size(clean) > MAX_TOOL_RESULT_CHARS:
            raise ToolError("The result is too large; ask for a narrower window, one parameter or a lower limit.")
    except ToolError as error:
        return _failure(name, raw, str(error))
    except ValueError:  # sanitize_evidence refused an oversized or too deeply nested result
        return _failure(name, raw, "The result is too large; ask for a narrower window, one parameter or a lower limit.")
    return ToolOutcome(
        name=name,
        ok=True,
        arguments=trace_arguments(name, raw),
        summary=_summary(name, clean),
        content=_escape(json.dumps(clean, sort_keys=True, default=str)),
        result=clean,
        notes=notes,
    )


def _freshness_note(ctx: ToolContext) -> dict[str, Any]:
    freshness = ctx.freshness()
    return {"status": freshness.get("status"), "as_of": freshness.get("as_of")}  # not the age: it changes every second
