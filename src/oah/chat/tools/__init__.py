"""Read-only tools the chat agent may call, as thin wrappers over existing service functions.

Rules (docs/chat_agent.md):

* no tool writes, exports FHIR or reaches a synthetic route; the model only ever gets the fourteen tools below;
* data comes from four labelled real sources, the sandbox (``real-sandbox``), the EEA Waterbase store
  (``real-eea-waterbase``: annual aggregates, rivers and lakes of GR, IT and NO), the EEA bathing-water store
  (``real-eea-bathing-water``: per-season CLASSIFICATION, never a concentration) and the EEA bathing-water SAMPLES
  store (``real-eea-bathing-samples``: individual E. coli and enterococci results, no threshold); each result and each
  record says which, and they are never merged into one figure. Three more tools (``oah.chat.external_tools``) give EXTERNAL
  context around a site (``external-open-meteo``: MODELLED weather and river discharge; ``external-gbif``: OPPORTUNISTIC
  species records), never the site's own measurements and never evidence of causation;
* inputs are validated with the same bounds as the REST routes (closed parameter names, ISO dates, ``limit`` 1 to
  500, ``date_from`` not after ``date_to``) and anything else becomes a tool error the model can read;
* outputs are cut to ``MAX_TOOL_RESULT_CHARS`` and passed through ``oah.explain.safety.sanitize_evidence`` (control
  characters, instruction-like text and URLs removed) before the model sees them;
* the selected country is enforced here, not trusted to the model: a site of another country (or of an unresolved
  country) is refused while a country is selected, so the regimes of two countries are never mixed in one answer.

Pure module: all data comes through the callables of ``ToolContext`` (supplied by ``oah.api``), so there is no HTTP
self-call and tests run with plain functions.

Layout (package ``oah.chat.tools``; every public name of the former single module is re-exported here):

* ``context``: ``ToolContext``, the callables the tools read through;
* ``definitions``: the tool definitions sent to the model, ``ALL_TOOLS``, the tools each index offers;
* ``validation``: argument checks, ``normalise_country`` and the sanitised argument trace;
* ``results``: the size bound, ``{amount, unit}`` numbers and ``ToolOutcome``;
* ``sites``, ``bathing``, ``comparison``, ``samples``: the handlers by tool family (the external-context tools stay in
  ``oah.chat.external_tools``);
* ``dispatch``: ``run_tool`` and the trace summary; ``citations``: ``citations_for`` and ``origin_for``.
"""

from __future__ import annotations

from oah.chat.errors import ToolError
from oah.chat.tools.bathing import DEFAULT_BATHING_LIMIT, MAX_BATHING_LIMIT
from oah.chat.tools.citations import MAX_CITATIONS, citations_for, origin_for
from oah.chat.tools.comparison import compact_country_change, compact_site_change
from oah.chat.tools.context import ToolContext
from oah.chat.tools.definitions import (
    ALL_TOOLS,
    INDEX_NAMES,
    TOOL_DEFINITIONS,
    TOOLS_BY_INDEX,
    allowed_tools,
    tool_definitions,
)
from oah.chat.tools.dispatch import run_tool
from oah.chat.tools.results import MAX_TOOL_RESULT_CHARS, ToolOutcome
from oah.chat.tools.samples import DEFAULT_SAMPLES_LIMIT, MAX_SAMPLES_LIMIT, compact_samples_change
from oah.chat.tools.sites import DEFAULT_MEASUREMENT_LIMIT, MAX_LISTED_STORE_SITES, compact_record
from oah.chat.tools.validation import COUNTRY_ALIASES, MAX_ARGUMENT_CHARS, normalise_country, trace_arguments

__all__ = [
    "ALL_TOOLS",
    "COUNTRY_ALIASES",
    "DEFAULT_BATHING_LIMIT",
    "DEFAULT_MEASUREMENT_LIMIT",
    "DEFAULT_SAMPLES_LIMIT",
    "INDEX_NAMES",
    "MAX_ARGUMENT_CHARS",
    "MAX_BATHING_LIMIT",
    "MAX_CITATIONS",
    "MAX_LISTED_STORE_SITES",
    "MAX_SAMPLES_LIMIT",
    "MAX_TOOL_RESULT_CHARS",
    "TOOLS_BY_INDEX",
    "TOOL_DEFINITIONS",
    "ToolContext",
    "ToolError",
    "ToolOutcome",
    "allowed_tools",
    "citations_for",
    "compact_country_change",
    "compact_record",
    "compact_samples_change",
    "compact_site_change",
    "normalise_country",
    "origin_for",
    "run_tool",
    "tool_definitions",
    "trace_arguments",
]
