"""Argument validation and the sanitised argument trace of the chat tools.

Package-internal helpers (underscore names are imported by the sibling tool modules): every bad argument becomes a
``ToolError`` the model can read; nothing here raises anything else for a bad call.
"""
from __future__ import annotations

import re
from collections.abc import Mapping
from datetime import date
from typing import Any

from oah.chat.errors import ToolError
from oah.chat.tools.definitions import TOOL_DEFINITIONS
from oah.explain.safety import sanitize_text
from oah.indices.period_change import Period, PeriodError


MAX_ARGUMENT_CHARS = 64
_LOCATION_ID = re.compile(r"^[\w.\-]{1,128}$")
_COUNTRY_CODE = re.compile(r"^[A-Za-z]{2}$")
# Anything in the trace that looks like a credential (an API key pasted into a question and passed on as an argument).
_SECRET_LIKE = re.compile(r"(?i)\bsk-[\w-]{8,}|\b[A-Za-z0-9+/_-]{32,}={0,2}")
COUNTRY_ALIASES ={"EL": "GR"}  # Greece is also written EL (docs/web_app_chat_by_country.md section 2)


def normalise_country(code: str) -> str:
    upper = code.strip().upper()
    return COUNTRY_ALIASES.get(upper, upper)


# --- argument validation ------------------------------------------------------------------------------------


def _text_argument(raw: Mapping[str, Any], name: str, *, required: bool) -> str | None:
    value = raw.get(name)
    if value is None:
        if required:
            raise ToolError(f"Missing required argument {name}.")
        return None
    if not isinstance(value, str) or not value.strip() or len(value) > 128:
        raise ToolError(f"Argument {name} must be a non-empty text of at most 128 characters.")
    return value.strip()


def _date_argument(raw: Mapping[str, Any], name: str) -> date | None:
    value = raw.get(name)
    if value is None:
        return None
    if not isinstance(value, str):
        raise ToolError(f"Argument {name} must be an ISO date YYYY-MM-DD.")
    try:
        return date.fromisoformat(value.strip())
    except ValueError as error:
        raise ToolError(f"Argument {name} must be an ISO date YYYY-MM-DD.") from error


def _parse_query(raw: Mapping[str, Any]) -> str | None:
    value = _text_argument(raw, "query", required=False)
    if value is None:
        return None
    if len(value) > MAX_ARGUMENT_CHARS or not value.isprintable():
        raise ToolError(f"Argument query must be printable text of at most {MAX_ARGUMENT_CHARS} characters.")
    return value


def _parse_location(raw: Mapping[str, Any]) -> str:
    value = _text_argument(raw, "location_id", required=True)
    if value is None or not _LOCATION_ID.match(value):
        raise ToolError("Argument location_id must be a bare site id (letters, digits, dot, dash, underscore).")
    return value


def _parse_country(raw: Mapping[str, Any]) -> str | None:
    value = _text_argument(raw, "country", required=False)
    if value is None:
        return None
    if not _COUNTRY_CODE.match(value):
        raise ToolError("Argument country must be a two-letter country code.")
    return normalise_country(value)


def _check_arguments(name: str, raw: Any) -> Mapping[str, Any]:
    if not isinstance(raw, Mapping):
        raise ToolError("Tool arguments must be a JSON object.")
    allowed = set(TOOL_DEFINITIONS[name]["input_schema"]["properties"])
    unknown = sorted(str(key) for key in raw if key not in allowed)
    if unknown:
        raise ToolError(f"Unknown argument(s): {', '.join(unknown)[:80]}.")
    return raw


def trace_arguments(name: str, raw: Any) -> dict[str, Any]:
    """Arguments for the step trace and the audit log: only schema keys, scalars, bounded and sanitised."""
    if name not in TOOL_DEFINITIONS or not isinstance(raw, Mapping):
        return {}
    shown: dict[str, Any] = {}
    for key in TOOL_DEFINITIONS[name]["input_schema"]["properties"]:
        value = raw.get(key)
        if value is None:
            continue
        if isinstance(value, bool) or not isinstance(value, (str, int, float)):
            shown[key] = "[invalid]"
        elif isinstance(value, str):
            shown[key] = _SECRET_LIKE.sub("[redacted]", sanitize_text(value, MAX_ARGUMENT_CHARS, remove_instructions=True)[0])
        else:
            shown[key] = value
    return shown


def _text_filter(raw: Mapping[str, Any], name: str) -> str | None:
    value = _text_argument(raw, name, required=False)
    if value is None:
        return None
    if len(value) > MAX_ARGUMENT_CHARS or not value.isprintable():
        raise ToolError(f"Argument {name} must be printable text of at most {MAX_ARGUMENT_CHARS} characters.")
    return value


def _parse_periods(raw: Mapping[str, Any]) -> tuple[Period, Period]:
    texts = {name: _text_argument(raw, name, required=True) for name in ("a_from", "a_to", "b_from", "b_to")}
    try:
        return Period.parse(texts["a_from"], texts["a_to"], "a"), Period.parse(texts["b_from"], texts["b_to"], "b")
    except PeriodError as error:
        raise ToolError(str(error)) from error
