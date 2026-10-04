"""Presentation rounding of the figures the chat agent states (docs/chat_agent.md, "Approximate figures").

This is NOT statistical uncertainty. Nothing here estimates a standard error, a confidence interval or a significance:
it only decides how many significant figures a number is SHOWN with, so a weak summary (few samples, a partial period,
many values below the detection limit, few paired sites, annual-only data) is not written as ``0.340954``. The exact number
always stays in the tool result next to the approximate one, and the only "interval" a result ever carries is the OBSERVED
range (the lowest and highest value seen, rounded outward so it still contains every observed value).

Policy (working values, not measured; change them here and in the documentation together):

* ``n >= LARGE_SAMPLE_COUNT`` (20): ``FIGURES_LARGE`` (3) significant figures;
* ``MEDIUM_SAMPLE_COUNT`` (5) to 19: ``FIGURES_SMALL`` (2);
* fewer than 5, or any weakness reason: ``FIGURES_SMALL`` (2) and the result is flagged ``low_precision``.

The number of figures never decreases as ``n`` grows. Rounding is half away from zero (``ROUND_HALF_UP``), so the sign of a
value (an increase or a decrease) is kept, and a nonzero value is never rounded to zero (at least two significant figures
are kept). An approximate mean is never allowed to leave the observed minimum and maximum: more figures are used until it
lies inside them (the exact value in the worst case).
"""
from __future__ import annotations

import math
from collections.abc import Iterable
from decimal import ROUND_CEILING, ROUND_FLOOR, ROUND_HALF_UP, Context, Decimal
from typing import Literal, TypeGuard

LARGE_SAMPLE_COUNT = 20
MEDIUM_SAMPLE_COUNT = 5
FIGURES_LARGE = 3
FIGURES_SMALL = 2
BELOW_DETECTION_SHARE_THRESHOLD = 0.25  # a quarter or more of the values below the detection or quantification limit
MAX_FIGURES = 17  # beyond this a float carries no more information

REASON_FEW_SAMPLES = "few-samples-in-a-period"
REASON_PARTIAL_PERIOD = "partial-period"
REASON_BELOW_DETECTION = "high-below-detection-share"
REASON_FEW_SITES = "few-paired-sites"
REASON_ANNUAL_ONLY = "annual-only-data"

BASIS = (
    "Presentation rounding of the exact numbers, not a statistical uncertainty. The observed range is the lowest and "
    "highest value seen, not a confidence interval."
)

_FIGURES_TEXT = {FIGURES_SMALL: "two significant figures", FIGURES_LARGE: "three significant figures"}
_CONTEXT = Context(prec=60)

Mode = Literal["nearest", "down", "up"]
_ROUNDING = {"nearest": ROUND_HALF_UP, "down": ROUND_FLOOR, "up": ROUND_CEILING}


def figures_text(figures: int) -> str:
    """The rounding in words (digits are avoided on purpose: a digit in a tool result is a number the grounding check accepts)."""
    return _FIGURES_TEXT.get(figures, "presentation rounding")


def is_count(value: object) -> TypeGuard[int]:
    return isinstance(value, int) and not isinstance(value, bool) and value >= 0


def is_few_samples(n: object) -> bool:
    """True when ``n`` is a count below ``MEDIUM_SAMPLE_COUNT`` (an unknown count is not called few: nothing is claimed)."""
    return is_count(n) and n < MEDIUM_SAMPLE_COUNT


def is_high_share(count: object, total: object) -> bool:
    """True when ``count`` of ``total`` values reaches ``BELOW_DETECTION_SHARE_THRESHOLD``."""
    if not (is_count(count) and is_count(total)) or total <= 0:
        return False
    return count / total >= BELOW_DETECTION_SHARE_THRESHOLD


def significant_figures(n: int | None, *, low_precision: bool = False) -> int:
    """How many significant figures a value summarising ``n`` samples is shown with (never fewer for a larger ``n``)."""
    if low_precision or not is_count(n) or n < LARGE_SAMPLE_COUNT:
        return FIGURES_SMALL
    return FIGURES_LARGE


def round_figures(value: float | int, figures: int, mode: Mode = "nearest") -> float | int:
    """``value`` rounded to ``figures`` significant figures: ``nearest`` (half away from zero), ``down`` or ``up``.

    Zero stays zero; the sign is kept; a nonzero value never becomes zero. An integer input gives an integer when the
    rounded value is whole. Raises ``ValueError`` for a boolean, NaN, infinity or ``figures`` below 1.
    """
    if isinstance(value, bool) or not isinstance(value, (int, float)) or not math.isfinite(value) or figures < 1:
        raise ValueError("a finite number and at least one significant figure are required")
    if value == 0:
        return 0 if isinstance(value, int) else 0.0
    exact = Decimal(repr(value)) if isinstance(value, float) else Decimal(value)
    quantum = Decimal(1).scaleb(exact.adjusted() - figures + 1)
    rounded = exact.quantize(quantum, rounding=_ROUNDING[mode], context=_CONTEXT)
    if isinstance(value, int) and rounded == rounded.to_integral_value():
        return int(rounded)
    return float(rounded)


def approximate_value(
    value: float | int, n: int | None, *, low_precision: bool = False,
    lower: float | int | None = None, upper: float | int | None = None,
) -> float | int:
    """The approximate form of ``value`` for ``n`` samples; inside ``[lower, upper]`` (the observed range) when given.

    If rounding would step outside the observed range (a mean of 0.9996 with a maximum of 0.9998 rounds to 1.0), more
    significant figures are used until the number lies inside; the exact value is the last resort.
    """
    figures = significant_figures(n, low_precision=low_precision)
    while figures <= MAX_FIGURES:
        candidate = round_figures(value, figures)
        if (lower is None or candidate >= lower) and (upper is None or candidate <= upper):
            return candidate
        figures += 1
    return value


def approximate_range(low: float | int, high: float | int, figures: int) -> tuple[float | int, float | int]:
    """The observed range rounded OUTWARD (minimum down, maximum up), so it still contains every observed value."""
    return round_figures(low, figures, "down"), round_figures(high, figures, "up")


def distinct_reasons(reasons: Iterable[str]) -> list[str]:
    return sorted(set(reasons))
