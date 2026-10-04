"""Ecological diversity indices for community structure and richness estimation.

References:
    Chao, A., & Jost, L. (2012). Coverage-based rarefaction and extrapolation:
    standardizing samples by completeness rather than size. Ecology, 93(12), 2533-2547.
"""

from __future__ import annotations

import math
from typing import Mapping


def shannon(counts: Mapping[str, int]) -> float:
    """Calculate Shannon-Wiener diversity index H'.

    Formula: H' = - sum(p_i * ln(p_i))

    Args:
        counts: Mapping of species/taxa names to abundance counts.

    Returns:
        Shannon index float >= 0.0. Single-species or empty sample returns 0.0.

    Raises:
        ValueError: If any count is negative.
    """
    if not counts:
        return 0.0

    total = 0
    positive_counts = []
    for taxon, count in counts.items():
        if count < 0:
            raise ValueError(f"Count for taxon '{taxon}' cannot be negative, got {count}.")
        if count > 0:
            total += count
            positive_counts.append(count)

    if total == 0 or len(positive_counts) <= 1:
        return 0.0

    h_prime = 0.0
    for count in positive_counts:
        p_i = count / total
        h_prime -= p_i * math.log(p_i)

    return max(0.0, float(h_prime))


def simpson(counts: Mapping[str, int]) -> float:
    """Calculate Simpson's Index of Diversity 1 - D.

    Formula: 1 - sum(p_i^2)

    Args:
        counts: Mapping of species/taxa names to abundance counts.

    Returns:
        Simpson diversity float in range [0.0, 1.0). Single-species sample returns 0.0.

    Raises:
        ValueError: If any count is negative.
    """
    if not counts:
        return 0.0

    total = 0
    positive_counts = []
    for taxon, count in counts.items():
        if count < 0:
            raise ValueError(f"Count for taxon '{taxon}' cannot be negative, got {count}.")
        if count > 0:
            total += count
            positive_counts.append(count)

    if total == 0 or len(positive_counts) <= 1:
        return 0.0

    sum_p_sq = sum((count / total) ** 2 for count in positive_counts)
    diversity = 1.0 - sum_p_sq
    return max(0.0, min(0.999999999999999, float(diversity)))


def pielou(counts: Mapping[str, int]) -> float:
    """Calculate Pielou's Evenness index J'.

    Formula: J' = H' / ln(S)

    Args:
        counts: Mapping of species/taxa names to abundance counts.

    Returns:
        Pielou's evenness float in range (0.0, 1.0].

    Raises:
        ValueError: If species richness S (number of taxa with count > 0) is < 2.
    """
    positive_counts = {t: c for t, c in counts.items() if c > 0}
    richness = len(positive_counts)
    if richness < 2:
        raise ValueError(f"Pielou's evenness requires at least 2 distinct species, got richness = {richness}.")

    h_prime = shannon(counts)
    ln_s = math.log(richness)
    j_prime = h_prime / ln_s
    return max(0.0, min(1.0, float(j_prime)))


def chao1(observed_richness: int, singletons: int, doubletons: int) -> float:
    """Calculate Chao1 bias-corrected species richness estimator.

    Formula: S_Chao1 = S_obs + (f1 * (f1 - 1)) / (2 * (f2 + 1))

    References:
        Chao & Jost (2012). Coverage-based rarefaction and extrapolation. Ecology, 93(12).

    Args:
        observed_richness: S_obs, total number of observed species/taxa.
        singletons: f1, number of species represented by exactly 1 individual.
        doubletons: f2, number of species represented by exactly 2 individuals.

    Returns:
        Estimated species richness float >= observed_richness.

    Raises:
        ValueError: If observed_richness < 0, singletons < 0, or doubletons < 0.
    """
    if observed_richness < 0:
        raise ValueError(f"observed_richness cannot be negative, got {observed_richness}.")
    if singletons < 0:
        raise ValueError(f"singletons cannot be negative, got {singletons}.")
    if doubletons < 0:
        raise ValueError(f"doubletons cannot be negative, got {doubletons}.")

    f1 = float(singletons)
    f2 = float(doubletons)
    additional = (f1 * (f1 - 1.0)) / (2.0 * (f2 + 1.0))
    estimated = float(observed_richness) + max(0.0, additional)
    return max(float(observed_richness), estimated)
