"""Season-to-season comparison of the bathing-water CLASSIFICATION (never a concentration).

ONLY the order the archive's README names is used: ``excellent``, ``good``, ``sufficient``, ``poor`` (best first). The
file also holds ``0 - Not classified`` and ``3 - Good or Sufficient``, which the README does not explain: a bathing water
with either (or with a blank or unknown class) in one of the two seasons is NOT comparable, is counted separately and
never enters a transition. No concentration, no threshold and no meaning beyond the order is used. A bathing water that
has a classification row in only one of the two seasons is counted as such and never imputed.

``compare_seasons`` is pure; ``season_change`` reads the store (``oah.bathing.store``).
"""

from __future__ import annotations

from collections.abc import Mapping
from typing import Any

from oah.bathing import store
from oah.bathing.constants import quality_class

ORDER: tuple[str, ...] = ("Excellent", "Good", "Sufficient", "Poor")  # the README's four categories, best first
_RANK = {label.lower(): position for position, label in enumerate(ORDER)}  # 0 is the best class


def rank_of(quality: str | None) -> int | None:
    """The position of a class in ``ORDER`` (0 = best), or None when it is not one of the README's four categories."""
    label = quality_class(quality)
    return _RANK.get(label.lower()) if label is not None else None


def compare_seasons(
    pairs: Mapping[tuple[str, str], int], totals_a: Mapping[str, int], totals_b: Mapping[str, int]
) -> dict[str, Any]:
    """Transition counts from the grouped ``(quality in A, quality in B) -> count`` of the bathing waters present in both seasons."""
    transitions: dict[tuple[int, int], int] = {}
    not_comparable: list[dict[str, Any]] = []
    for (quality_a, quality_b), count in sorted(pairs.items()):
        rank_a, rank_b = rank_of(quality_a), rank_of(quality_b)
        if rank_a is None or rank_b is None:
            not_comparable.append({"quality_a": quality_a, "quality_b": quality_b, "count": count})
        else:
            transitions[(rank_a, rank_b)] = transitions.get((rank_a, rank_b), 0) + count
    moved_up = sum(count for (a, b), count in transitions.items() if b < a)  # a smaller rank is a better class
    moved_down = sum(count for (a, b), count in transitions.items() if b > a)
    unchanged = sum(count for (a, b), count in transitions.items() if a == b)
    paired = sum(pairs.values())
    total_a, total_b = sum(totals_a.values()), sum(totals_b.values())
    return {
        "paired_bathing_waters": paired,
        "comparable": moved_up + moved_down + unchanged,
        "moved_up": moved_up,
        "moved_down": moved_down,
        "unchanged": unchanged,
        "transitions": [
            {"from_class": ORDER[a], "to_class": ORDER[b], "count": count} for (a, b), count in sorted(transitions.items())
        ],
        "not_comparable": {"count": sum(item["count"] for item in not_comparable), "pairs": not_comparable},
        "only_in_season_a": total_a - paired,
        "only_in_season_b": total_b - paired,
    }


def season_change(country: str, season_a: int, season_b: int, water_type: str | None = None) -> dict[str, Any]:
    """The comparison for one country (EL is read as GR) and two seasons, with the totals of each season and the data range."""
    code = store.normalise_country(country)
    status = store.store_status()
    summary = next((item for item in store.countries_summary() if item.country == code), None)
    totals_a = store.season_class_counts(code, season_a, water_type)
    totals_b = store.season_class_counts(code, season_b, water_type)
    pairs = store.season_pair_counts(code, season_a, season_b, water_type)
    flags: list[str] = []
    if not status.ready:
        flags.append("store-not-ready")
    elif summary is None:
        flags.append("no-bathing-water-data-for-country")
    elif not summary.first_season <= season_a <= summary.latest_season or not summary.first_season <= season_b <= summary.latest_season:
        flags.append("season-outside-data")
    if status.ready and (not totals_a or not totals_b) and "no-bathing-water-data-for-country" not in flags:
        flags.append("season-without-classifications")
    result = compare_seasons(pairs, totals_a, totals_b)
    return {
        "country": code,
        "type": water_type.strip() if water_type and water_type.strip() else None,
        "season_a": season_a,
        "season_b": season_b,
        "order": list(ORDER),
        "data_range": {
            "first_season": summary.first_season if summary else None,
            "last_season": summary.latest_season if summary else None,
        },
        "totals": {
            "a": {"season": season_a, "bathing_waters": sum(totals_a.values()), "classes": dict(totals_a)},
            "b": {"season": season_b, "bathing_waters": sum(totals_b.values()), "classes": dict(totals_b)},
        },
        **result,
        "flags": sorted(set(flags)),
    }
