"""Anthropic API client construction for the explanation layer."""
from __future__ import annotations

import anthropic

from oah.config import Settings, load_settings


REQUEST_TIMEOUT_SECONDS = 30.0
# No hidden retries: the SDK would otherwise resend a failed request on its own, a provider call that no spend cap counts. A
# failure is reported once as a clean 502 (oah.explain.errors) and the caller decides whether to ask again.
MAX_RETRIES = 0


class LLMNotConfiguredError(RuntimeError):
    """Raised when no Anthropic API key is available to build a client."""


def build_client(settings: Settings | None = None) -> anthropic.Anthropic:
    """Build an Anthropic client from configured settings.

    Raises LLMNotConfiguredError rather than silently constructing a client
    that will fail on first use, so callers (the API layer, scripts) get an
    explicit, actionable error instead of a generic authentication failure.
    """
    resolved = settings or load_settings()
    if not resolved.anthropic_api_key:
        raise LLMNotConfiguredError(
            "ANTHROPIC_API_KEY is not set (checked .env and the process environment). "
            "The explanation layer cannot call the LLM without it."
        )
    # Bounded time and retries: a slow or failing upstream must not hold a request open or multiply spend.
    return anthropic.Anthropic(api_key=resolved.anthropic_api_key, timeout=REQUEST_TIMEOUT_SECONDS, max_retries=MAX_RETRIES)
