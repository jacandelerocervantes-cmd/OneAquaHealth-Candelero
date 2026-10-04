"""Request and response models of ``POST /chat``."""
from __future__ import annotations

from typing import Any, Literal

from pydantic import BaseModel, Field, field_validator

from oah.api.schemas.common import ChatOrigin, DataFreshnessModel
from oah.api.schemas.language import LanguageFields


ChatIndex = Literal["water-quality", "water-parameters", "data-quality", "microbiology"]


class ChatTurn(BaseModel):
    """A prior turn sent back by the client. Untrusted: it is cleaned and given to the model as data only."""

    role: Literal["user", "assistant"]
    text: str = Field(..., min_length=1, max_length=500)


class ChatRequest(BaseModel):
    message: str = Field(..., min_length=1, max_length=500)
    country: str | None = Field(default=None, pattern=r"^[A-Za-z]{2}$")  # also checked against GET /countries
    index: ChatIndex | None = None
    history: list[ChatTurn] = Field(default_factory=list, max_length=6)
    # A language code of GET /languages (case-insensitive, "es" means es-MX). Omitted: OAH_DEFAULT_LANGUAGE ("en").
    # An unknown code is a 422 that lists the supported codes. Checked in the route, not here, so the list is in the message.
    language: str | None = Field(default=None, min_length=2, max_length=12)

    @field_validator("message")
    @classmethod
    def _not_blank(cls, value: str) -> str:
        if not value.strip():
            raise ValueError("message must not be blank")
        return value


# ``answered``: a grounded, safe answer. ``withheld``: unsafe (the flags say why). ``withheld-ungrounded``: a number or unit could
# not be traced to the tool results; no text is returned, the citations and steps still show what was consulted.
ChatStatus = Literal["answered", "budget-exceeded", "withheld", "withheld-ungrounded", "no-answer"]


class ChatStep(BaseModel):
    step: int  # the model call that requested the tool (1-based)
    tool: str
    arguments: dict[str, Any]  # schema keys only, bounded and sanitised
    ok: bool
    summary: str


class ChatCitation(BaseModel):
    """A tool result the answer may rest on (sources consulted, not a per-number attribution)."""

    tool: str
    site_id: str | None = None
    parameter: str | None = None
    period_start: str | None = None
    period_end: str | None = None
    value: float | None = None
    unit: str | None = None
    limit_basis: str | None = None
    source: str | None = None  # real-sandbox, real-eea-waterbase, real-eea-bathing-water or real-eea-bathing-samples


class ChatEvidenceScope(BaseModel):
    type: Literal["site", "country", "bathing-water"]
    id: str | None = None  # a site id, a two-letter country code or a bathing-water id, as the tool result gave it
    name: str | None = None  # a sanitised name the tool result already held (cut at 80 characters); never a remark


class ChatEvidenceValue(BaseModel):
    """One value copied unchanged from a tool result."""

    period: str | None = None  # a year, a month, a date or start/end (ISO), as the tool result gave it
    statistic: str | None = None  # for example mean, median, sample, monthly-sum
    value: int | float  # not rounded
    n: int | None = None  # the number of samples (or days) behind the value, when the tool result gave it
    comparator: str | None = None  # present when the value was reported as a bound (for example "<")


class ChatEvidenceSummary(BaseModel):
    """Many values: how many, the lowest and highest value seen and the first and last period. An OBSERVED range, not a
    statistical interval of any kind."""

    kind: Literal["observed-range"]
    n: int
    minimum: int | float | None = None
    maximum: int | float | None = None
    n_censored: int | None = None  # values reported as a bound, left out of minimum and maximum
    first_period: str | None = None
    last_period: str | None = None


class ChatEvidenceItem(BaseModel):
    """The data of one tool result the agent consulted, compactly: exactly one of ``values`` (at most 10) or ``summary``."""

    tool: str
    scope: ChatEvidenceScope
    parameter: str | None = None  # a parameter or an indicator name
    unit: str | None = None
    period: str | None = None  # first/last period of the values
    origin: str | None = None  # the origin label of the tool result (real-sandbox, real-eea-waterbase, ...)
    attribution: str | None = None  # the attribution text the tool result carried
    data_kind: str | None = None  # external context only (modelled or opportunistic)
    values: list[ChatEvidenceValue] | None = None
    summary: ChatEvidenceSummary | None = None


class ChatUsage(BaseModel):
    """What this conversation used. The process-wide remaining budget is deliberately not public."""

    model_calls: int  # used by this conversation
    max_steps: int
    input_tokens: int | None = None
    output_tokens: int | None = None


class ChatResponse(LanguageFields):
    """An AI-generated answer from read-only tool results. Not verified; never a potability, health or regulatory determination."""

    origin: ChatOrigin  # the source(s) the tool results came from: a real source, an external context, or real-mixed
    status: ChatStatus
    answer: str | None  # in the answer language (or the English fallback); null when withheld (unsafe or not grounded)
    country: str | None = None
    index: ChatIndex | None = None
    steps: list[ChatStep]
    citations: list[ChatCitation]
    # The data the agent consulted, built by the backend from the tool results (never from model text): present ONLY when the
    # status is withheld-ungrounded or withheld, null otherwise. At most 20 items; a short series is listed exactly, a long one
    # is summarised by its observed range. Numbers are copied unchanged.
    evidence: list[ChatEvidenceItem] | None = None
    evidence_truncated: bool = False  # true when items were left out to keep the block within its bounds
    data_freshness: DataFreshnessModel
    grounded: bool
    ungrounded_numbers: list[str]
    unit_mismatches: list[str]
    unsafe: bool
    output_flags: list[str]
    input_notes: list[str]  # what was removed or cut from the question and history
    disclaimer: str
    model: str
    usage: ChatUsage
    cached: bool
