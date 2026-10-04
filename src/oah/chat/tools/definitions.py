"""The tool definitions the model sees (the Anthropic ``tools`` parameter) and which tools each index offers.

The JSON schemas and descriptions here are sent to the model: change them only on purpose (a test pins them).
"""
from __future__ import annotations

from collections.abc import Sequence
from typing import Any

from oah.chat import external_tools


INDEX_NAMES: tuple[str, ...] = ("water-quality", "water-parameters", "data-quality", "microbiology")


# --- tool definitions (the Anthropic ``tools`` parameter) ---------------------------------------------------

_LOCATION_PROPERTY = {"type": "string", "description": "Bare site id as returned by list_sites, for example Loc-Almyros."}

TOOL_DEFINITIONS: dict[str, dict[str, Any]] = {
    "list_countries": {
        "name": "list_countries",
        "description": "List the countries known to the backend with their limit regime, limit sources and site counts.",
        "input_schema": {"type": "object", "properties": {}, "additionalProperties": False},
    },
    "list_sites": {
        "name": "list_sites",
        "description": (
            "List the sites (ids, names, kind, source, CCME status) of one country, from the sandbox and from the EEA "
            "Waterbase store (river and lake sites with annual measurements and no index). Use it to find the site id "
            "behind a place name; pass a name query to narrow the list. Defaults to the selected country."
        ),
        "input_schema": {
            "type": "object",
            "properties": {
                "country": {"type": "string", "description": "Two-letter country code, for example GR."},
                "query": {"type": "string", "description": "Part of a site name, water body name or site id (at most 64 characters)."},
            },
            "additionalProperties": False,
        },
    },
    "get_site_index": {
        "name": "get_site_index",
        "description": (
            "CCME water quality index of one site: score, regime, country, the limit_basis of every parameter, "
            "confidence and data-quality counts. Not available for a site with no evaluable data (it then says why)."
        ),
        "input_schema": {
            "type": "object",
            "properties": {"location_id": _LOCATION_PROPERTY},
            "required": ["location_id"],
            "additionalProperties": False,
        },
    },
    "get_site_measurements": {
        "name": "get_site_measurements",
        "description": (
            "Per-parameter measurements of one site (sandbox records, or Waterbase annual aggregates with n, mean, min "
            "and max per year), each with its unit, period, the limit it was compared with, the limit_basis and a status. "
            "Filter by parameter and by an inclusive ISO date window."
        ),
        "input_schema": {
            "type": "object",
            "properties": {
                "location_id": _LOCATION_PROPERTY,
                "parameter": {"type": "string", "description": "Parameter name such as Nitrate, pH or Total phosphates."},
                "date_from": {"type": "string", "description": "ISO date YYYY-MM-DD, inclusive."},
                "date_to": {"type": "string", "description": "ISO date YYYY-MM-DD, inclusive."},
                "limit": {"type": "integer", "description": "Maximum records, 1 to 500 (default 50)."},
            },
            "required": ["location_id"],
            "additionalProperties": False,
        },
    },
    "get_qc_summary": {
        "name": "get_qc_summary",
        "description": (
            "Data-quality overview over all official records: counts of findings by type and of records left out "
            "(not specific to one country)."
        ),
        "input_schema": {"type": "object", "properties": {}, "additionalProperties": False},
    },
    "list_bathing_waters": {
        "name": "list_bathing_waters",
        "description": (
            "List EEA bathing waters (Bathing Water Directive status 2025) with the CLASSIFICATION of their latest season "
            "(for example 1 - Excellent). It is a classification, not a concentration: no E. coli or enterococci values "
            "exist in this data. Filter by country, a name or identifier fragment, the latest quality class and the water "
            "type (for example coastalBathingWater). Defaults to the selected country."
        ),
        "input_schema": {
            "type": "object",
            "properties": {
                "country": {"type": "string", "description": "Two-letter country code, for example GR."},
                "query": {"type": "string", "description": "Part of a bathing water name or identifier (at most 64 characters)."},
                "quality": {"type": "string", "description": "Latest-season class, for example Excellent or 1 - Excellent."},
                "type": {"type": "string", "description": "Water type as written in the file, for example coastalBathingWater."},
                "limit": {"type": "integer", "description": "Maximum bathing waters, 1 to 50 (default 20)."},
            },
            "additionalProperties": False,
        },
    },
    "get_bathing_water_history": {
        "name": "get_bathing_water_history",
        "description": (
            "Season-by-season classification of one bathing water (quality class, monitoring calendar, management status). "
            "A classification under Directive 2006/7/EC, not a concentration and not legal compliance."
        ),
        "input_schema": {
            "type": "object",
            "properties": {
                "bathing_water_id": {"type": "string", "description": "Identifier as returned by list_bathing_waters."},
            },
            "required": ["bathing_water_id"],
            "additionalProperties": False,
        },
    },
    "compare_periods": {
        "name": "compare_periods",
        "description": (
            "Compare one parameter between two periods at ONE site or across the sites of ONE country, using stored data "
            "only (deterministic arithmetic, no estimate). Each period is a range of calendar months YYYY-MM, both ends "
            "included. Returns per period the number of samples n_samples, the mean (sum over n of the quantified values), "
            "min, max, the values below the quantification limit and the limit with its limit_basis where the project has "
            "one, then the change (increase means mean_B minus mean_A as computed here), the direction and crossed_limit. "
            "A country comparison uses only the sites with enough samples in BOTH periods. Always read data_range and the "
            "flags: a period beyond the data is reported, never shifted. Sandbox sites have annual aggregates only "
            "(flag annual-only)."
        ),
        "input_schema": {
            "type": "object",
            "properties": {
                "scope": {"type": "string", "description": "site or country."},
                "id_or_country": {"type": "string", "description": "A site id from list_sites (scope site) or a two-letter country code (scope country)."},
                "parameter": {"type": "string", "description": "Parameter name such as Nitrate, Total phosphates, Turbidity or BOD5."},
                "a_from": {"type": "string", "description": "Start month of period A, YYYY-MM."},
                "a_to": {"type": "string", "description": "End month of period A, YYYY-MM, inclusive."},
                "b_from": {"type": "string", "description": "Start month of period B, YYYY-MM."},
                "b_to": {"type": "string", "description": "End month of period B, YYYY-MM, inclusive."},
            },
            "required": ["scope", "id_or_country", "parameter", "a_from", "a_to", "b_from", "b_to"],
            "additionalProperties": False,
        },
    },
    "compare_bathing_seasons": {
        "name": "compare_bathing_seasons",
        "description": (
            "Compare the bathing-water CLASSIFICATIONS of one country between two seasons: how many bathing waters moved "
            "up, down or stayed in the README's order excellent, good, sufficient, poor. Bathing waters whose class is not "
            "classified or good or sufficient in either season are counted separately as not comparable. A classification "
            "comparison, not a concentration; no threshold is involved."
        ),
        "input_schema": {
            "type": "object",
            "properties": {
                "country": {"type": "string", "description": "Two-letter country code, for example IT."},
                "season_a": {"type": "integer", "description": "First season, a year such as 2019."},
                "season_b": {"type": "integer", "description": "Second season, a year such as 2024."},
            },
            "required": ["country", "season_a", "season_b"],
            "additionalProperties": False,
        },
    },
    "get_bathing_samples": {
        "name": "get_bathing_samples",
        "description": (
            "Individual E. coli and intestinal enterococci results (cfu/100ml) of ONE bathing water of Greece or Italy, "
            "newest first, from the EEA bathing-water monitoring results, with a summary over all matching samples: "
            "counts, minimum, maximum, mean and median of the quantified values. Values flagged as below the limit of "
            "detection, missing or of unknown status are counted apart. These are measurements: no threshold, limit "
            "or classification is applied. Filter by an inclusive ISO date window and by season."
        ),
        "input_schema": {
            "type": "object",
            "properties": {
                "bathing_water_id": {"type": "string", "description": "Identifier as returned by list_bathing_waters."},
                "date_from": {"type": "string", "description": "ISO date YYYY-MM-DD, inclusive."},
                "date_to": {"type": "string", "description": "ISO date YYYY-MM-DD, inclusive."},
                "season": {"type": "integer", "description": "Bathing season, a year such as 2024."},
                "limit": {"type": "integer", "description": "Maximum samples listed, 1 to 100 (default 20); the summary covers all matches."},
            },
            "required": ["bathing_water_id"],
            "additionalProperties": False,
        },
    },
    "compare_bathing_concentrations": {
        "name": "compare_bathing_concentrations",
        "description": (
            "Compare the individual E. coli and intestinal enterococci results between two periods at ONE bathing water or "
            "across the bathing waters of ONE country (Greece or Italy), using stored data only (deterministic "
            "arithmetic). Each period is a range of calendar months YYYY-MM, both ends included. Returns per indicator and "
            "period n_samples, mean, median, min and max of the quantified values, the counts of flagged values, and the "
            "change of the mean and of the median (increase means B minus A as computed here). A country comparison uses "
            "only the bathing waters with enough samples in BOTH periods. Always read data_range and the flags: a period "
            "beyond the data is reported, never shifted. No significance is tested and no threshold or limit exists."
        ),
        "input_schema": {
            "type": "object",
            "properties": {
                "scope": {"type": "string", "description": "bathing_water or country."},
                "id_or_country": {"type": "string", "description": "A bathing water identifier (scope bathing_water) or a two-letter country code (scope country)."},
                "a_from": {"type": "string", "description": "Start month of period A, YYYY-MM."},
                "a_to": {"type": "string", "description": "End month of period A, YYYY-MM, inclusive."},
                "b_from": {"type": "string", "description": "Start month of period B, YYYY-MM."},
                "b_to": {"type": "string", "description": "End month of period B, YYYY-MM, inclusive."},
            },
            "required": ["scope", "id_or_country", "a_from", "a_to", "b_from", "b_to"],
            "additionalProperties": False,
        },
    },
}

TOOL_DEFINITIONS.update(external_tools.DEFINITIONS)
ALL_TOOLS: tuple[str, ...] = tuple(TOOL_DEFINITIONS)
# What each selected index may use. Without an index every tool is available.
TOOLS_BY_INDEX: dict[str, tuple[str, ...]] = {
    "water-quality": (
        "list_countries", "list_sites", "get_site_index", "get_site_measurements", "compare_periods",
        *external_tools.EXTERNAL_TOOL_NAMES,
    ),
    "water-parameters": (
        "list_countries", "list_sites", "get_site_measurements", "compare_periods", *external_tools.EXTERNAL_TOOL_NAMES
    ),
    "data-quality": ("list_sites", "get_qc_summary"),
    "microbiology": (
        "list_countries", "list_bathing_waters", "get_bathing_water_history", "compare_bathing_seasons",
        "get_bathing_samples", "compare_bathing_concentrations", external_tools.WEATHER_TOOL,
    ),
}


def allowed_tools(index: str | None) -> tuple[str, ...]:
    return ALL_TOOLS if index is None else TOOLS_BY_INDEX[index]


def tool_definitions(names: Sequence[str]) -> list[dict[str, Any]]:
    return [TOOL_DEFINITIONS[name] for name in names]
