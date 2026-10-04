"""Route support for the external-context endpoints: error mapping and the localised fixed notices.

The routes in ``oah.api.app`` stay thin: they resolve the language, call ``ExternalContext`` through ``payload`` and return
the dictionary. A bad site or input becomes a 404 or 422; a provider problem is NOT an error here: it is a normal 200
response with ``status: external-unavailable`` and a ``reason`` (docs/external_context.md section 2).
"""
from __future__ import annotations

from collections.abc import Callable
from typing import Any

from fastapi import HTTPException

from oah.external.envelope import ExternalInputError
from oah.external.service import ExternalContext, notice_keys
from oah.external.sites import SiteLookupError
from oah.i18n.strings import load_strings

STATUS_NOTICE_KEYS = ("external_context_notice",)


def localised_notices(code: str, keys: list[str] | tuple[str, ...]) -> dict[str, str]:
    strings = load_strings(code)
    return {key: strings.get(key) for key in keys}


def payload(call: Callable[[], dict[str, Any]], code: str) -> dict[str, Any]:
    """Run one ``ExternalContext`` call; 404 for an unknown site, 422 for an unusable site or invalid input."""
    try:
        result = call()
    except SiteLookupError as error:
        raise HTTPException(status_code=error.status_code, detail=error.detail) from error
    except ExternalInputError as error:
        raise HTTPException(status_code=422, detail=str(error)) from error
    return {**result, "language": code, "notices": localised_notices(code, notice_keys(result))}


def status_payload(context: ExternalContext, code: str) -> dict[str, Any]:
    return {**context.status(), "language": code, "notices": localised_notices(code, STATUS_NOTICE_KEYS)}
