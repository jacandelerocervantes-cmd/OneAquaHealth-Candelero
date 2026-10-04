# Period comparison (backend package 5)

Date: 2026-10-02. Code: `src/oah/indices/period_change/` (the pure comparison), `src/oah/waterbase/change.py` and
`src/oah/indices/sandbox_change.py` (the two data adapters), `src/oah/api/change.py` (assembly shared by the routes and the chat
tools), `src/oah/bathing/change.py` (the season comparison). Routes: `GET /sites/{site_id}/change`,
`GET /countries/{country_code}/change`, `GET /bathing-waters/change` (`docs/api_routes.md`). Chat tools: `compare_periods`,
`compare_bathing_seasons` (`docs/chat_agent.md`).

The question this answers: "from May 2021 to May 2026, how much has X changed?". It delivers the DATA whether or not a limit
exists, gives the limit and its source wherever the project has one, and says plainly when a period lies beyond the data. **No model
is involved**: every number is arithmetic on stored values, and no statistic beyond the ones listed here is computed (no trend, no
significance test, no interpolation). The REST routes return the exact numbers only. The chat tools add, next to them, an `approximate` block of
presentation rounding (significant figures by sample count, the observed range rounded outward; not a statistical uncertainty): `docs/chat_agent.md` section 11.

## 1. Inputs

- A scope: one site, or one country (`EL` is read as `GR`).
- A parameter: a closed project name (for example `Nitrate`, `Total phosphates`) or the Waterbase label of a measurement-only or
  listed determinand (`Turbidity`, `BOD5`, `Chloride`, ...), case-insensitive, at most 64 characters. A sandbox site accepts the closed
  names only; a Waterbase site the names of `oah.waterbase.mapping.parameter_names`. A name that is not known to a consulted source is a 422.
- Two periods, A and B, each a range of calendar months `YYYY-MM` (years 1900 to 2100), both ends included, at most 1200 months. An
  inverted or malformed period is a 422. A comes first by convention only: the periods may be in any order, and a `periods-overlap`
  flag is raised when they share months.

The matrix of a Waterbase series is the one the mapping holds for a closed name (so `Lead dissolved` is `W-DIS`), the other one for the
Waterbase label of a mapped determinand (`Lead and its compounds` is `W`, listed but never compared), and `W` for the label of an
unmapped determinand (a comparison needs exactly one series; the measurements route lists every matrix).

## 2. Definitions and formulas

Let a period contain the quantified values `x_1 ... x_n` of the sites in scope (values below the limit of quantification are NOT among them).

| Quantity | Definition |
|---|---|
| `n_samples` | `n`, the number of quantified values in the period (for the sandbox: the number of aggregate records, `n_unit` `aggregate-records`) |
| `n_months_with_data` | months of the period with at least one quantified value (for the sandbox: the months the used aggregates cover) |
| `mean` | `sum(x_i) / n`, computed as the sum of the monthly sums over the sum of the monthly counts, so it does not depend on how the samples fall into months (a mean of monthly means is never used) |
| `min`, `max` | the smallest and largest quantified value (the extremes of the monthly extremes); the mean lies between them |
| `n_below_loq` | samples reported below the limit of quantification in the period |
| `below_loq_share` | `n_below_loq / (n_samples + n_below_loq)`, null when both are zero |
| absolute change | `mean_B - mean_A` |
| relative percent | `100 * (mean_B - mean_A) / abs(mean_A)`; null with `relative_percent_note` `baseline-zero` when `mean_A` is zero after rounding to six decimals, `baseline-missing` when A has no mean, `comparison-missing` when B has none |
| direction | `no-change` when `round(mean_A, 6) == round(mean_B, 6)`, else `increased` (`mean_B > mean_A`) or `decreased` |

- The direction is exact equality after rounding. The rounding (`COMPARISON_DECIMALS = 6`) only absorbs floating-point noise from
  `sum / n` and unit conversion: any difference larger than one millionth of the unit is reported as a difference. **It is not a
  significance test and no claim of significance is made anywhere.**
- The percent uses `abs(mean_A)` so that its sign always matches the direction. For `Cel` and `pH` the number is given with the note
  `interval-scale` (and the flag `relative-change-interval-scale`): a percent change of a Celsius or pH mean is not meaningful.
- Output numbers are rounded to six decimals (percent: four); the change is computed from the exact values, not from the rounded ones.
- Swapping the two periods negates the absolute change exactly and swaps the direction (a property test checks it, with the other
  invariants: the mean lies in `[min, max]`; the mean equals `sum / n`; regrouping samples into months never changes the mean; the
  paired set of a country is the same for both periods and for the swapped comparison).

### Values below the limit of quantification

A below-LOQ row is counted (`n_below_loq`) and its number (the file holds the quantification limit or a placeholder there) is never
used as a measurement, exactly as in the store build (`docs/waterbase_store.md`). Excluding them biases the mean upward when many samples
are below the limit, so every period that has any carries the flag `below-loq-excluded-bias-upward` together with the share. A month
with only below-LOQ rows counts for `n_below_loq` and not for `n_months_with_data`. For the sandbox a censored record with `<` or `<=` is
below LOQ in the same way; any other comparator is left out and counted.

## 3. Coverage rules (constants of `oah.indices.period_change`, each overridable by the caller)

| Constant | Default | Meaning |
|---|---|---|
| `MIN_SAMPLES_PER_PERIOD` | 3 | quantified samples a period needs at one site; fewer gives `status` `insufficient-data` (the numbers are still returned) |
| `MIN_AGGREGATES_PER_PERIOD` | 1 | the same for an annual-only source (each aggregate record already summarises many samples; the default 3 of the monthly sources would make every sandbox comparison insufficient) |
| `FEW_SITES_THRESHOLD` | 5 | fewer paired sites than this carries the flag `few-sites` (a country comparison) |
| `COMPARISON_DECIMALS` | 6 | rounding for equality (above) |

Flags (a list on the whole result, and per period where it applies):

| Flag | Raised when |
|---|---|
| `period-outside-data` | the period ends after the last month the scope holds for the parameter (or the scope holds none). `data_range` gives the first and last month so a client can propose the latest available period; **the period is never shifted and no gap is filled** |
| `period-before-data` | the period ends before the first month the scope holds |
| `partial-period` | some but not all months of the period have a quantified value (`n_months_with_data < months_in_period`) |
| `below-loq-excluded-bias-upward` | `n_below_loq > 0` in the period |
| `annual-only` | the source is annual aggregates (the sandbox): never monthly resolution |
| `records-crossing-period-edge-excluded` | an annual aggregate crosses the period edge and was left out |
| `few-sites` | a country comparison with 1 to 4 paired sites |
| `periods-overlap` | the periods share months |
| `relative-change-undefined` | the relative percent is null (zero or missing baseline) |
| `relative-change-interval-scale` | the unit is `Cel` or `pH` |
| `no-data-for-scope` | the scope holds no data for the parameter at all |

`status` is `ok` when every period meets the minimum and `insufficient-data` otherwise. `data_range` is the first and last month with
any kept record of the parameter in the scope (a month with only below-LOQ rows counts), over all time and whatever the periods;
for the sandbox it is the span of the usable records of the parameter. `GET /countries` has a `data_range` per source and country
(Waterbase: any kept record of the country; sandbox: any water Observation matching a closed parameter), so a UI can show availability.

## 4. A country: paired sites only

A site is **paired** when it meets the minimum number of samples in BOTH periods. The comparison uses the paired sites only and the
same sites for both periods; a site is never compared with another site set and nothing is imputed.

- `n_sites_considered`: sites with at least one record (quantified or below LOQ) in either period. A site with no record in either
  period is not considered (it would only add noise).
- `n_sites_paired`, `n_sites_excluded` with `exclusion_reasons`: `absent-in-period-a` (records only in B), `absent-in-period-b`,
  `insufficient-samples` (records in both, fewer than the minimum in one).
- Per period: `n_sites`, `n_samples` (sum over the paired sites), `mean_of_site_means` (the mean of the paired sites' means, each site
  counting once whatever its number of samples), `n_below_loq`, `below_loq_share`, flags. The change of the two means is
  `change_of_site_means`.
- `median_site_relative_change_percent`: the median of the per-site relative changes (sites with a zero baseline are left out and
  counted in `n_sites_relative_change_undefined`); `sites_increased`, `sites_decreased`, `sites_unchanged` use the same rounding rule per site.
- `few-sites` below 5 paired sites. With no paired site the status is `insufficient-data` and the counts still say what was found.
- The mean of site means is not a national status: it weights every site equally and is a descriptive figure only.

## 5. Limits: the existing machinery, applied to a period mean

For each period mean, `assess_mean` applies the functions the measurement records already use (`resolve_limit`, `limit_basis` with its
verification label, the `OAH_LIMITS_FILE` overrides, `classify_*`, the pH range); a parity test (`tests/unit/test_period_change_adapters.py`)
checks that it returns the same limit, basis, regime, status and scored value as `annual_record` for every mapped determinand, in
IT, GR and NO, for rivers and lakes. Per period the result has an `assessment`: `limit`, `limit_unit`, `limit_type`, `limit_range`,
`limit_basis`, `limit_regime`, `status` (`within-limit`, `exceeds-limit`, `indeterminate`, `not-scored`, `excluded`), `scored_value`, `flags`.

| Case | Behaviour |
|---|---|
| River (Waterbase `RW`) | the `surface` regime of the site's country: Italy DM 260/2010 LIMeco, Greece HWQI, Norway the EU or drinking-water proxy values, as in `docs/limits_verification.md`; an `OAH_LIMITS_FILE` override shows as `override: <source>` in `limit_basis` |
| Sandbox site | the regime and country of its Location (surface for a river, otherwise drinking) |
| Lake (`LW`) | `limit_regime` `no-limit-regime`, no limit, `not-scored` (`no-limit-regime`) |
| Measurement-only groups (`solids-turbidity`, `organic-matter`) | no limit, `not-scored` (`no-limit-regime`, `measurement-only`) whatever the category |
| Determinand without a closed name (Chloride, Phosphate, ...) | no limit, `not-scored` (`no-limit-mapping`) with the Waterbase reason |
| Cadmium, Italian dissolved oxygen, temperature in IT and GR | `not-scored` (`surface-limit-needs-hardness`, `oxygen-saturation-criterion-not-derivable`, `interpretive-only`) as in the records |
| Dated limit (lead, drinking regime) | judged at the last day of the period |

`crossed_limit` (site scope): `within-to-exceeds`, `exceeds-to-within`, `none` when both periods are judged against a limit and have enough
samples, otherwise null. "Exceeds" means beyond the limit in its own direction (below a minimum for dissolved oxygen). At country scope each
period reports `river_sites_judged` and `river_sites_over_limit` over the paired river sites, and `river_limit` (the limit that applies to a river
site of the country in each period, or why none does). No new limit was added or invented.

**Approximation.** National aggregation rules (LIMeco, HWQI and so on) are not reproduced. A period mean compared with a limit is a screening
aid, not a compliance assessment. Every response carries `approximation_notice` (and the existing `interpretation_notice`) as fixed strings,
localised when `language` is given (`oah.i18n.strings`, English in code, machine-drafted files for the other 25 languages):
"Screening aid, not a compliance assessment: each period is summarised by its mean, which is compared with the limit. National
aggregation rules such as LIMeco or HWQI are not reproduced."

## 6. Sources

- **EEA Waterbase** (`real-eea-waterbase`): the store holds one aggregate per site, determinand, matrix, unit and MONTH (schema version 3).
  A mapped determinand is converted per row to the unit and basis of the closed parameter (`to_project_unit`; a basis that does not match is
  refused), total phosphorus as phosphate; a measurement-only determinand keeps only its expected unit; an unmapped one keeps the unit with the most
  records. Every other row is left out and counted (`rows_excluded_unit`), never converted by guesswork.
- **Sandbox** (`real-sandbox`): the records are ANNUAL AGGREGATES (a median, else an average, per period), not samples and not months. Each is
  placed on the months its period covers and counts as ONE record; a record is used in a period only when the period contains all its months
  (one that crosses the edge is left out, counted, flagged, never split); the "mean" is the mean of those aggregate values; records that QC
  excluded (`qc-inconsistent`, `physically-impossible`, unit mismatch) are not used. Result flag `annual-only`, `resolution` `annual-only`.
- The two sources are never combined: a country answer has one result per source.

## 7. Worked example (SYNTHETIC numbers)

An Italian river site, total phosphorus reported as `mg{P}/L`. Period A = 2021-01 to 2021-12: samples of 0.04 in March, April and May.
Period B = 2023-01 to 2023-12: samples of 0.12 in March, May and July and one sample below the quantification limit in August.
Phosphorus is compared as phosphate: factor `PO4/P = (30.973762 + 4 x 15.999) / 30.973762 = 3.066136`.

| | A | B |
|---|---|---|
| `n_samples` | 3 | 3 |
| `n_below_loq`, share | 0, 0 | 1, 0.25 (flag `below-loq-excluded-bias-upward`) |
| `n_months_with_data` of 12 | 3 (flag `partial-period`) | 3 (flag `partial-period`) |
| mean in mg/L as PO4 | `0.04 x 3.066136 = 0.122645` | `0.12 x 3.066136 = 0.367936` |
| limit (Italy, DM 260/2010 LIMeco: 100 ug/l as P) | `0.1 x 3.066136 = 0.306614` mg/L | the same |
| status | `within-limit` | `exceeds-limit` |

Change: absolute `0.367936 - 0.122645 = 0.245291` mg/L; relative `100 x 0.245291 / 0.122645 = 200` percent; direction `increased`;
`crossed_limit` `within-to-exceeds`. Had A held a mean of 0 the relative percent would be null with the note `baseline-zero`. Had B been
2026-05 against data ending in 2024-12, the answer would say `period-outside-data`, return `data_range.last` `2024-12`, `n_samples` 0 and a null
change, and shift nothing. A country comparison over this and four more such sites would report `n_sites_paired` 5 (no `few-sites`), the mean of the five
site means per period, the median of the five relative changes and how many sites increased.

## 8. Seasons of bathing-water classification (`GET /bathing-waters/change`)

Counts only. The classes are compared by the order the archive README names, `excellent`, `good`, `sufficient`, `poor` (best first), and
nothing else: `0 - Not classified`, `3 - Good or Sufficient` (the README does not explain them) and a blank or unknown class are NOT comparable
and are counted separately, per pair of strings as written. A bathing water with a classification row in only one of the two seasons is counted
as `only_in_season_a` or `only_in_season_b`, never imputed. Result: per-season totals per class string, `paired_bathing_waters`, `comparable`,
`moved_up`, `moved_down`, `unchanged`, the list of transitions (`from_class`, `to_class`, `count`), `not_comparable` (count and pairs),
`data_range` (first and last season of the country), flags (`season-outside-data`, `season-without-classifications`,
`no-bathing-water-data-for-country`, `store-not-ready`). No concentration, no threshold and no meaning beyond the order. The notice is the
fixed string `bathing_change_notice`, localised.

## 8b. Samples of bathing waters (`GET /bathing-waters/{bw_id}/samples/change`, `GET /bathing-waters/samples/change`)

The machinery above is reused for the individual E. coli and intestinal enterococci samples of the Discodata store (`docs/bathing_samples_store.md`), with the parameter declared MEASUREMENT ONLY: cells are the calendar-month n, sum, min and max of the QUANTIFIED values of a bathing water, the coverage rule (3 quantified samples), the flags, `data_range` and the paired-site rule of a country are those of sections 2 to 4, and there is no limit assessment, no `crossed_limit` and no significance claim. Values flagged below the limit of detection, missing or of unrecognised status are NOT in the mean; they are counted per period and named in flags, but the flag `below-loq-excluded-bias-upward` is not used for them because the direction of a detection-limit number is unknown. Added: the exact median per period (the middle quantified value, or the mean of the two middle ones; for a country the median of the per-bathing-water medians of the paired bathing waters) and the change of the median. Bathing waters are sampled in the bathing season only, so periods with other months carry `partial-period`.

## 9. Limitations

1. Descriptive arithmetic, not inference: a difference between two means is reported, never judged significant; a seasonal pattern
   (a period of three summer months against twelve months) is not corrected for. Compare like with like.
2. Monthly resolution exists for the Waterbase store only; its years end at 2024 for Italy and Norway and 2021 for Greece in the 2026 edition, and the
   sandbox ends about 2020 (a few 2024-25 records for some parameters). Periods beyond the data are reported, not completed.
3. The mean of a Waterbase month is the mean of its quantified samples; two samples of one month weigh twice one sample of another month, by
   construction (the mean is `sum / n`).
4. A below-LOQ share is reported, but the project does not substitute, estimate or censor-adjust (no Kaplan-Meier or ROS here).
5. A limit comparison of a period mean is not the national classification rule (see the approximation notice).
6. A country mean of site means depends on which sites have enough data in both periods; the paired counts say how many and why others were left out.
7. The sandbox "mean" is a mean of aggregate values (medians), not of samples; `n_samples` there counts records.
8. `pH` is logarithmic: the arithmetic mean of pH is not rigorous (it is flagged in the measurement records; here the percent is flagged `interval-scale`).
9. The matrix choice for an unmapped label (`W`) and the unit choice for an unmapped determinand (the most frequent unit) are choices of this
   project, stated here; the real build had no unit variants.
10. Machine-drafted translations of the two fixed strings were not reviewed by a human.

## 10. Tests

`tests/unit/test_period_change.py` (the pure module: exact arithmetic, zero baseline, below LOQ, insufficient data, the May 2021 to May 2026
case, partial periods, paired sites, median, limits for a river with a country regime, lakes, measurement-only, overrides, properties),
`test_period_change_adapters.py` (units, matrices, parity with `annual_record`), `test_period_change_api.py` (the monthly store, routes, errors,
SQL bounds and injection, sandbox annual-only, localisation, old stores), `test_period_change_chat.py` (the tool, country enforcement, grounding of
the new numbers), `test_bathing_change.py`, `test_period_change_strings.py`, `tests/contract/test_period_change_contract.py`. All data is
SYNTHETIC and labelled; no test uses the network or the real archives. The country-scope bounds have their own tests (section 11).

## 11. Country-wide comparisons: SQL aggregation, concurrency guard, result cache and hard caps (security fix F4, 2026-10-03)

**Problem.** The country comparison used to turn every monthly row of the country into Python objects (`MonthlyRow`, then `Cell`, then lists per site), up to
`MAX_SCOPE_ROWS` = 2,000,000 rows (1,500,000 samples for the bathing samples) per request, with no result cache and no limit on concurrent calls. Measured
on the real store before the fix, a request cost about 1 KB of Python heap per monthly row: Italy, pH (the largest country and determinand of the store, about 96,500 rows)
needed about 96 MB of extra process memory for one request; at the cap, about 2 GiB; a few concurrent calls, or the chat tool `compare_periods`, could have exhausted a
2 GiB instance. (The real store never reaches the cap for one determinand; the cap was the only bound, and a larger future store would have hit memory first.)

**1. Aggregation inside SQLite, no result number changed.** `oah.waterbase.scope_read.scope_country_aggregates` runs parameterised, read-only statements that return one
record per site and period (`GROUP BY site_id`): `SUM(n)`, `SUM(n_below_loq)`, `SUM(n_lower_reliability)`, `MIN` and `MAX` of the value times the unit factor, the sum, and a month
bit mask. Exactness, which is what makes the numbers identical and not merely close:

- the factor of a unit (the project unit through `to_project_unit`; one stored unit for an unmapped or measurement-only determinand) is bound as a double and multiplied in SQL, the same
  IEEE product the row path computed; the unit rules are one function (`oah.waterbase.change.unit_rules`) shared by both paths, and rows in a unit that is left out are counted from a
  per-unit `COUNT(*)` (`rows_excluded_unit`);
- the sum is NOT SQLite's `SUM` (its rounding differs from `math.fsum` and from one SQLite version to another). A user-defined aggregate (`oah.indices.sqlite_aggregates.ExactSum`)
  keeps Shewchuk's exact partial sums and returns their correctly rounded total, which equals `math.fsum` of the same converted monthly sums, so the mean `sum / n` is bit-identical;
- `min` and `max` come from months with `n > 0` only, as before; multiplying by a positive factor is monotone, so the minimum of the products is the product of the minimum;
- `n_months_with_data` of a country is the number of bits of the OR of the paired sites' masks (a month is a bit relative to the period start), not a set of months;
- the category and country of a site are those of its first row in primary-key order (unit, year, month) inside the periods, as the row path took them (a site whose rows span two
  categories, 3 in the real build, keeps that behaviour); the data range is the same `MIN` and `MAX` read as before.

The pure code is split accordingly: `compare_country` (cells in, as before) builds `period_stats` per site and period and calls `compare_country_stats`, which holds the whole comparison;
the SQL path builds the same `PeriodStats` with `aggregate_stats` from `WindowAggregate` records and calls `compare_country_stats` directly. A site is paired, excluded, counted and
judged exactly as in sections 2 to 5. Bathing-water samples: `oah.bathing_samples.store.country_window_aggregates` does the same per bathing water and period (integer sums are exact), and
the per-bathing-water MEDIAN is the exact median of the values of that bathing water (since the schema 2 speed-up, point 6 below, both come from ONE sequential pass per indicator, not from SQL window functions). The row-materialising code (`oah.waterbase.change.country_change_rows`,
`oah.bathing_samples.change.country_change_rows`) is kept as the reference of the parity tests and of `scripts/check_country_scope_parity.py`; no route or tool calls it.
The comparison of ONE site is unchanged: one site's rows are few.

**2. One process-wide guard** (`oah.indices.scope_guard`; module constants, not settings, because they bound memory and no variable should raise them):

| Constant | Value | Meaning |
|---|---|---|
| `MAX_CONCURRENT` | 2 | country-scope comparisons running at once in the process (Waterbase and samples share the pool; the routes and the chat tool go through the same functions) |
| `WAIT_SECONDS` | 5 | how long a further comparison waits for a slot; then `ScopeBusy` |
| `RETRY_AFTER_SECONDS` | 5 | the `Retry-After` of the busy answer |
| `CACHE_ENTRIES`, `CACHE_TTL_SECONDS` | 64, 600 | TTL + LRU cache of finished results |

A busy process answers HTTP **503** with `Retry-After: 5` and the detail "The server is busy with other country-wide comparisons; try again in a few seconds (or compare one site, or a
shorter period)." (503 is the repository's existing status for "a data source or a guard cannot serve right now", declared on every protected route); the chat tool reports the same sentence as a
tool error, so the model can tell the user instead of inventing a number. Nothing queues beyond the 5 second wait. The cache key is (source, store file path with modification time and size,
country, determinand and matrix, both windows): never the language (notices are applied outside), and a rebuilt store never answers from its predecessor's entries. A cached result is
deep-copied in and out, a failure is never cached, and an identical question that waited for a slot is answered from the cache without a second computation. All of it is in memory: it
resets on every restart (crash, deploy, failed probe) and is per instance.

**3. Hard caps, last resort.** `store.MAX_SCOPE_ROWS` (2,000,000) now counts the rows the aggregation scans (inside the aggregate callback, so the statement stops at the cap), and a wall-clock
cap (`scope_read.SCOPE_QUERY_SECONDS` 120 s; `COUNTRY_READ_SECONDS` 240 s for the samples aggregate) interrupts the statement through SQLite's progress handler. Either one raises `ScopeTooLarge`,
which the API answers with **422** ("This comparison is too large to run: ... Narrow the periods."); the samples cap `MAX_COUNTRY_ROWS` (1,500,000) does the same (before, `RowCapExceeded` was not
caught and would have been a 500). The result field `truncated` stays (always `false` on the SQL path: it either completes or fails).

**4. Measured on the real stores** (2026-10-03, arm64 laptop, SQLite 3.42, other processes running, so seconds are indicative; `scripts/check_country_scope_parity.py --isolated`; each path in a fresh
process; "peak" is the peak working set of the process, about 48 MB of which is the imports):

| Case (periods 2010-01..2017-06 and 2017-07..2024-12) | Rows path (before) | SQL path (after) |
|---|---|---|
| Waterbase IT pH (about 96,500 monthly rows, the largest) | 5.0 s, peak 144 MB | 3.3 s, peak 56 MB |
| Waterbase IT total phosphates | 3.3 s, peak 116 MB | 2.0 s, peak 55 MB |
| Waterbase IT BOD5 | 2.8 s, peak 115 MB | 1.4 s, peak 55 MB |
| Samples IT (both indicators; 5,494 and 5,449 paired bathing waters) | 94 s, peak 269 MB | 61 s, peak 64 MB |
| Samples GR | 25 s, peak 119 MB | 18 s, peak 59 MB |

Python heap by `tracemalloc` (which slows both paths): Waterbase IT total phosphates 59.1 MB to 4.6 MB, nitrate 51.7 to 4.3, total suspended solids 50.7 to 3.9, BOD5 58.3 to 4.5, chloride 63.4 to 4.4,
lead dissolved 73.4 to 4.4, Norway TOC 16.0 to 1.7; samples IT 206 MB to 6.8 MB and GR 61.8 to 2.7. **Parity on the real stores: EQUAL (the whole result dictionary, exact equality) for every one of the
ten cases** (paired sites: IT phosphates 619, nitrate 502, suspended solids 784, BOD5 983, chloride 917, lead dissolved 426, Norway TOC 196, Greek nitrate 0; samples IT 5,494 and 5,449, GR 1,547 and 1,547).
The samples comparison was slow at that point (about 12 passes over an 84 MB table at 2 to 5 s each on this machine); point 6 below is the fix.

**6. Samples: one pass per indicator (schema 2, 2026-10-04).** The slowness above was the read pattern, not the aggregation: the only index was `(country, sample_date)`, so every row of a country was looked up in the
84 MB table, and each of the 12 passes (two windows, two indicators, aggregate, median, kind counts) did it again. The samples store (schema 2, `docs/bathing_samples_store.md` "Country comparison read path") now has a covering
index for the kind counts and one PARTIAL index per indicator (quantified values only, ordered by country, bathing water, value). `oah.bathing_samples.store.country_window_aggregates` reads that index once per indicator;
`oah.bathing_samples.country_scan` (a user-defined aggregate) keeps the integer values of one bathing water per window and returns n, sum, minimum, maximum, month mask and the median (sorted values: the middle one, or `(a + b) / 2`
of the two middle ones, as `statistics.median`); `country_kind_counts` returns the counts by kind for both indicators and both windows in one covering read. Three passes per comparison instead of twelve, no window function
(`window_medians` was removed), no SQL `SUM` or `AVG` involved in a result number. The raw values are still read: the medians are exact and the result is bit-identical to the reference path. The guard, cache, row cap and clock are unchanged.

Measured on the rebuilt real store (2026-10-04, same laptop, `scripts/check_country_scope_parity.py` and `scripts/measure_samples_country_route.py`; seconds indicative, other processes running):

| Case (both indicators, paired bathing waters E. coli / enterococci) | Before (schema 1, SQL path) | After (schema 2) | Reference row path on the new store | Result |
|---|---|---|---|---|
| IT 2010-01..2017-06 / 2017-07..2024-12 (5,494 / 5,449) | 61 s | 3.4 s | 30.1 s | EQUAL |
| IT 2008-05..2016-06 / 2016-07..2024-10, longest windows (5,495 / 5,464) | not measured (about 61 s) | 3.3 s | 29.4 s | EQUAL |
| IT 2019-05..2019-09 / 2023-05..2023-09 (3,981 / 3,714) | not measured | 1.6 s | 2.9 s | EQUAL |
| IT 2015-01..2020-12 / 2018-01..2024-12, overlapping (5,499 / 5,454) | not measured | 2.6 s | 22.6 s | EQUAL |
| GR 2010-01..2017-06 / 2017-07..2024-12 (1,547 / 1,547) | 18 s | 1.1 s | 7.7 s | EQUAL |
| GR 2008-05..2016-06 / 2016-07..2024-10 (1,542 / 1,542) | not measured | 1.3 s | 9.9 s | EQUAL |
| GR 2019-05..2019-09 / 2023-05..2023-09 (425 / 808) | not measured | 0.5 s | 0.8 s | EQUAL |
| GR 2022-01..2024-12 / 2010-01..2013-12, swapped (1,165 / 1,376) | not measured | 1.0 s | 3.7 s | EQUAL |

Through the API route with the real store (`TestClient`, throwaway key, external providers off): IT 3.4 s cold, GR 1.1 to 1.3 s cold, 0.02 s for the same question again (cache). Process peak working set of the Italian
comparison 58 MB (48 MB of it the imports), Python heap peak (`tracemalloc`) 6.9 MB for Italy and 2.5 MB for Greece (before: 6.8 and 2.7 MB; the memory was already bounded). Parity: `tests/property/test_country_scope_parity.py`
(250 random synthetic stores, three countries, both indicators, all six kinds, values up to 2^53 - 1, overlapping, swapped, empty and outside-the-data windows: the whole result, and per bathing water n, sum, minimum, maximum, month
mask and median against `month_cells` and `window_values`, and the kind counts against `kind_counts`).

**5. Tests.** `tests/property/test_country_scope_parity.py` (hypothesis: random SYNTHETIC stores with mixed units, categories, below-LOQ months, overlapping, swapped and empty periods, four determinands: the
whole result and the per-site statistics, the mean bit-identical, equal between the SQL and the row path), `tests/unit/test_country_scope_guard.py` (cache, TTL, LRU, no caching of failures, bounded wait and
503 with `Retry-After`, the chat tool when busy, row and time caps as 422, the query plan on the primary key and injection text, the exact sum against SQLite `SUM`, the samples SQL path against the row path on
the synthetic store and on random stores, the samples scan and caps). Provisional: the guard constants (2, 5 s, 64, 600 s) and the caps were chosen for a one-instance demo of 2 GiB and are not tuned
against production traffic.
