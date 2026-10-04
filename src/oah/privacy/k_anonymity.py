"""k-Anonymity privacy enforcement on record sets.

References:
    Sweeney, L. (2002). k-Anonymity: A model for protecting privacy.
    International Journal of Uncertainty, Fuzziness and Knowledge-Based Systems, 10(05), 557-570.
"""

from __future__ import annotations

from collections import Counter
from typing import Any, Sequence


def enforce_k_anonymity(
    records: Sequence[dict[str, Any]],
    quasi_identifiers: Sequence[str],
    k: int = 5,
) -> list[dict[str, Any]]:
    """Enforce k-anonymity on a set of records with respect to quasi-identifiers.

    Args:
        records: Sequence of record dictionaries.
        quasi_identifiers: Sequence of attribute keys acting as quasi-identifiers.
        k: Minimum required group size (default 5).

    Returns:
        The input list of records if all equivalence classes have at least k records.

    Raises:
        ValueError: If k < 1 or if any equivalence class has fewer than k records,
            listing all violating groups with their keys and counts.
    """
    if k < 1:
        raise ValueError(f"k must be at least 1, got {k}.")

    if not records or k == 1:
        return list(records)

    groups: Counter[tuple[Any, ...]] = Counter()
    for rec in records:
        key = tuple(rec.get(q) for q in quasi_identifiers)
        groups[key] += 1

    violating_groups = {key: count for key, count in groups.items() if count < k}

    if violating_groups:
        details = ", ".join(
            f"{dict(zip(quasi_identifiers, key))}: count={count}"
            for key, count in sorted(violating_groups.items(), key=lambda item: str(item[0]))
        )
        raise ValueError(
            f"k-anonymity (k={k}) violated for {len(violating_groups)} equivalence class(es): {details}"
        )

    return list(records)
