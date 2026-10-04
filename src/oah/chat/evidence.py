"""A compact, bounded evidence summary of the tool results of one chat conversation (docs/chat_agent.md, "Evidence summary").

Built ONLY from the sanitised results of the tools the model called, never from model text, and only for a response whose
answer was withheld (``withheld-ungrounded`` or ``withheld``): the web app can then still show the DATA the agent consulted.

* few values (at most ``MAX_EXACT_VALUES``, 10) are listed exactly, each with its period;
* more values are summarised by the number of values, the lowest and the highest value seen and the first and last period.
  This is an OBSERVED range, not a statistical interval of any kind.

Every number is copied from the tool result unchanged (no rounding, no arithmetic: a minimum is picked, not computed). Free
text from providers is never carried: only names and ids the tool results already hold as sanitised fields (a site or
bathing-water name, an identifier), the parameter, the unit, the period labels, the origin label and the attribution. The
block is bounded (``MAX_EVIDENCE_ITEMS`` items, ``MAX_EVIDENCE_CHARS`` characters once serialised) and passed once more through
``oah.explain.safety.sanitize_evidence`` (the function the tool results go through), which cuts every string at 200 characters.
"""
from __future__ import annotations

import json
import math
from collections.abc import Callable, Mapping, Sequence
from typing import Any

from oah.chat.tools import ToolOutcome
from oah.explain.safety import sanitize_evidence

MAX_EVIDENCE_ITEMS = 20
MAX_EXACT_VALUES = 10
MAX_EVIDENCE_CHARS = 12_000
MAX_NAME_CHARS = 80

_SUMMARY_KIND = "observed-range"
_BATHING_INDICATORS = ("escherichia_coli", "intestinal_enterococci")


def _number(value: Any) -> float | int | None:
    if isinstance(value, bool) or not isinstance(value, (int, float)):
        return None
    return value if math.isfinite(value) else None


def _text(value: Any, limit: int = MAX_NAME_CHARS) -> str | None:
    return value[:limit] if isinstance(value, str) and value.strip() else None


def _count(value: Any) -> int | None:
    return value if isinstance(value, int) and not isinstance(value, bool) and value >= 0 else None


def _period(start: Any, end: Any) -> str | None:
    first, last = _text(start, 40), _text(end, 40)
    if first and last and first != last:
        return f"{first}/{last}"
    return first or last


def _entry(period: str | None, statistic: str | None, node: Any, n: Any = None) -> dict[str, Any] | None:
    """One value of a series, taken from an ``{amount, unit}`` node; None when there is no plain number."""
    amount = _number(node.get("amount")) if isinstance(node, Mapping) else None
    if amount is None:
        return None
    comparator = _text(node.get("comparator"), 4) if isinstance(node, Mapping) else None
    entry = {"period": period, "statistic": _text(statistic, 40), "value": amount, "n": _count(n), "comparator": comparator}
    return {key: value for key, value in entry.items() if value is not None}


def _summarise(entries: Sequence[Mapping[str, Any]]) -> dict[str, Any]:
    """The observed range of the uncensored values (a value with a comparator is counted apart, never taken for a result)."""
    plain = [entry for entry in entries if "comparator" not in entry]
    periods = sorted(str(entry["period"]) for entry in entries if "period" in entry)
    summary: dict[str, Any] = {"kind": _SUMMARY_KIND, "n": len(entries)}
    if plain:
        summary["minimum"] = min(entry["value"] for entry in plain)
        summary["maximum"] = max(entry["value"] for entry in plain)
    if len(plain) != len(entries):
        summary["n_censored"] = len(entries) - len(plain)
    if periods:
        summary["first_period"], summary["last_period"] = periods[0], periods[-1]
    return summary


def _series(entries: Sequence[dict[str, Any]]) -> dict[str, Any]:
    """Exact values when there are few, the observed-range summary when there are many."""
    if len(entries) <= MAX_EXACT_VALUES:
        return {"values": list(entries)}
    return {"summary": _summarise(entries)}


def _item(
    tool: str, result: Mapping[str, Any], scope: Mapping[str, Any], parameter: Any, unit: Any,
    entries: Sequence[dict[str, Any]], *, summary: dict[str, Any] | None = None, origin: Any = None, attribution: Any = None,
) -> dict[str, Any] | None:
    """One evidence item; None when it holds no value at all."""
    if not entries and summary is None:
        return None
    if summary is not None:
        labels = [str(summary[key]) for key in ("first_period", "last_period") if key in summary]
    else:
        labels = [str(entry["period"]) for entry in entries if "period" in entry]
    starts, ends = [label.split("/")[0] for label in labels], [label.split("/")[-1] for label in labels]
    span = (min(starts) if starts else None, max(ends) if ends else None)  # a label is a year, a month, a date or start/end
    item: dict[str, Any] = {
        "tool": tool,
        "scope": {key: value for key, value in scope.items() if value is not None},
        "parameter": _text(parameter),
        "unit": _text(unit, 40),
        "period": None if span[0] is None or span[1] is None else (span[0] if span[0] == span[1] else f"{span[0]}/{span[1]}"),
        "origin": _text(origin if origin is not None else result.get("origin"), 60),
        "attribution": _text(attribution if attribution is not None else result.get("attribution"), 200),
        "data_kind": _text(result.get("data_kind"), 60),
        **(({"summary": summary}) if summary is not None else _series(entries)),
    }
    return {key: value for key, value in item.items() if value is not None}


# --- one builder per tool family ---------------------------------------------------------------------------------------------


def _measurements(outcome: ToolOutcome, result: Mapping[str, Any]) -> list[dict[str, Any] | None]:
    groups: dict[tuple[str | None, str | None], list[dict[str, Any]]] = {}
    for record in result.get("records") or []:
        if not isinstance(record, Mapping):
            continue
        value = record.get("value")
        unit = value.get("unit") if isinstance(value, Mapping) else None
        year = record.get("year")
        label = str(year) if _count(year) is not None else _period(record.get("period_start"), record.get("period_end"))
        entry = _entry(label, record.get("statistic"), value, record.get("n"))
        if entry is not None:
            groups.setdefault((_text(record.get("parameter")), _text(unit, 40)), []).append(entry)
    scope = {"type": "site", "id": _text(result.get("location_id"))}
    return [
        _item(outcome.name, result, scope, parameter, unit, entries)
        for (parameter, unit), entries in groups.items()
    ]


def _site_scope(result: Mapping[str, Any]) -> dict[str, Any]:
    scope = result.get("scope") or {}
    return {"type": "site", "id": _text(scope.get("id")), "name": _text(scope.get("name"))}


def _means(view: Mapping[str, Any], key: str) -> dict[str, Any] | None:
    return _entry(_period(view.get("start"), view.get("end")), "mean", view.get(key), view.get("n_samples"))


def _comparison(outcome: ToolOutcome, result: Mapping[str, Any]) -> list[dict[str, Any] | None]:
    if "results" in result:  # country scope: one entry per source
        scope = result.get("scope") or {}
        found = []
        for item in result.get("results") or []:
            entries = [
                entry for entry in (_means(item.get(name) or {}, "mean_of_site_means") for name in ("period_a", "period_b"))
                if entry is not None
            ]
            found.append(
                _item(
                    outcome.name, item, {"type": "country", "id": _text(scope.get("code"), 8)},
                    item.get("parameter") or result.get("parameter"), item.get("unit"), entries,
                )
            )
        return found
    entries = [entry for entry in (_means(result.get(name) or {}, "mean") for name in ("period_a", "period_b")) if entry is not None]
    return [_item(outcome.name, result, _site_scope(result), result.get("parameter"), result.get("unit"), entries)]


def _bathing_samples(outcome: ToolOutcome, result: Mapping[str, Any]) -> list[dict[str, Any] | None]:
    site = result.get("bathing_water") or {}
    scope = {"type": "bathing-water", "id": _text(site.get("id")), "name": _text(site.get("name"))}
    unit = result.get("unit")
    truncated = bool(result.get("truncated"))
    summary = result.get("summary") or {}
    filters, span = result.get("filters") or {}, result.get("data_range") or {}
    found = []
    for name in _BATHING_INDICATORS:
        entries = []
        for row in result.get("samples") or []:
            value = ((row.get(name) or {}).get("value")) if isinstance(row, Mapping) else None
            entry = _entry(_text(row.get("date"), 40), "sample", value)
            if entry is not None:
                entries.append(entry)
        totals = summary.get(name) or {}
        minimum, maximum, count = _number((totals.get("min") or {}).get("amount")), _number((totals.get("max") or {}).get("amount")), _count(totals.get("n_quantified"))
        if truncated and count and minimum is not None and maximum is not None:
            # the rows are only the newest of many: say how many values the whole selection holds, not just the rows
            collected = {
                "kind": _SUMMARY_KIND, "n": count, "minimum": minimum, "maximum": maximum,
                "first_period": _text(filters.get("date_from") or span.get("first_sample_date"), 40),
                "last_period": _text(filters.get("date_to") or span.get("last_sample_date"), 40),
            }
            found.append(
                _item(outcome.name, result, scope, name, unit, entries,
                      summary={key: value for key, value in collected.items() if value is not None})
            )
        else:
            found.append(_item(outcome.name, result, scope, name, unit, entries))
    return found


def _concentrations(outcome: ToolOutcome, result: Mapping[str, Any]) -> list[dict[str, Any] | None]:
    scope_in = result.get("scope") or {}
    country = scope_in.get("type") == "country"
    scope = (
        {"type": "country", "id": _text(scope_in.get("code"), 8)} if country
        else {"type": "bathing-water", "id": _text(scope_in.get("id")), "name": _text(scope_in.get("name"))}
    )
    keys = (("mean_of_site_means", "mean"), ("median_of_site_medians", "median")) if country else (("mean", "mean"), ("median", "median"))
    found = []
    for name, item in (result.get("indicators") or {}).items():
        entries = []
        for period_name in ("period_a", "period_b"):
            view = item.get(period_name) or {}
            for key, statistic in keys:
                entry = _entry(_period(view.get("start"), view.get("end")), statistic, view.get(key), view.get("n_samples"))
                if entry is not None:
                    entries.append(entry)
        found.append(_item(outcome.name, result, scope, name, result.get("unit"), entries))
    return found


def _months(outcome: ToolOutcome, result: Mapping[str, Any], series: Sequence[tuple[str, str]]) -> list[dict[str, Any] | None]:
    site = result.get("site") or {}
    scope = {"type": "site", "id": _text(site.get("id")), "name": _text(site.get("name"))}
    found = []
    for key, statistic in series:
        entries: list[dict[str, Any]] = []
        unit = None
        for month in result.get("months") or []:
            if not isinstance(month, Mapping) or not isinstance(month.get(key), Mapping):
                continue
            node = month[key]
            entry = _entry(_text(month.get("month"), 10), statistic, node, node.get("n_days"))
            if entry is not None:
                entries.append(entry)
                unit = node.get("unit")
        found.append(_item(outcome.name, result, scope, key, unit, entries))
    return found


def _weather(outcome: ToolOutcome, result: Mapping[str, Any]) -> list[dict[str, Any] | None]:
    return _months(outcome, result, (("precipitation_sum", "monthly-sum"), ("temperature_mean", "monthly-mean")))


def _discharge(outcome: ToolOutcome, result: Mapping[str, Any]) -> list[dict[str, Any] | None]:
    return _months(outcome, result, (("discharge_mean", "monthly-mean"),))


_BUILDERS: dict[str, Callable[[ToolOutcome, Mapping[str, Any]], list[dict[str, Any] | None]]] = {
    "get_site_measurements": _measurements,
    "compare_periods": _comparison,
    "get_bathing_samples": _bathing_samples,
    "compare_bathing_concentrations": _concentrations,
    "get_weather_context": _weather,
    "get_river_discharge_context": _discharge,
}


def _size(items: Sequence[Mapping[str, Any]]) -> int:
    return len(json.dumps(items, sort_keys=True, default=str))


def build_evidence(outcomes: Sequence[ToolOutcome]) -> tuple[list[dict[str, Any]], bool]:
    """The evidence items of the successful tool results, in call order, and whether any were left out for the bound.

    Tools that return no figures (lists, classification, index, species) add nothing. Identical items (the same call made
    twice) are listed once.
    """
    items: list[dict[str, Any]] = []
    for outcome in outcomes:
        builder = _BUILDERS.get(outcome.name)
        if not outcome.ok or outcome.result is None or builder is None:
            continue
        for item in builder(outcome, outcome.result):
            if item is not None and item not in items:
                items.append(item)
    truncated = len(items) > MAX_EVIDENCE_ITEMS
    del items[MAX_EVIDENCE_ITEMS:]
    while items and _size(items) > MAX_EVIDENCE_CHARS:
        items.pop()
        truncated = True
    clean, _ = sanitize_evidence({"items": items})  # the same sanitiser as the tool results: control characters, instructions, URLs, 200 characters
    return list(clean["items"]), truncated
