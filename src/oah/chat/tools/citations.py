"""Citations (the sources behind a tool result) and the origin label of a whole answer."""
from __future__ import annotations

from collections.abc import Sequence
from typing import Any

from oah.bathing_samples.constants import UNIT as SAMPLES_UNIT
from oah.chat import external_tools
from oah.chat.tools.results import ToolOutcome
from oah.chat.tools.samples import _SAMPLE_INDICATORS


MAX_CITATIONS = 40


def citations_for(outcome: ToolOutcome) -> list[dict[str, Any]]:
    """The sources behind a successful tool result: site, parameter, period, value and limit basis."""
    result = outcome.result
    if not outcome.ok or result is None:
        return []

    def entry(**fields: Any) -> dict[str, Any]:
        base: dict[str, Any] = {
            "tool": outcome.name, "site_id": None, "parameter": None, "period_start": None, "period_end": None,
            "value": None, "unit": None, "limit_basis": None, "source": result.get("origin"),
        }
        return {**base, **fields}

    if outcome.name in external_tools.EXTERNAL_TOOL_NAMES:
        return external_tools.citations(outcome.name, result, entry)
    if outcome.name == "get_site_measurements":
        found = []
        for record in result.get("records", []):
            value = record.get("value") or {}
            found.append(
                entry(
                    site_id=result.get("location_id"), parameter=record.get("parameter"),
                    period_start=record.get("period_start"), period_end=record.get("period_end"),
                    value=value.get("amount"), unit=value.get("unit"), limit_basis=record.get("limit_basis"),
                )
            )
        return found
    if outcome.name == "get_site_index":
        bases = result.get("limit_basis")
        if isinstance(bases, dict) and bases:
            return [entry(site_id=result.get("location_id"), parameter=name, limit_basis=text) for name, text in bases.items()]
        return [entry(site_id=result.get("location_id"))]
    if outcome.name == "compare_periods":
        scope = result.get("scope") or {}
        shown = result.get("results") if "results" in result else [result]
        found = []
        for item in shown or []:
            period_a, period_b = item.get("period_a") or {}, item.get("period_b") or {}
            mean = period_b.get("mean") or period_b.get("mean_of_site_means") or {}
            limit_check = period_b.get("limit_check") or item.get("river_limit_period_b") or {}
            found.append(
                entry(
                    site_id=scope.get("id") or scope.get("code"), parameter=item.get("parameter") or result.get("parameter"),
                    period_start=period_a.get("start"), period_end=period_b.get("end"), value=mean.get("amount"),
                    unit=mean.get("unit"), limit_basis=limit_check.get("limit_basis"),
                    source=item.get("source") or result.get("origin"),
                )
            )
        return found or [entry()]
    if outcome.name == "compare_bathing_seasons":
        return [
            entry(
                site_id=result.get("country"), parameter="Bathing water classification comparison",
                period_start=str(result.get("season_a")), period_end=str(result.get("season_b")),
            )
        ]
    if outcome.name == "get_bathing_samples":
        site_id = (result.get("bathing_water") or {}).get("id")
        filters = result.get("filters") or {}
        span = result.get("data_range") or {}
        return [
            entry(
                site_id=site_id, parameter=name, period_start=filters.get("date_from") or span.get("first_sample_date"),
                period_end=filters.get("date_to") or span.get("last_sample_date"),
                value=((result.get("summary") or {}).get(name, {}).get("mean") or {}).get("amount"), unit=SAMPLES_UNIT,
            )
            for name in _SAMPLE_INDICATORS
        ]
    if outcome.name == "compare_bathing_concentrations":
        scope = result.get("scope") or {}
        found = []
        for name, item in (result.get("indicators") or {}).items():
            period_a, period_b = item.get("period_a") or {}, item.get("period_b") or {}
            mean = period_b.get("mean") or period_b.get("mean_of_site_means") or {}
            found.append(
                entry(
                    site_id=scope.get("id") or scope.get("code"), parameter=name, period_start=period_a.get("start"),
                    period_end=period_b.get("end"), value=mean.get("amount"), unit=SAMPLES_UNIT,
                )
            )
        return found or [entry()]
    if outcome.name == "list_sites":
        return [entry(site_id=site.get("id")) for site in result.get("sites", [])]
    if outcome.name == "list_bathing_waters":
        return [entry(site_id=item.get("id")) for item in result.get("bathing_waters", [])]
    if outcome.name == "get_bathing_water_history":
        site_id = (result.get("bathing_water") or {}).get("id")
        return [
            entry(site_id=site_id, parameter="Bathing water classification", period_start=str(row.get("season")),
                  period_end=str(row.get("season")))
            for row in result.get("history", [])
        ]
    return [entry()]


def origin_for(outcomes: Sequence[ToolOutcome]) -> str:
    """The origin label of a whole answer: the one real source its tool results came from, else ``real-mixed``."""
    found = {str(o.result.get("origin")) for o in outcomes if o.ok and o.result is not None and o.result.get("origin")}
    if "real-mixed" in found or len(found) > 1:
        return "real-mixed"
    return next(iter(found)) if found else "real-sandbox"
