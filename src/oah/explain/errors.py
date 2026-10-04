"""A clean, safe-to-return exception wrapping real Anthropic SDK failures.

Without this, an unhandled anthropic.APIError (billing, upstream rate limit, a network
failure reaching Anthropic, ...) surfaces as a raw Python traceback and a generic 500 to any
caller of /explain/*. That is both unhelpful (no clean message) and a minor information leak
(a stack trace, including local file paths, in an HTTP response). This module is the one place
that translates the SDK's exception hierarchy into something the API layer can map to a
sensible HTTP status without needing to know anthropic's own exception types.
"""
from __future__ import annotations

import logging

import anthropic

logger = logging.getLogger(__name__)


class LLMRequestError(RuntimeError):
    """A real Anthropic API call failed. `status_code` is the caller-facing HTTP status this
    should map to: 429 when Anthropic itself rate-limited us, 502 for every other upstream
    failure (bad request rejected by Anthropic, invalid key, network error, ...)."""

    def __init__(self, detail: str, *, status_code: int) -> None:
        super().__init__(detail)
        self.detail = detail
        self.status_code = status_code


RATE_LIMITED_DETAIL = "The language-model provider is rate-limiting requests; retry later."
UPSTREAM_FAILED_DETAIL = "The language-model provider could not complete the request."


def wrap_anthropic_error(error: anthropic.APIError) -> LLMRequestError:
    """A fixed, generic detail per status class: upstream text can reveal billing state, organisation or
    model names and key hints, so it is logged on the server and never returned to the caller."""
    logger.warning("Anthropic API call failed: %s", error)
    if isinstance(error, anthropic.RateLimitError):
        return LLMRequestError(RATE_LIMITED_DETAIL, status_code=429)
    return LLMRequestError(UPSTREAM_FAILED_DETAIL, status_code=502)
