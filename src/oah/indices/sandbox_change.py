"""Period comparison over the sandbox records: measurement records in, ``oah.indices.period_change`` results out.

The sandbox holds ANNUAL AGGREGATES (a period summary per Observation with a median or an average, a minimum and a
maximum), not samples and not months. This adapter never pretends otherwise (``docs/period_change.md``):

* an aggregate is placed on the calendar months its period covers (``first_month`` to ``last_month``) and counts as ONE
  record (``n_unit`` ``aggregate-records``); the result carries the flag ``annual-only``;
* an aggregate is used in a period only when the period contains ALL the months it covers; an aggregate that crosses
  the period edge is left out and counted (``n_records_excluded_crossing_period_edge``), never split or pro-rated;
* the value of an aggregate is its median (else its average), the ``statistic`` of the record; the "mean" of a period is
  the mean of those aggregate values, not a mean of samples;
* a censored record (``<`` or ``<=``) counts as below the limit of quantification and is not in the mean; any other
  comparator, an excluded record or a record without a readable period is left out and counted.
"""

from __future__ import annotations

import math
from collections.abc import Mapping, Sequence
from datetime import timedelta
from typing import Any

from oah.indices.period_change import (
    Cell,
    ParameterContext,
    Period,
    SiteContext,
    compare_country,
    compare_site,
    month_text,
)
from oah.indices.regimes import DEFAULT_REGIME, countries_by_location_ref, regimes_by_location_ref
from oah.indices.site_measurements import _period as _observation_period
from oah.indices.site_measurements import site_measurement_records
from oah.indices.water_parameter_limits import (
    PARAMETER_UNITS,
    is_health_measure_profile,
    is_water_profile,
    match_closed_parameter,
)
from oah.timeutil import TimeError, parse_fhir_time
from oah.waterbase.mapping import GROUP_WATER_CHEMISTRY

SOURCE_ID = "real-sandbox"


def _months(record: Mapping[str, Any]) -> tuple[int, int] | None:
    """The first and last calendar month (positions) a record's period covers, or None when it cannot be read."""
    start, end = record.get("period_start"), record.get("period_end")
    try:
        first = parse_fhir_time(str(start or end or "")).start
        last = parse_fhir_time(str(end or start or "")).end - timedelta(microseconds=1)
    except TimeError:
        return None
    first_position, last_position = first.year * 12 + first.month - 1, last.year * 12 + last.month - 1
    return (first_position, last_position) if first_position <= last_position else None


def records_to_cells(records: Sequence[Mapping[str, Any]], site_id: str) -> tuple[list[Cell], dict[str, Any]]:
    """``(cells, notes)``: one cell per usable record; ``notes`` counts what was left out and names the statistics used."""
    cells: list[Cell] = []
    left_out = {"excluded_records": 0, "unplaceable_records": 0, "unsupported_comparator_records": 0}
    statistics_used: set[str] = set()
    for record in records:
        value = record.get("value")
        if record.get("status") == "excluded" or isinstance(value, bool) or not isinstance(value, (int, float)) or not math.isfinite(value):
            left_out["excluded_records"] += 1
            continue
        span = _months(record)
        if span is None:
            left_out["unplaceable_records"] += 1
            continue
        comparator = record.get("comparator")
        if comparator in ("<", "<="):
            cells.append(Cell(site_id, span[0], span[1], 0, 0.0, None, None, 1, 0))  # below the limit of quantification
        elif comparator:
            left_out["unsupported_comparator_records"] += 1
        else:
            cells.append(Cell(site_id, span[0], span[1], 1, float(value), float(value), float(value), 0, 0))
            statistics_used.add(str(record.get("statistic") or "value"))
    return cells, {**left_out, "statistics_used": sorted(statistics_used)}


def parameter_context(parameter: str) -> ParameterContext:
    """A closed project parameter name (canonical case) as an annual-only parameter of the sandbox."""
    return ParameterContext(
        name=parameter, unit=PARAMETER_UNITS[parameter], group=GROUP_WATER_CHEMISTRY, closed_name=parameter,
        measurement_only=False, resolution="annual-only", source=SOURCE_ID,
    )


def _span(cells: Sequence[Cell]) -> tuple[int, int] | None:
    return (min(c.first_month for c in cells), max(c.last_month for c in cells)) if cells else None


def _site_context(locations: Sequence[dict[str, Any]], site_id: str) -> SiteContext:
    ref = f"Location/{site_id}"
    name = next((str(loc.get("name") or site_id) for loc in locations if loc.get("id") == site_id), site_id)
    return SiteContext(
        site_id, countries_by_location_ref(locations).get(ref), regimes_by_location_ref(locations).get(ref, DEFAULT_REGIME), name
    )


def site_change(
    observations: Sequence[dict[str, Any]], locations: Sequence[dict[str, Any]], site_id: str, parameter: str,
    period_a: Period, period_b: Period,
) -> dict[str, Any]:
    """One sandbox site's comparison; ``parameter`` is a canonical closed name (see ``parameter_names``)."""
    records = site_measurement_records(observations, locations, site_id, parameter)
    cells, notes = records_to_cells(records, site_id)
    result = compare_site(cells, parameter_context(parameter), _site_context(locations, site_id), period_a, period_b, data_range=_span(cells))
    return {**result, "record_notes": notes}


def country_change(
    observations: Sequence[dict[str, Any]], locations: Sequence[dict[str, Any]], country: str, parameter: str,
    period_a: Period, period_b: Period,
) -> dict[str, Any] | None:
    """The comparison of the sandbox sites of ``country`` (None when the sandbox has no Location of that country)."""
    by_ref = countries_by_location_ref(locations)
    site_ids = sorted(ref.removeprefix("Location/") for ref, found in by_ref.items() if found == country)
    if not site_ids:
        return None
    cells_by_site: dict[str, list[Cell]] = {}
    contexts: dict[str, SiteContext] = {}
    everything: list[Cell] = []
    left_out: dict[str, int] = {}
    for site_id in site_ids:
        cells, notes = records_to_cells(site_measurement_records(observations, locations, site_id, parameter), site_id)
        for key in ("excluded_records", "unplaceable_records", "unsupported_comparator_records"):
            left_out[key] = left_out.get(key, 0) + int(notes[key])
        if cells:
            cells_by_site[site_id] = cells
            contexts[site_id] = _site_context(locations, site_id)
            everything.extend(cells)
    result = compare_country(
        cells_by_site, contexts, parameter_context(parameter), country, period_a, period_b, data_range=_span(everything)
    )
    return {**result, "record_notes": left_out}


def country_ranges(
    observations: Sequence[dict[str, Any]], locations: Sequence[dict[str, Any]]
) -> dict[str, tuple[str, str]]:
    """``{country: (first month, last month)}`` of the water-profile Observations that match a closed parameter, per country.

    One pass over the Observations (the same selection as ``site_measurement_records``); a Location whose country
    cannot be told contributes to no country.
    """
    by_ref = countries_by_location_ref(locations)
    spans: dict[str, list[int]] = {}
    for obs in observations:
        country = by_ref.get(str((obs.get("subject") or {}).get("reference")))
        profiles = obs.get("meta", {}).get("profile", [])
        if country is None or is_health_measure_profile(profiles) or not is_water_profile(profiles):
            continue
        if match_closed_parameter(obs) is None:
            continue
        start, end = _observation_period(obs)
        span = _months({"period_start": start, "period_end": end})
        if span is not None:
            found = spans.setdefault(country, [span[0], span[1]])
            found[0], found[1] = min(found[0], span[0]), max(found[1], span[1])
    return {country: (month_text(first), month_text(last)) for country, (first, last) in sorted(spans.items())}
