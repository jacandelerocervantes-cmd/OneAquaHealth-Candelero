"""Period comparison: how a parameter changed between two periods at one site or across the sites of one country.

PURE and deterministic: no model, no network, no clock, no new statistics. The inputs are monthly cells (``Cell``)
already expressed in the parameter's unit and the two periods as year-month ranges; the outputs are plain dictionaries
(``docs/period_change.md`` has the definitions, the formulas, the constants and a worked example).

What is computed, per period and scope (all exact arithmetic on what the store holds):

* ``n_samples`` (quantified values), ``n_months_with_data``, ``mean = sum / n`` (the sum of the monthly sums over the
  sum of the counts, so the mean does not depend on how the samples were grouped into months), ``min``, ``max``,
  ``n_below_loq`` and the below-LOQ share ``n_below_loq / (n_samples + n_below_loq)``. Values below the limit of
  quantification are NOT in the mean (they bias it upward, said by a flag).
* the change: absolute ``mean_B - mean_A``, relative percent ``100 * (mean_B - mean_A) / |mean_A|`` (null with a flag
  when ``mean_A`` is zero after rounding, or missing) and the direction ``increased`` / ``decreased`` / ``no-change``
  (exact equality of the two means after rounding to ``COMPARISON_DECIMALS``; no significance claim of any kind).
* the limit, where the project has one, through the EXISTING machinery (``resolve_limit``, ``limit_basis`` with its
  verification label, the ``OAH_LIMITS_FILE`` overrides, the pH range): each period mean is compared with the limit of
  the site's regime and country as a screening aid, and ``crossed_limit`` says whether the comparison changed.

Coverage rules (constants below, each overridable by the caller): a period needs ``MIN_SAMPLES_PER_PERIOD`` quantified
samples (``MIN_AGGREGATES_PER_PERIOD`` aggregate records for an annual-only source) or the result is
``insufficient-data`` with the numbers still returned; flags ``period-outside-data``, ``period-before-data``,
``partial-period``, ``below-loq-excluded-bias-upward``, ``annual-only``, ``few-sites``. A country comparison uses ONLY
the sites that meet the minimum in both periods (paired sites); no site set is ever compared with another and nothing
is imputed.

Approximation: national aggregation rules (LIMeco, HWQI, ...) are not reproduced; a periodic mean compared with a limit
is a screening aid, not a compliance assessment (``approximation_notice``, a fixed string in ``oah.i18n.strings``).


Layout (package ``oah.indices.period_change``; every name of the former single module is re-exported here):

* ``periods``: months, ``Period``, ``Cell``, ``SiteContext``, ``ParameterContext`` (the inputs);
* ``stats``: ``period_stats``, ``aggregate_stats`` (the same statistics from rows summed by the data layer), ``change_block``, the flags and the per-period view, with the coverage constants (pure arithmetic);
* ``limits``: ``assess_mean`` and ``crossing`` (the existing limit machinery applied to a period mean);
* ``compare``: ``compare_site``, ``compare_country`` (from cells) and ``compare_country_stats`` (from per-site statistics).
"""

from __future__ import annotations

from oah.indices.period_change.compare import compare_country, compare_country_stats, compare_site
from oah.indices.period_change.limits import (
    CROSSING_VALUES,
    LAKE_BASIS,
    MEASUREMENT_ONLY_BASIS,
    NO_COUNTERPART_BASIS,
    NO_LIMIT_REGIME,
    OXYGEN_BASIS,
    assess_mean,
    crossing,
)
from oah.indices.period_change.periods import (
    MAX_PERIOD_MONTHS,
    MAX_YEAR,
    MIN_YEAR,
    Cell,
    ParameterContext,
    Period,
    PeriodError,
    Resolution,
    SiteContext,
    month_position,
    month_text,
    monthly_cell,
    parse_year_month,
)
from oah.indices.period_change.stats import (
    COMPARISON_DECIMALS,
    FEW_SITES_THRESHOLD,
    INTERVAL_SCALE_UNITS,
    MIN_AGGREGATES_PER_PERIOD,
    MIN_SAMPLES_PER_PERIOD,
    PERCENT_DECIMALS,
    VALUE_DECIMALS,
    PeriodStats,
    WindowAggregate,
    aggregate_stats,
    change_block,
    period_stats,
)

__all__ = [
    "COMPARISON_DECIMALS", "CROSSING_VALUES", "FEW_SITES_THRESHOLD", "INTERVAL_SCALE_UNITS", "LAKE_BASIS",
    "MAX_PERIOD_MONTHS", "MAX_YEAR", "MEASUREMENT_ONLY_BASIS", "MIN_AGGREGATES_PER_PERIOD", "MIN_SAMPLES_PER_PERIOD",
    "MIN_YEAR", "NO_COUNTERPART_BASIS", "NO_LIMIT_REGIME", "OXYGEN_BASIS", "PERCENT_DECIMALS", "VALUE_DECIMALS",
    "Cell", "ParameterContext", "Period", "PeriodError", "PeriodStats", "Resolution", "SiteContext", "WindowAggregate",
    "aggregate_stats", "assess_mean", "change_block", "compare_country", "compare_country_stats", "compare_site", "crossing", "month_position", "month_text",
    "monthly_cell", "parse_year_month", "period_stats",
]
