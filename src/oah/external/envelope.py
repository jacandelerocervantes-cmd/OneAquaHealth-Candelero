"""The common frame of every external response: what it is, where it came from, how to credit it, and its status.

Every response says plainly that it is EXTERNAL context (``origin`` ``external-*``), what kind of numbers it holds
(``data_kind``: modelled reanalysis, modelled discharge or opportunistic records), the attribution to display, and a
``status`` of ``ok``, ``no-data`` or ``external-unavailable`` (with a ``reason``). A provider problem never raises.
"""
from __future__ import annotations

from datetime import date
from typing import Any

from oah.external.constants import (
    PROVIDER_INFO,
    STATUS_UNAVAILABLE,
)


class ExternalInputError(ValueError):
    """The caller's input is invalid (a period, a group, a limit); a route answers 422, a tool returns the message."""


def envelope(
    provider: str,
    status: str,
    reason: str | None = None,
    *,
    flags: list[str] | None = None,
    cached: bool = False,
    **fields: Any,
) -> dict[str, Any]:
    info = PROVIDER_INFO[provider]
    return {
        "status": status,
        "reason": reason,
        "provider": provider,
        "origin": info.origin,
        "data_kind": info.kind,
        "attribution": info.attribution,
        "attribution_url": info.attribution_url,
        "attribution_verified": info.attribution_verified,
        "licence": info.licence,
        "data_note": info.data_note,
        "flags": list(flags or []),
        "cached": cached,
        **fields,
    }


def unavailable(provider: str, reason: str, **fields: Any) -> dict[str, Any]:
    """The graceful result of a provider that is off, over budget, cooling down or failing."""
    return envelope(provider, STATUS_UNAVAILABLE, reason, **fields)


def validate_period(date_from: date, date_to: date, max_span_days: int) -> int:
    """The number of days of the inclusive period; ``ExternalInputError`` when inverted or longer than the maximum."""
    if date_from > date_to:
        raise ExternalInputError("date_from must not be after date_to.")
    days = (date_to - date_from).days + 1
    if days > max_span_days:
        raise ExternalInputError(f"The period is {days} days; the longest period of one request is {max_span_days} days.")
    return days
