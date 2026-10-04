"""Water quality indices and Ecological Quality Ratio (EQR) classification.

References:
    Canadian Council of Ministers of the Environment (CCME). (2001).
    Canadian Water Quality Index 1.0: Technical Report. CCME, Winnipeg.
"""

from __future__ import annotations

import math
from typing import Sequence


def _is_lower_bound_parameter(parameter: str) -> bool:
    """Determine whether objective_limit for a parameter is a lower-bound threshold."""
    param_clean = parameter.strip().lower().replace(" ", "_")
    return (
        param_clean.endswith("_min")
        or "lower" in param_clean
        or param_clean in ("do", "dissolved_oxygen", "oxygen", "ph_min")
    )


def _require_finite(*values: float) -> None:
    """Reject NaN and infinity: a non-finite measurement must be excluded by the caller, never scored."""
    if not all(math.isfinite(value) for value in values):
        raise ValueError(f"observed values and limits must be finite numbers, got {values}.")


def excursion(observed: float, limit: float, is_lower: bool) -> float:
    """CCME 2001 excursion of one test: 0 when the objective is met, else the relative departure.

    Upper-limit parameter fails when ``observed > limit`` (excursion ``observed/limit - 1``);
    lower-limit parameter (e.g. dissolved oxygen) fails when ``observed < limit`` (excursion
    ``limit/observed - 1``). A non-positive divisor yields the sentinel 999.0.

    Raises:
        ValueError: If ``observed`` or ``limit`` is NaN or infinite. Comparisons with NaN are always
            false, so a non-finite value would otherwise be scored as a pass or corrupt F3.
    """
    _require_finite(observed, limit)
    if is_lower:
        if observed >= limit:
            return 0.0
        return 999.0 if observed <= 0 else (limit / observed) - 1.0
    if observed <= limit:
        return 0.0
    return 999.0 if limit <= 0 else (observed / limit) - 1.0


def ccme_wqi(measurements: Sequence[tuple[str, float, float] | tuple[str, float, float, bool]]) -> float:
    """Calculate Canadian Council of Ministers of the Environment Water Quality Index (CCME WQI 1.0).

    Implements CCME 2001 F1 (Scope), F2 (Frequency), and F3 (Amplitude) calculations.

    Args:
        measurements: Sequence of (parameter_name, observed_value, objective_limit) triples, or
            quadruples that add ``is_lower`` (True when the limit is a minimum, e.g. dissolved
            oxygen). Callers that know the direction MUST pass the quadruple; triples fall back to
            a name-based guess (``_is_lower_bound_parameter``), which is only a convenience.

    Returns:
        CCME WQI score float in range [0.0, 100.0].

    Raises:
        ValueError: If measurements sequence is empty, or any observed value or limit is NaN or
            infinite (callers must exclude and count such values before scoring).

    Notes:
        Cross-referenced against `docs/audit/OneAquaHealth_Informe_Auditado.md` appendix and CCME 2001:
        - F1 is the percentage of failed parameters (variables) out of total parameters measured.
        - F2 is the percentage of failed tests (measurements) out of total tests conducted.
        - Excursions are calculated as (observed / limit) - 1 for upper bounds and (limit / observed) - 1
          for lower bounds (e.g. dissolved oxygen).
        - nse (normalized sum of excursions) is normalized by total tests M_t.
        - F3 = nse / (0.01 * nse + 0.01).
        - CCME WQI = 100 - sqrt(F1^2 + F2^2 + F3^2) / 1.732.
    """
    if not measurements:
        raise ValueError("measurements sequence cannot be empty.")

    all_parameters = set()
    failed_parameters = set()

    total_tests = len(measurements)
    failed_tests = 0
    sum_excursions = 0.0

    for measurement in measurements:
        param, observed, limit = measurement[0], measurement[1], measurement[2]
        param_key = param.strip()
        all_parameters.add(param_key)

        is_lower = measurement[3] if len(measurement) == 4 else _is_lower_bound_parameter(param_key)
        excess = excursion(observed, limit, is_lower)
        failed = (observed < limit) if is_lower else (observed > limit)

        if failed:
            failed_parameters.add(param_key)
            failed_tests += 1
            sum_excursions += excess

    m_v = len(all_parameters)
    u_v = len(failed_parameters)
    f1 = float((u_v / m_v) * 100.0) if m_v > 0 else 0.0

    m_t = float(total_tests)
    u_t = float(failed_tests)
    f2 = float((u_t / m_t) * 100.0) if m_t > 0 else 0.0

    nse = sum_excursions / m_t if m_t > 0 else 0.0
    f3 = (nse / (0.01 * nse + 0.01)) if nse > 0 else 0.0

    vector_sum = math.sqrt(f1**2 + f2**2 + f3**2)
    wqi = 100.0 - (vector_sum / 1.732)
    return max(0.0, min(100.0, float(wqi)))


def classify_ccme_wqi(score: float) -> str:
    """Classify a CCME WQI 1.0 score into its five official bands (CCME 2001, Table 3):
    Excellent [95-100], Good [80-95), Fair [65-80), Marginal [45-65), Poor [0-45).

    Raises:
        ValueError: If score is outside [0.0, 100.0].
    """
    if not 0.0 <= score <= 100.0:
        raise ValueError(f"score must be in [0.0, 100.0], got {score}.")
    if score >= 95.0:
        return "Excellent"
    if score >= 80.0:
        return "Good"
    if score >= 65.0:
        return "Fair"
    if score >= 45.0:
        return "Marginal"
    return "Poor"


def eqr(observed: float, reference: float) -> tuple[float, str]:
    """Calculate Ecological Quality Ratio (EQR) and classify per EU Water Framework Directive (WFD).

    Args:
        observed: Observed index or metric value >= 0.0.
        reference: Reference benchmark metric value > 0.0.

    Returns:
        Tuple of (eqr_ratio, wfd_class_string).

    Raises:
        ValueError: If reference <= 0.0 or observed < 0.0.
    """
    _require_finite(observed, reference)
    if reference <= 0.0:
        raise ValueError(f"reference value must be strictly positive (> 0.0), got {reference}.")
    if observed < 0.0:
        raise ValueError(f"observed value cannot be negative, got {observed}.")

    ratio = float(observed / reference)

    if ratio >= 0.8:
        wfd_class = "High"
    elif ratio >= 0.6:
        wfd_class = "Good"
    elif ratio >= 0.4:
        wfd_class = "Moderate"
    elif ratio >= 0.2:
        wfd_class = "Poor"
    else:
        wfd_class = "Bad"

    return ratio, wfd_class
