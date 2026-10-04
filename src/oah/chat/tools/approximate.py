"""The ``approximate`` block the statistics tools add next to their exact numbers (docs/chat_agent.md, "Approximate figures").

Presentation rounding only (``oah.chat.precision``): the exact numbers stay in the result, the block repeats them rounded
for the weight of the data behind them, with the observed range (lowest and highest value seen, rounded outward) and a
``low_precision`` flag with reason codes taken from facts the tools already carry (sample counts, flags, detection-limit
counts, paired sites). Every number is ``{amount, unit}`` so the grounding check still pairs it with its unit, and no digit
is written in a text field.
"""
from __future__ import annotations

from collections.abc import Iterable, Mapping
from typing import Any

from oah.chat import precision
from oah.chat.tools.results import _amount

def _number(node: Any) -> float | int | None:
    """The amount of an ``{amount, unit}`` node when it is a finite number (never a boolean)."""
    value = node.get("amount") if isinstance(node, Mapping) else None
    if isinstance(value, bool) or not isinstance(value, (int, float)):
        return None
    return value if value == value and abs(value) != float("inf") else None


def _unit(node: Any) -> Any:
    return node.get("unit") if isinstance(node, Mapping) else None


def _rounded(node: Any, figures: int, *, mode: precision.Mode = "nearest") -> dict[str, Any] | None:
    value = _number(node)
    return None if value is None else _amount(precision.round_figures(value, figures, mode), _unit(node))


def _approximate(node: Any, n: int | None, low: bool, observed: Mapping[str, Any] | None = None) -> dict[str, Any] | None:
    """The approximate form of ``node``, kept inside the (outward-rounded) observed range ``observed`` when there is one."""
    value = _number(node)
    if value is None:
        return None
    lower = _number((observed or {}).get("min"))
    upper = _number((observed or {}).get("max"))
    return _amount(precision.approximate_value(value, n, low_precision=low, lower=lower, upper=upper), _unit(node))


def _range(low_node: Any, high_node: Any, figures: int) -> dict[str, Any] | None:
    low, high = _number(low_node), _number(high_node)
    if low is None or high is None:
        return None
    low_out, high_out = precision.approximate_range(low, high, figures)
    return {"min": _amount(low_out, _unit(low_node)), "max": _amount(high_out, _unit(high_node))}


def _clean(parts: Mapping[str, Any]) -> dict[str, Any]:
    return {key: value for key, value in parts.items() if value not in (None, {}, [])}


def _block(figures: int, reasons: Iterable[str], parts: Mapping[str, Any]) -> dict[str, Any]:
    found = precision.distinct_reasons(reasons)
    return {
        "low_precision": bool(found), "reasons": found, "rounding": precision.figures_text(figures),
        "basis": precision.BASIS, **_clean(parts),
    }


def _smallest(counts: Iterable[Any]) -> int | None:
    known = [int(count) for count in counts if precision.is_count(count)]
    return min(known) if known else None


def _figures(n: int | None, reasons: Iterable[str]) -> int:
    return precision.significant_figures(n, low_precision=bool(list(reasons)))


def _change(change: Mapping[str, Any], n: int | None, low: bool) -> dict[str, Any]:
    """The change block with the same keys and the direction copied unchanged; the signs are kept by the rounding."""
    figures = precision.significant_figures(n, low_precision=low)
    return _clean(
        {
            "absolute": _rounded(change.get("absolute"), figures),
            "relative_percent": _rounded(change.get("relative_percent"), figures),
            "direction": change.get("direction"),
        }
    )


def _percent_share(node: Any) -> float | None:
    value = _number(node)
    return None if value is None else value / 100


def _mean_period(view: Mapping[str, Any], mean_key: str, low: bool, extra: Mapping[str, str]) -> dict[str, Any]:
    """One period of a block: the approximate mean (and median) kept inside the observed range, and that range."""
    n = view.get("n_samples")
    figures = precision.significant_figures(n if precision.is_count(n) else None, low_precision=low)
    observed = _range(view.get("min"), view.get("max"), figures)
    parts: dict[str, Any] = {mean_key: _approximate(view.get(mean_key), n, low, observed)}
    for out_key, source_key in extra.items():
        parts[out_key] = _approximate(view.get(source_key), n, low, observed)
    parts["observed_range"] = observed
    return _clean(parts)


# --- compare_periods ---------------------------------------------------------------------------------------------------------


def site_comparison_block(result: Mapping[str, Any]) -> dict[str, Any] | None:
    """The block of a site comparison (``compact_site_change`` output), or None when neither period has a mean."""
    views = {name: result.get(name) or {} for name in ("period_a", "period_b")}
    with_data = {name: view for name, view in views.items() if _number(view.get("mean")) is not None}
    if not with_data:
        return None
    flags = set(result.get("flags") or [])
    reasons: set[str] = set()
    for view in with_data.values():
        flags |= set(view.get("flags") or [])
        if precision.is_few_samples(view.get("n_samples")):
            reasons.add(precision.REASON_FEW_SAMPLES)
        if (share := _percent_share(view.get("below_loq_percent"))) is not None and share >= precision.BELOW_DETECTION_SHARE_THRESHOLD:
            reasons.add(precision.REASON_BELOW_DETECTION)
    if "partial-period" in flags:
        reasons.add(precision.REASON_PARTIAL_PERIOD)
    if "annual-only" in flags:
        reasons.add(precision.REASON_ANNUAL_ONLY)
    n = _smallest(view.get("n_samples") for view in with_data.values())
    low = bool(reasons)
    parts: dict[str, Any] = {
        name: _mean_period(view, "mean", low, {}) for name, view in with_data.items()
    }
    parts["change"] = _change(result.get("change") or {}, n, low)
    return _block(_figures(n, reasons), reasons, parts)


def country_comparison_block(entry: Mapping[str, Any]) -> dict[str, Any] | None:
    """The block of one country-comparison entry (one source), or None when neither period has a mean of site means."""
    views = {name: entry.get(name) or {} for name in ("period_a", "period_b")}
    with_data = {name: view for name, view in views.items() if _number(view.get("mean_of_site_means")) is not None}
    if not with_data:
        return None
    flags = set(entry.get("flags") or [])
    reasons: set[str] = set()
    for view in with_data.values():
        flags |= set(view.get("flags") or [])
        if precision.is_few_samples(view.get("n_samples")):
            reasons.add(precision.REASON_FEW_SAMPLES)
        if (share := _percent_share(view.get("below_loq_percent"))) is not None and share >= precision.BELOW_DETECTION_SHARE_THRESHOLD:
            reasons.add(precision.REASON_BELOW_DETECTION)
    paired, threshold = entry.get("n_sites_paired"), entry.get("few_sites_threshold")
    if "few-sites" in flags or (precision.is_count(paired) and precision.is_count(threshold) and paired < threshold):
        reasons.add(precision.REASON_FEW_SITES)
    if "partial-period" in flags:
        reasons.add(precision.REASON_PARTIAL_PERIOD)
    if "annual-only" in flags:
        reasons.add(precision.REASON_ANNUAL_ONLY)
    n = _smallest(view.get("n_samples") for view in with_data.values())
    low = bool(reasons)
    figures = _figures(n, reasons)
    parts: dict[str, Any] = {
        name: _clean({"mean_of_site_means": _approximate(view.get("mean_of_site_means"), n, low)})
        for name, view in with_data.items()
    }
    parts["change_of_site_means"] = _change(entry.get("change_of_site_means") or {}, n, low)
    parts["median_site_relative_change"] = _rounded(entry.get("median_site_relative_change"), figures)
    return _block(figures, reasons, parts)


# --- bathing samples ---------------------------------------------------------------------------------------------------------


def samples_summary_block(summary: Mapping[str, Any], flags: Iterable[str]) -> dict[str, Any] | None:
    """The block of ``get_bathing_samples``: one entry per indicator of the summary that has quantified values."""
    indicators: dict[str, Any] = {}
    for name, entry in summary.items():
        if not isinstance(entry, Mapping) or _number(entry.get("mean")) is None:
            continue
        n = entry.get("n_quantified")
        reasons: set[str] = set()
        if precision.is_few_samples(n):
            reasons.add(precision.REASON_FEW_SAMPLES)
        if precision.is_count(n) and precision.is_high_share(entry.get("n_detection_limit"), _sum(n, entry.get("n_detection_limit"))):
            reasons.add(precision.REASON_BELOW_DETECTION)
        if "partial-period" in set(flags):
            reasons.add(precision.REASON_PARTIAL_PERIOD)
        low = bool(reasons)
        figures = _figures(n, reasons)
        observed = _range(entry.get("min"), entry.get("max"), figures)
        indicators[name] = _block(
            figures, reasons,
            {
                "mean": _approximate(entry.get("mean"), n, low, observed),
                "median": _approximate(entry.get("median"), n, low, observed),
                "observed_range": observed,
            },
        )
    return {"basis": precision.BASIS, "indicators": indicators} if indicators else None


def _sum(first: Any, second: Any) -> int | None:
    return int(first) + int(second) if precision.is_count(first) and precision.is_count(second) else None


def samples_comparison_block(item: Mapping[str, Any], *, country_scope: bool) -> dict[str, Any] | None:
    """The block of one indicator of ``compare_bathing_concentrations`` (``item`` is the compacted indicator entry)."""
    mean_key, median_key = ("mean_of_site_means", "median_of_site_medians") if country_scope else ("mean", "median")
    views = {name: item.get(name) or {} for name in ("period_a", "period_b")}
    with_data = {name: view for name, view in views.items() if _number(view.get(mean_key)) is not None}
    if not with_data:
        return None
    flags = set(item.get("flags") or [])
    reasons: set[str] = set()
    detection_key = "n_detection_limit_all_sites" if country_scope else "n_detection_limit"
    for view in with_data.values():
        flags |= set(view.get("flags") or [])
        n_view = view.get("n_samples")
        if precision.is_few_samples(n_view):
            reasons.add(precision.REASON_FEW_SAMPLES)
        if precision.is_high_share(view.get(detection_key), _sum(n_view, view.get(detection_key))):
            reasons.add(precision.REASON_BELOW_DETECTION)
    if country_scope:
        paired, threshold = item.get("n_sites_paired"), item.get("few_sites_threshold")
        if "few-sites" in flags or (precision.is_count(paired) and precision.is_count(threshold) and paired < threshold):
            reasons.add(precision.REASON_FEW_SITES)
    if "partial-period" in flags:
        reasons.add(precision.REASON_PARTIAL_PERIOD)
    n = _smallest(view.get("n_samples") for view in with_data.values())
    low = bool(reasons)
    figures = _figures(n, reasons)
    parts: dict[str, Any] = {}
    for name, view in with_data.items():
        if country_scope:
            parts[name] = _clean(
                {
                    mean_key: _approximate(view.get(mean_key), n, low),
                    median_key: _approximate(view.get(median_key), n, low),
                }
            )
        else:
            parts[name] = _mean_period(view, mean_key, low, {median_key: median_key})
    if country_scope:
        parts["change_of_site_means"] = _change(item.get("change_of_site_means") or {}, n, low)
        parts["change_of_site_medians"] = _change(item.get("change_of_site_medians") or {}, n, low)
        parts["median_site_relative_change"] = _rounded(item.get("median_site_relative_change"), figures)
    else:
        parts["change_of_mean"] = _change(item.get("change_of_mean") or {}, n, low)
        parts["change_of_median"] = _change(item.get("change_of_median") or {}, n, low)
    return _block(figures, reasons, parts)


# --- get_site_measurements ---------------------------------------------------------------------------------------------------


def record_block(record: Mapping[str, Any], *, annual_aggregate_without_count: bool) -> dict[str, Any] | None:
    """The block of one compact measurement record, or None for a record that is not low precision, has no plain number or has a comparator.

    A Waterbase annual record carries its sample count ``n`` and ``n_below_loq``; a sandbox record carries neither and is an
    annual aggregate, so it is always low precision with the reason ``annual-only-data``.
    """
    value = record.get("value")
    if _number(value) is None or (isinstance(value, Mapping) and value.get("comparator")):
        return None
    n = record.get("n")
    reasons: set[str] = set()
    if annual_aggregate_without_count and not precision.is_count(n):
        reasons.add(precision.REASON_ANNUAL_ONLY)
    if precision.is_few_samples(n):
        reasons.add(precision.REASON_FEW_SAMPLES)
    if precision.is_high_share(record.get("n_below_loq"), _sum(n, record.get("n_below_loq"))):
        reasons.add(precision.REASON_BELOW_DETECTION)
    if not reasons:
        return None  # not low precision: the exact values are given as usual, nothing is added (keeps long lists short)
    known = n if precision.is_count(n) else None
    figures = _figures(known, reasons)
    observed = _range(record.get("min"), record.get("max"), figures)
    approx = _approximate(value, known, True, observed)
    if observed is not None and observed == {"min": record.get("min"), "max": record.get("max")}:
        observed = None  # the record's own minimum and maximum already are the observed range: not repeated
    return _clean({"low_precision": True, "reasons": precision.distinct_reasons(reasons), "value": approx, "observed_range": observed})


def measurements_block(records: Iterable[Mapping[str, Any]]) -> dict[str, Any]:
    """The result-level note of ``get_site_measurements``: the basis and the union of the reasons of the shown records."""
    reasons: set[str] = set()
    low = False
    for record in records:
        block = record.get("approximate")
        if isinstance(block, Mapping):
            reasons |= set(block.get("reasons") or [])
            low = low or bool(block.get("low_precision"))
    return {"low_precision": low, "reasons": precision.distinct_reasons(reasons), "basis": precision.BASIS}
