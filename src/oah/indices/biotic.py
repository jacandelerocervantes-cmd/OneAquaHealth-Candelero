"""Biotic ecological indices for aquatic macroinvertebrates.

BMWP/ASPT/IBMWP tolerance tables are regional (e.g. UK BMWP vs Iberian IBMWP differ);
functions in this module take score tables as explicit inputs, never hardcoded.

References:
    Alba-Tercedor, J., & Sánchez-Ortega, A. (1988). Un método rápido y simple
    para evaluar la calidad biológica de las aguas corrientes. Limnetica, 4, 51-56.
"""

from __future__ import annotations

from typing import Mapping


def bmwp(family_tolerance_scores: Mapping[str, int]) -> int:
    """Calculate Biological Monitoring Working Party (BMWP/IBMWP) score.

    Args:
        family_tolerance_scores: Mapping of taxa family name to its regional tolerance score.

    Returns:
        Sum of tolerance scores for all families present in the sample.
    """
    if not family_tolerance_scores:
        return 0
    for family, score in family_tolerance_scores.items():
        if not isinstance(score, int) or isinstance(score, bool):
            raise TypeError(f"Tolerance score for '{family}' must be an integer.")
        if score < 1 or score > 10:
            raise ValueError(f"Tolerance score for '{family}' must be between 1 and 10, got {score}.")
    return sum(family_tolerance_scores.values())


def aspt(bmwp_score: int, family_count: int) -> float:
    """Calculate Average Score Per Taxon (ASPT).

    Args:
        bmwp_score: Total BMWP/IBMWP score.
        family_count: Number of families present in the sample.

    Returns:
        Average score per taxon (bmwp_score / family_count).

    Raises:
        ValueError: If family_count <= 0.
    """
    if family_count <= 0:
        raise ValueError("family_count must be a positive integer greater than zero.")
    return float(bmwp_score / family_count)


def ept_ratio(counts_by_order: Mapping[str, int]) -> float:
    """Calculate Ephemeroptera, Plecoptera, Trichoptera (EPT) abundance ratio.

    Args:
        counts_by_order: Mapping of order names to individual organism counts.

    Returns:
        Proportion of EPT individuals in total sample count, in range [0.0, 1.0].

    Raises:
        ValueError: If total count is zero or if any count is negative.
    """
    if not counts_by_order:
        raise ValueError("counts_by_order cannot be empty and total count must be greater than zero.")

    total = 0
    ept_count = 0
    for order_name, count in counts_by_order.items():
        if count < 0:
            raise ValueError(f"Count for order '{order_name}' cannot be negative, got {count}.")
        total += count
        if order_name.strip().lower() in ("ephemeroptera", "plecoptera", "trichoptera"):
            ept_count += count

    if total <= 0:
        raise ValueError("Total organism count across orders must be greater than zero.")

    return float(ept_count / total)
