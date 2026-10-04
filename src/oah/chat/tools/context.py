"""Where the chat tools get their data: ``ToolContext``, a bundle of callables supplied by ``oah.api``."""
from __future__ import annotations

from collections.abc import Callable, Mapping
from dataclasses import dataclass
from datetime import date
from typing import Any

from oah.external.service import ExternalContext
from oah.indices.period_change import Period


@dataclass(frozen=True)
class ToolContext:
    """Where the tools get data. Each callable wraps the existing function the matching REST route uses."""

    country: str | None
    sites: Callable[[], list[dict[str, Any]]]  # list_sites_with_status over official records
    countries: Callable[[], tuple[list[dict[str, Any]], int]]  # countries_overview
    index: Callable[[str], dict[str, Any] | None]  # per-site CCME payload, None when the site is unknown
    measurements: Callable[[str, str | None, date | None, date | None], list[dict[str, Any]] | None]  # None: unknown site
    qc: Callable[[], dict[str, Any]]  # QC report over official records
    freshness: Callable[[], Mapping[str, Any]]  # get_data_freshness
    # Waterbase store (optional, so a context without it still works): a page of ``/sites`` entries for a country and a
    # name query, ``(total matching, entries)``, and one site entry (None when unknown or the store is not built).
    waterbase_sites: Callable[[str | None, str | None, int], tuple[int, list[dict[str, Any]]]] | None = None
    waterbase_site: Callable[[str], dict[str, Any] | None] | None = None
    # Bathing-water classification store (optional): a page of entries for ``(country, name query, quality, type, limit)``
    # as ``(total matching, entries)``, and one bathing water with its ``history`` (None when unknown or not built).
    bathing_list: Callable[[str | None, str | None, str | None, str | None, int], tuple[int, list[dict[str, Any]]]] | None = None
    bathing_get: Callable[[str], dict[str, Any] | None] | None = None
    # Period comparison (optional): ``(site id, parameter, period A, period B)`` and ``(country, parameter, period A,
    # period B)`` give the same payload as the REST routes; a ValueError (invalid input) or LookupError (unknown scope)
    # carries a message that is safe to show. ``bathing_compare`` is ``(country, season A, season B)``.
    compare_site: Callable[[str, str, Period, Period], dict[str, Any]] | None = None
    compare_country: Callable[[str, str, Period, Period], dict[str, Any]] | None = None
    bathing_compare: Callable[[str, int, int], dict[str, Any]] | None = None
    # Bathing-water SAMPLES store (optional): ``(bathing water id, date from, date to, season, limit)`` gives the route's
    # payload (newest first) or None when the identifier is unknown; ``(bathing water id, period A, period B)`` and
    # ``(country, period A, period B)`` give the comparison payloads. A ToolError carries a message that is safe to show.
    samples_get: Callable[[str, date | None, date | None, int | None, int], dict[str, Any] | None] | None = None
    samples_compare_site: Callable[[str, Period, Period], dict[str, Any]] | None = None
    samples_compare_country: Callable[[str, Period, Period], dict[str, Any]] | None = None
    # EXTERNAL context (optional, docs/external_context.md): the facade the three external tools call; None means they
    # answer that external context is not available in this deployment.
    external: ExternalContext | None = None
