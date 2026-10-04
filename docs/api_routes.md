# API additions for the web app (backend package 1)

Date: 2026-10-02. All routes below are protected like every other route except `/health`: `X-API-Key` and the per-host rate
limit. The key is checked before the rate limit ("Access control and abuse limits" below). All carry an `origin` and `data_freshness`. Sandbox data is `real-sandbox` and works on official records only
(`docs/official_record_filter.md`); the optional EEA Waterbase slice is `real-eea-waterbase` (package 3, `docs/waterbase_store.md`).
The two are never mixed silently: every site and record carries its own `origin` and `source`, and a list holding both is
labelled `real-mixed`. Values are reference values, not legal limits (`interpretation_notice`). The route table
that the contract test checks is in `docs/architecture.md`; the machine-readable schema is `docs/openapi.json`.

Sandbox-backed answers are served from an in-process stale-while-revalidate cache (`docs/architecture.md`, "Sandbox cache"):
no field changed. When the copy behind an answer is older than the cache TTL (default 300 s), `data_freshness.status` is
`snapshot` (a held copy of live data, dated by `as_of`, with its `age_seconds`) instead of `live`, and `snapshot-stale` once the
copy is more than 24 hours old. A response is `live` only while its copy is younger than the TTL.

## `GET /sites` (changed)

Query (all optional): `country` (two letters, `EL` is read as `GR`; matches `limit_country`), `q` (part of a name or id, at most 64
characters, case-insensitive), `source` (`real-sandbox` or `real-eea-waterbase`), `limit` (1 to 500, default 200), `offset` (0 or more).
The list is the matching sandbox sites first (in their usual order), then the matching Waterbase sites ordered by country and id, so
a request never returns thousands of sites: the page is cut at `limit` and `truncated` says whether more remain.

Response: `origin` (`real-sandbox`, `real-eea-waterbase`, or `real-mixed` when the returned page holds both), `sources` (the sources
of the returned sites), `total_matching` (across both sources), `returned`, `limit`, `offset`, `truncated`, `sites`, and `waterbase`
(`state` `ready`, `not-built` or `unreadable`, plus `detail`, `edition`, `attribution`, `build_date_utc` when ready). Without a built
store only sandbox sites appear and `waterbase.state` is `not-built`. `source=real-eea-waterbase` never touches the sandbox, so it
works offline. `data_freshness` is the sandbox's when the sandbox was consulted, otherwise `snapshot` dated by the store build.

Waterbase entries (additive; a sandbox entry gets the defaults): `source` and `origin` `real-eea-waterbase`, `kind` `water-body`,
`status` `measurements-only` (no CCME index is computed for them, `reason` says so), `ui_status` `unavailable`, `limit_country`
(`GR`, `IT`, `NO`), `limit_regime` (`surface` for a river, `no-limit-regime` for a lake), `water_category` (`river` or `lake`),
`location_status` (`located`, or `no-location` when the file has no coordinates for the site or the site is restricted (confidentiality other than `F`: coordinates are never stored or shown even if a source supplies them, `docs/waterbase_store.md`), then `latitude` and `longitude` are
null), `water_body_name`, `first_year`, `last_year`. `latitude` and `longitude` are therefore nullable in the contract.

Two additive changes to every entry.

### `kind`

`water-body`, `air-quality-station`, `city` or `other`, from `src/oah/indices/site_kind.py`. First match wins:

1. Location `type` coding `420531007` (SNOMED CT "River", seen on the real Almyros Location) -> `water-body`. Not provisional.
2. The id, name or description contains the whole word `station`, or the words `air quality` -> `air-quality-station`. **Provisional**:
   a text rule, because no Location type says "air station".
3. The id, name or description contains one of `river`, `stream`, `estuary`, `coast`, `reach`, `lake`, `creek` (camel case is
   split, so `LowerReach` matches) -> `water-body`. **Provisional**: the words come from ids already seen
   (`Loc-Almyros-Estuary`, `Loc-Almyros-Coast`, `Loc-Giofyros-LowerReach`) and the Almyros description.
4. Location `type` coding `288520005` (SNOMED CT "City environment", observed in the sandbox) -> `city`.
5. Anything else -> `other`.

An air station whose name and description contain none of the rule-2 words is shown as `other` (or `city` if typed so). Check
the real Location resources and extend the keywords before relying on this for display.

### `limit_country` on skipped sites

Skipped entries now carry `limit_country` when `country_for_location` resolves one (it was only present on evaluated entries).

## `GET /countries`

Code: `src/oah/indices/countries.py`, `src/oah/indices/regimes.py` (`known_countries`, `has_national_limits`,
`country_limit_sources`). The route has no country list of its own. Countries are the union of: the recognised codes, the keys
of the national limit and oxygen tables, the values of the Location country overrides (all three change when `OAH_LIMITS_FILE`
is loaded), and every `limit_country` of a site.

Per country: `code`, `status`, `regime`, `has_national_limits`, `limit_sources`, `evaluated_sites`, `skipped_sites`,
`skipped_non_water_sites`, `total_sites` (all sources), and, added with the Waterbase store, `measurement_only_sites` (Waterbase
sites: annual measurements, no index), `latest_year` (latest year of Waterbase data, null without it) and `sources`, a breakdown
per source: `real-sandbox` (`total_sites`, `evaluated_sites`, `skipped_sites`) and `real-eea-waterbase` (`total_sites`,
`river_sites`, `lake_sites`, `sites_without_location`, `first_year`, `last_year`, `attribution`, `parameter_groups`). Also
`sites_without_country` (sites whose country cannot be resolved; never attributed to a country) and `waterbase` (the store state,
as in `/sites`). `origin` is `real-mixed` when any country holds Waterbase sites.

Added by package 4 (all additive):

- `parameter_groups` (per country): the groups of parameters present, from `water-chemistry`, `solids-turbidity`, `organic-matter`
  (`docs/waterbase_store.md`): the groups of the determinands the Waterbase store holds for the country, plus `water-chemistry` when
  a sandbox site of the country was evaluated. Sorted. The same list, Waterbase part only, is `parameter_groups` of the
  `real-eea-waterbase` entry of `sources`. Real build: Italy and Norway all three groups, Greece `organic-matter` and `water-chemistry`.
- `bathing_water` (per country): the EEA bathing-water CLASSIFICATION held for the country, or null (store not built, or no row for
  the country; Norway has none in the 2025 v1.0 file): `origin` `real-eea-bathing-water`, `bathing_waters` (count),
  `classification_rows`, `first_season`, `latest_season`, `latest_season_counts` (the file's own quality strings, for example
  `1 - Excellent`, mapped to the number of bathing waters in the latest season), `attribution`, `content` `classification-only`.
  It never changes the country `status` or `regime`.
- `bathing_water` (response level): `state` (`ready`, `not-built`, `unreadable`), `detail`, `edition`, `attribution`,
  `build_date_utc`, like `waterbase`. `waterbase.state` can now also be `rebuild-required` (a store built before the added groups).

Added by package 5 (additive): each entry of `sources` carries `data_range` (`first`, `last`: months `YYYY-MM`, or null when the source holds no
data for the country). Waterbase: the first and last month with any kept record of the country (real store: GR 2012-01 to 2021-12, IT and NO 2010-01 to
2024-12); sandbox: the span of the water Observations that match a closed parameter and whose Location resolves to the country. A UI shows it so the user
knows what a period question can reach.

- `status` is `national-limits` (a national table exists and at least one site was evaluated), `eu-values-only` (no national
  table, at least one site evaluated), `measurements-only` (no sandbox site evaluated, but the Waterbase store holds sites of the
  country) or `no-evaluable-water-data` (no site evaluated and none held, whatever limits exist). Decision: the
  label describes the data actually scored, so Italy, which has a national table but no evaluated site today, reads
  `no-evaluable-water-data`; `has_national_limits: true` tells the UI that the table is ready.
- `regime` is the limit regime of the country's `water-body` sites (Waterbase rivers count as `surface`, lakes as
  `no-limit-regime`): `surface`, `drinking`, `no-limit-regime`, `mixed` when they differ, `null` when the country has no water-body site.
- `limit_sources` are the distinct `limit_basis` texts of a river site of that country (national, `override: <source>` and the
  EU surface values), taken from `oah.indices.regimes.limit_basis`, so a limits-file override shows up as `override: ...`.
- Counts cover the sites `/sites` lists (Locations with a map position, plus the Waterbase sites). `skipped_non_water_sites` is the part of
  `skipped_sites` whose kind is not `water-body`.

## `GET /catalog` (web app sidebar)

Code: `src/oah/indices/catalog.py` (pure rules, unit-tested with synthetic inputs), assembly in `src/oah/api/payloads.py` (`_catalog_payload`), route in
`src/oah/api/routes/catalog.py`, models in `src/oah/api/schemas/catalog.py`. Protected like every route except `/health`. It is the authoritative list of the
families and indices of the sidebar (`docs/web_app_design.md`) for one country: the web app hides only what it marks as not applicable. It returns ALL indices
with an `applies` flag (so a client or a test can see what was hidden), never a country-less list.

Query: `country` (required, two letters, case-insensitive, `EL` is read as `GR`; a code that is not one of `GET /countries` is a 422 whose message lists the known
codes; a missing or malformed one is also a 422) and `language` (optional, a code of `GET /languages`; localises the `reason` texts only, titles stay English).

Response (`CatalogResponse`): `origin` (`real-mixed` when any country holds Waterbase sites, else `real-sandbox`, the convention of `/countries`), `data_freshness`
(the sandbox's, as in `/countries`), `interpretation_notice` (the fixed string of the other routes), `language`, `country`, `country_name` (only where the project
already carries a name for the code: Greece, Italy, Norway; null otherwise), `families` (in the order water, microbiology, context, data, synthetic-labs: `id`,
`title`, `indices`), `applicable_count` (for tests and tools; the UI shows no numbers) and `stores` (what the rules read, so the UI can show a notice for a store
that is not built: `sandbox` `available` or `unavailable`, `waterbase`, `bathing_water` and `bathing_samples` state blocks as in `/countries`, and `external`:
`enabled`, `weather`, `discharge`, `species`).

Each index: `id`, `family_id`, `family_title`, `title`, `origin_kind` (`real`, `external`, `synthetic`), `origins` (the origin labels of the data behind it),
`applies`, `reason_code` and `reason` (set only when it does not apply), `routes` (the paths behind it, as in this document), `chat_index` (the `index` of
`POST /chat` that fits it, or null).

| Family | Index id and title | Origin kind (origins) | Routes | `chat_index` |
|---|---|---|---|---|
| Water | `water-quality` Water quality | real (`real-sandbox`) | `/sites`, `/indices/{location_id}`, `/explain/indices/{location_id}` | `water-quality` |
| Water | `water-parameters` Water parameters | real (`real-sandbox`, `real-eea-waterbase`) | `/sites`, `/sites/{location_id}/measurements`, `/sites/{site_id}/change`, `/countries/{country_code}/change` | `water-parameters` |
| Water | `solids-turbidity` Solids and turbidity | real (`real-eea-waterbase`) | as water-parameters | `water-parameters` (provisional, see below) |
| Water | `organic-matter` Organic matter | real (`real-eea-waterbase`) | as water-parameters | `water-parameters` (provisional) |
| Microbiology | `bathing-classes` Bathing classes | real (`real-eea-bathing-water`) | `/bathing-waters`, `/bathing-waters/{bw_id}`, `/bathing-waters/change` | `microbiology` |
| Microbiology | `bathing-samples` E. coli and enterococci | real (`real-eea-bathing-samples`) | `/bathing-waters/{bw_id}/samples`, `.../samples/change`, `/bathing-waters/samples/change` | `microbiology` |
| Context | `weather` Weather | external (`external-open-meteo`) | `/sites/{site_id}/weather` | null |
| Context | `river-discharge` River discharge | external (`external-open-meteo`) | `/sites/{site_id}/discharge` | null |
| Context | `species-nearby` Species nearby | external (`external-gbif`) | `/sites/{site_id}/species` | null |
| Data | `data-quality` Data quality | real (`real-sandbox`) | `/qc/report` | `data-quality` |
| Synthetic labs | `citizen-science` Citizen science | synthetic | `/reliability/campaign` | null |
| Synthetic labs | `review-queue` Review queue (read-only) | synthetic | `/review/queue` | null |
| Synthetic labs | `river-risk` River risk | synthetic | `/risk/{site_id}` | null |

Not included at all, never returned: biotic quality, protozoa, air quality and population health (not available as data).

Applicability rules (what "applies" means: the service holds the data the index needs for the country; it says nothing about the values, and is never a safety
or compliance statement). Nothing is a hard-coded country list; every input comes from a store summary or a site list:

| Index | Applies when |
|---|---|
| `water-quality` | at least one sandbox site of the country was evaluated (`evaluated_sites` of `/countries`: it has a CCME index) |
| `water-parameters` | the country's `parameter_groups` (from `/countries`) contain `water-chemistry` (an evaluated sandbox site or the Waterbase `country_determinands`) |
| `solids-turbidity`, `organic-matter` | the Waterbase `country_determinands` of the country contain a determinand of that group |
| `bathing-classes` | the bathing-water classification store holds bathing waters of the country |
| `bathing-samples` | the bathing-samples store holds samples of the country (independent of the classification store) |
| `weather` | the Open-Meteo archive switch is on (`OAH_EXTERNAL_ENABLED` and `OAH_EXTERNAL_OPEN_METEO_ENABLED`) AND the country has at least one located site: a sandbox water-body site, a Waterbase river or lake site with coordinates, or a bathing water with coordinates |
| `river-discharge` | the GloFAS switch is on (`OAH_EXTERNAL_GLOFAS_ENABLED`) AND a located river site exists: a Waterbase river site with coordinates, or a sandbox water-body site (the sandbox gives no water category, and the discharge route accepts it) |
| `species-nearby` | the GBIF switch is on (`OAH_EXTERNAL_GBIF_ENABLED`) AND a located water-quality site exists (as above, lakes included, bathing waters excluded: the species route refuses them) |
| `data-quality` | the sandbox answered (live, or a local snapshot; `/qc/report` is not specific to a country) |
| `citizen-science`, `review-queue`, `river-risk` | always (synthetic by design; labelled `synthetic`) |

`reason_code` (and the fixed string of each, in `src/oah/i18n/strings.py` and the 25 translation files, machine drafts): `no-data-for-country` ("No data for this country."),
`data-not-loaded` ("Data not loaded."), `provider-off` ("This external provider is switched off."), `no-located-site` ("No site with coordinates in this country."),
`no-located-river-site` ("No river site with coordinates in this country."). When nothing was found and a source the index depends on is not loaded (a store that is
`not-built`, `unreadable` or `rebuild-required`, or a sandbox without live data and without snapshot) the reason is `data-not-loaded`, not `no-data-for-country`; a
provider that is off is reported first. The catalogue never fails because a source is missing: an unreachable sandbox without snapshot is `stores.sandbox` `unavailable`
(the indices that need it say `data-not-loaded`) and the stores still answer. The same overview feeds the validation of `country`.

Decisions and provisional items: (1) `solids-turbidity` and `organic-matter` carry the chat index `water-parameters` because the tools of that index answer them (the Waterbase
labels such as Turbidity are accepted by `get_site_measurements` and `compare_periods`); the chat has no index of its own for them, so this is a choice, not a fact of the chat
code, and can be set to null. (2) A sandbox water-body site counts as a located river site for the discharge, because the sandbox gives no water category; the discharge route
itself flags a cell that may not be the river. (3) The located-site counts of the stores come from two added read-only queries (`oah.waterbase.store.located_counts`,
`oah.bathing.store.located_counts`); coordinate plausibility is checked by the external routes when a site is used, not here. (4) The reason strings are machine drafts like
every other fixed string (no human review).

## `GET /sites/{location_id}/measurements`

Code: `src/oah/indices/site_measurements.py`. No new formula: each record is built with the index's own functions
(`representative_quantity`, `convert_to_unit`, `resolve_limit`, `classify_quantity`, `classify_range_quantity`,
`resolve_range_limit`, `saturation_test`), in the order of `apply_ccme_wqi_to_sandbox`, and a test checks that the number of
scored records and of exceedances equals the index's `evaluable_measurements` and `failed_measurements`.

Query: `resolution` (package 5, `annual` by default or `monthly`, see "Monthly resolution" below), `group` (package 4, see "Parameter groups" below), `parameter` (a closed name such as `Nitrate` or `pH`, case-insensitive; the names come from
`CLOSED_PARAM_MAPPING`; anything else is 422), `date_from` and `date_to` (ISO dates, UTC days, both included; a record is kept
when its period overlaps the window; a record whose time cannot be read is dropped when a window is given; `date_from` after
`date_to` is 422), `limit` (1 to 500, default 200). 404 for a site with no Location and no Observation. A known site with no
matching record returns an empty list.

A Waterbase site (an id of `GET /sites` with `source` `real-eea-waterbase`) is answered from the local store, without a sandbox
fetch: see "Waterbase sites" below.

Response: `location_id`, the echoed filters, `limit`, `total_matching`, `returned`, `truncated`, `records`. Records are sorted
by period start, parameter, Observation id. Each record:

| Field | Meaning |
|---|---|
| `observation_id`, `parameter` | The Observation and its closed parameter name |
| `value`, `statistic` | The value used, in `unit`, and which statistic it is: `median`, else `average`, `value` for a plain Quantity |
| `comparator` | `<`, `<=`, `>=`, `>` for a censored value (then `value` is the bound) |
| `min`, `max` | The exact minimum and maximum components, in `unit` (null when absent) |
| `unit`, `original_unit` | The unit the limit uses, and the unit the record was reported in (`value` is converted) |
| `period_start`, `period_end` | As stored (a single instant gives the same text twice) |
| `scored_value` | The number compared with the limit; equals `value` except for Italian oxygen, where it is the saturation deviation in % |
| `limit`, `limit_unit`, `limit_type`, `limit_range` | The limit applied, its unit, `maximum` or `minimum`, and `[6.5, 9.5]` for pH (inside the range the upper bound is shown, as the index does) |
| `limit_basis`, `limit_regime`, `limit_country` | Source text with its verification label, regime and country regime of the site |
| `status` | `within-limit`, `exceeds-limit`, `indeterminate` (censored value that cannot decide), `not-scored`, `excluded` |
| `data_quality_flags` | Why a record is not scored or needs care: `qc-inconsistent`, `no-representative-statistic`, `no-quantity`, `non-finite-value`, `unit-mismatch`, `physically-impossible`, `invalid-quantity`, `censored`, `censored-bound-counted-as-pass`, `interpretive-only`, `surface-limit-needs-hardness`, `no-temperature-for-saturation`, `ambiguous-temperature-for-saturation`, `unusable-temperature-for-saturation` |
| `origin` | `real-sandbox` |

`not-scored` records keep their value but no limit comparison: water temperature in countries where it is interpretive only (GR, IT)
and hardness-dependent cadmium on rivers. `data_freshness` is on the response, not repeated per record.

## `GET /sites/{location_id}/fhir`

Code: `src/oah/fhir/output/measurements.py`, route in `src/oah/api/routes/sites.py`. Read-only. Same query and same errors as
`GET /sites/{location_id}/measurements` (the route calls it, so the two never disagree); the answer is a FHIR R4 collection
`Bundle` in JSON (typed `FhirBundleResponse` in the contract: the envelope is typed, the FHIR resources are free-form FHIR JSON): one `Location`, one `Observation` per record that has a numeric value, one
software `Device` and one `Provenance` (targets: every Observation; source: the attribution of the data). Records without a value
are left out; a selection with no numeric value at all is a 404. No code is invented (the parameter is `code.text` only; a UCUM
unit code only for units written the UCUM way). Every resource carries the project-defined data-origin tag of its record. It
does not claim conformance to the OneAquaHealth profiles. The web app's "Download as FHIR" button on the measurements table calls
it. Details and rules: `docs/fhir_mapping.md`, section "Site measurements export".

### Waterbase sites (package 3)

Same route, same fields, with these differences (`docs/waterbase_store.md` has the rules). `origin` and `source` are
`real-eea-waterbase`; `attribution` is `EEA Waterbase - Water Quality ICM 2026 (CC BY 4.0)`; `index_status` is `measurements-only`;
`site` carries the site block (`name`, `country`, `water_category`, `water_body_name`, coordinates or `no-location`,
`confidentiality`, first and last year); `data_freshness` is `snapshot` dated by the store build. One record is one ANNUAL aggregate:
`statistic` `mean`, `value` the annual mean of the quantified samples in `unit` (converted to the limit's unit and basis where the
mapping says so, `original_unit` is what Waterbase reported), `min`, `max`, `n` (samples in the mean), `n_below_loq` (not in the
mean), `n_lower_reliability` (Waterbase status U or V, in the mean), `year`, `period_start` and `period_end` (the calendar year),
`determinand_code`, `matrix` (`W` or `W-DIS`). There is no median.

`parameter` also accepts the Waterbase label of a determinand that is listed but not compared (`Chloride`, `Oxygen saturation`,
`Phosphate`, `Lead and its compounds` for whole water). `date_from` and `date_to` keep the years the window overlaps. Rivers are
scored with the existing machinery on the annual mean (`limit`, `limit_basis`, `limit_regime` `surface`, `status`); lakes carry
`limit_regime` `no-limit-regime`, no limit and status `not-scored`. Extra `data_quality_flags`: `no-limit-mapping`, `no-limit-regime`,
`all-below-loq`, `below-loq-excluded-from-mean`, `includes-lower-reliability-records`, `arithmetic-mean-of-ph`,
`oxygen-saturation-criterion-not-derivable`; `unit-mismatch` now also means a unit label whose basis differs from the expected one
(status `excluded`). A year with only values below the quantification limit is `indeterminate`.

### Parameter groups and the `group` filter (package 4, additive)

Every record carries `group` (`water-chemistry`, `solids-turbidity` or `organic-matter`; sandbox records are `water-chemistry`, the
label the Waterbase chemistry has for the same closed parameter names). The optional query parameter `group` keeps only the records of
that group (any other value is 422); `parameter` and `group` combine, a parameter outside the group matches nothing; the response
echoes `group`. The Waterbase store holds eight determinands in the two new groups (Turbidity, Total suspended solids, Secchi depth;
Total organic carbon (TOC), Dissolved organic carbon (DOC), Chlorophyll a, BOD5, CODCr), accepted by `parameter` under those labels.
They are MEASUREMENT ONLY: `limit` null, `limit_regime` `no-limit-regime`, `status` `not-scored`, flags `no-limit-regime` and
`measurement-only`, rivers included; a unit label other than the expected one is `excluded` with `unit-mismatch`. The `unit` is as
reported (`{NTU}`, `mg/L`, `m`, `mg{C}/L`, `mg{O2}/L`, `ug/L`). Turbidity and suspended solids are proxies for particulate/colloidal
matter, not colloids (`docs/waterbase_store.md`).

### Monthly resolution (package 5, additive)

`resolution=monthly` on a Waterbase site returns one record per MONTH instead of one per year: the same fields as the annual record plus `month`
(1 to 12, null on an annual record), `period_start` and `period_end` the first and last day of that month, `observation_id` ending in the
month (`...|2021-05|mg{NO3}/L`), `n` the samples of that month, `value` their mean, `min`, `max`, and the same limit, basis and status as an annual
record (a dated limit is judged at the end of that month). `date_from` and `date_to` keep the months of the years they touch; `limit` (1 to 500,
default 200) still bounds the answer (`total_matching`, `returned` and `truncated` say what was cut). The response echoes `resolution`: `annual`,
`monthly`, or `period-summary` for a sandbox site. A sandbox site has no monthly resolution (its records are annual aggregates): `resolution=monthly`
for it is a 422, nothing is pretended. Any other value is a 422.

## `GET /sites/{site_id}/change` and `GET /countries/{country_code}/change` (backend package 5)

Code: `src/oah/indices/period_change/` (pure), `src/oah/waterbase/change.py`, `src/oah/indices/sandbox_change.py`, `src/oah/api/change.py`,
`src/oah/api/change_schemas.py`. Definitions, formulas, constants, flags, limit behaviour, a worked example and the limitations: `docs/period_change.md`.
Protected like every route except `/health`. Deterministic arithmetic on stored values; no model.

Query (all required except `language`, and `source` on the country route): `parameter` (a closed name or a Waterbase label, case-insensitive, at most 64
characters), `a_from`, `a_to`, `b_from`, `b_to` (`YYYY-MM`, both ends included; period A is `a_from` to `a_to`, period B `b_from` to `b_to`), `language` (a code of
`GET /languages`; localises the two notices), and on the country route `source` (`real-sandbox` or `real-eea-waterbase`) to consult one source only.
404 for an unknown site or country (the country must be one of `GET /countries`; `EL` is read as `GR`); 422 for a malformed month, an inverted period
(`a_from` after `a_to`, or `b_from` after `b_to`), a period longer than 1200 months, an unknown parameter (the message lists the known names), an unknown
language or source. A parameter that is valid but unknown to the consulted source (a Waterbase label for a sandbox site) is also a 422. Works for both
sources: a site is looked up in the Waterbase store first (a local read) and in the sandbox otherwise.

Response of the site route (`SiteChangeResponse`): `origin`, `source`, `attribution` (null for the sandbox), `data_freshness`, `language`, `interpretation_notice`
and `approximation_notice` (fixed strings in `language`), `scope` (`id`, `name`, `country`, `water_category`, `regime`), `parameter`, `unit`, `group`,
`resolution` (`monthly`, or `annual-only` for the sandbox), `status` (`ok`, `insufficient-data`), `min_samples_per_period`, `periods` (`a` and `b`: `start`, `end`,
`months_in_period`, `n_samples`, `n_unit`, `n_months_with_data`, `mean`, `min`, `max`, `n_below_loq`, `below_loq_share`, `n_lower_reliability`, `meets_minimum_samples`,
`flags`, `assessment` with `limit`, `limit_unit`, `limit_type`, `limit_range`, `limit_basis`, `limit_regime`, `status`, `scored_value`), `change` (`absolute` = mean_B minus
mean_A, `relative_percent`, `relative_percent_note`, `direction`), `crossed_limit` (`within-to-exceeds`, `exceeds-to-within`, `none`, or null), `data_range` (`first`, `last`),
`flags`, `rows_excluded_unit` (Waterbase) and `record_notes` (sandbox: records left out, statistics used).

Response of the country route (`CountryChangeResponse`): `origin` (`real-mixed` when two sources answered), `data_freshness`, `language`, the two notices, `scope`, `parameter`,
`results` (one `CountrySourceChange` per source that holds the parameter for the country, never combined: the site fields above for the paired sites, plus `n_sites_considered`,
`n_sites_paired`, `n_sites_excluded`, `exclusion_reasons`, per period `n_sites`, `mean_of_site_means`, `river_sites_judged`, `river_sites_over_limit`,
`change_of_site_means`, `median_site_relative_change_percent`, `sites_increased`, `sites_decreased`, `sites_unchanged`, `river_limit`, `few_sites_threshold`), `waterbase`
(the store state) and `note` (said when no source holds the parameter). A country comparison uses PAIRED sites only (the sites that meet the minimum in both periods).

Reading it: a period beyond the data (flag `period-outside-data`) is reported with its (empty) numbers and the `data_range`, so a client can suggest the latest available
period; nothing is shifted. Always show `n_samples`, the flags, the limit with `limit_basis` where there is one (and say there is none otherwise), and the notices.

Country-wide comparisons are bounded (security fix F4, `docs/period_change.md` section 11; the same for `GET /bathing-waters/samples/change`). The data are summed per
site inside SQLite, so a request costs memory in proportion to the sites, not the rows; no result number changes. At most 2 country comparisons run at once in a
process and a further one waits at most 5 seconds: it is then refused with **503** (`detail` says the server is busy; header `Retry-After: 5`; the chat tool reports the
same sentence). A **422** says the read would pass a hard cap (2,000,000 monthly rows, 1,500,000 samples, or 120 seconds): narrow the periods. A repeated identical
question (same store file, country, parameter and periods; the language is irrelevant) is answered from a 64-entry, 10-minute cache. The guard and the cache are in
memory and reset on every restart (crash, deploy, probe failure) and are per instance: they smooth bursts, they are not a quota. No field or status was added: 503 and
422 were already declared for these routes.

## `GET /bathing-waters/change` (backend package 5)

Query: `country` (two letters, required), `season_a`, `season_b` (years 1900 to 2100, required), `type` (the file's water type, case-insensitive, at most 64
characters, optional), `language` (optional). Counts of classification transitions between two seasons using ONLY the README order excellent > good >
sufficient > poor; `0 - Not classified`, `3 - Good or Sufficient` and a blank or unknown class are not comparable and are counted separately; a bathing water in one
season only is counted as such. Response (`BathingChangeResponse`): `origin` `real-eea-bathing-water`, `data_freshness`, `attribution`, `language`, `notice` and
`comparison_notice` (fixed strings in `language`), `bathing_water` (store state), `country`, `type`, `season_a`, `season_b`, `order`, `data_range`, `totals` (per
season: bathing waters per class string), `paired_bathing_waters`, `comparable`, `moved_up`, `moved_down`, `unchanged`, `transitions`, `not_comparable` (count and pairs),
`only_in_season_a`, `only_in_season_b`, `flags`. No concentration, no threshold. 422 for a malformed country or season; a country with no bathing-water data, a season outside
the data or a store that is not built answers 200 with zero counts and the flag that says so. The route is declared before `/bathing-waters/{bw_id}`.

## `GET /bathing-waters` and `GET /bathing-waters/{bw_id}` (backend package 4)

Code: `src/oah/bathing/` (`store.py`, `service.py`), route functions in `src/oah/api/routes/bathing.py`. Store, filters and limits:
`docs/bathing_water_store.md`. Protected like every route except `/health`. Every response has `origin` `real-eea-bathing-water`,
`attribution` (`EEA Bathing Water Directive - Status of bathing water, 2025 v.1.0 (EEA CC BY 4.0)`), `data_freshness` (`snapshot`
dated by the store build) and a `notice`: this is the per-season CLASSIFICATION under Directive 2006/7/EC, not a concentration (no
E. coli or intestinal enterococci value exists in this data), not a statement of legal compliance and not a health or safety
determination. No concentration, limit or threshold appears in any field.

`GET /bathing-waters` query (all optional): `country` (two letters, `EL` is read as `GR`), `q` (part of a name or identifier, at most 64
characters, case-insensitive, `%` and `_` literal), `type` (the file's water type, for example `coastalBathingWater`, `lakeBathingWater`,
`riverBathingWater`, `transitionalBathingWater`; case-insensitive, at most 64 characters), `quality` (the class of the LATEST season, either
the file's string such as `1 - Excellent` or its label `Excellent`, case-insensitive, at most 64 characters), `limit` (1 to 500, default
200), `offset` (0 or more). Response: `bathing_water` (store state: `ready`, `not-built` with the build command in `detail`, or
`unreadable`), `bathing_waters`, `total_matching`, `returned`, `limit`, `offset`, `truncated`. Without a built store the list is empty and
the state says why. Each entry: `id`, `country`, `name` (the identifier when the file's name is the placeholder `UNKNOWN`), `type`,
`geographical_constraint` (as written), `group_identifier`, `latitude` and `longitude` (nullable, with `location_status` `located` or
`no-location`), `bw_profile_url` (plain text from the file, only `http(s)` URLs are kept, otherwise null; the API never fetches it and a
client must not turn it into an automatic link), `first_season`, `latest_season`, `n_seasons`, `latest_quality` (the file's string, null
when blank), `latest_quality_class` (its label), `origin`, `source`.

`GET /bathing-waters/{bw_id}`: the entry above as `bathing_water`, plus `history`, one item per season oldest first: `season`, `quality`
(the file's string; a value the project has not seen is passed as written, `null` when blank), `quality_class`, `monitoring_calendar`
(for example `1 - Implemented`; blank before the 2018 season), `management` (for example `1 - Continuously monitored`; blank before
2013), and `profile_note`. 404 for an unknown identifier (the detail names the store state when it is not ready).

Countries in the 2025 v1.0 file: Greece (stored `GR`, written `EL` in the file) and Italy; there is no Norwegian row, so `country=NO`
returns an empty list.

Added with the bathing-water SAMPLES (backend package 6): `GET /bathing-waters/{bw_id}` also returns `samples`, a link block: `state`
(`ready`, `not-built`, `unreadable`), `available` (whether individual samples exist for this bathing water), `n_samples`, `first_sample_date`,
`last_sample_date`, `first_season`, `last_season` and `path` (`/bathing-waters/{bw_id}/samples`, null when there is none). The classification itself
is unchanged and still never a concentration.

## `GET /bathing-waters/{bw_id}/samples` and the sample comparisons (backend package 6)

Code: `src/oah/bathing_samples/` (`store.py`, `service.py`, `change.py`), `src/oah/api/samples.py`, models in `src/oah/api/samples_schemas.py`. Store, extraction,
observed limits, value kinds and limitations: `docs/bathing_samples_store.md`. Protected like every route except `/health`. Every response has `origin`
`real-eea-bathing-samples` (a NEW origin value: the individual E. coli and intestinal enterococci results are a different dataset from the classification, whose
`real-eea-bathing-water` is documented as "never a concentration"), `attribution` (`EEA Bathing Water Directive, monitoring results via Discodata (EEA CC BY 4.0)`),
`data_freshness` (`snapshot` dated by the store build), `unit` (`cfu/100ml`, from the Discodata table metadata) with `unit_statement`, `language` and three fixed notices in
that language (`notice`: individual results, not a classification and not a compliance assessment; `no_threshold_notice`: no threshold or limit is applied, none exists in this
project for these bacteria; `flagged_values_note`: flagged values are counted apart), plus `bathing_samples` (the store state, like `bathing_water`).

`GET /bathing-waters/{bw_id}/samples` query (all optional): `date_from`, `date_to` (ISO days, sample date, both included; `date_from` after `date_to` is 422), `season`
(1900 to 2100), `limit` (1 to 500, default 200), `order` (`asc` by sample date then record id, default, or `desc`), `language`. Response: `bathing_water` (`id`,
`country`, `name`, `type`; from the classification store, or the identifier alone when only the samples store knows it), `filters` (echoed), `data_range` (the
bathing water's all-time first and last sample date and season, null when it has none), `total_matching`, `returned`, `limit`, `truncated`, `samples`, `summary`, `flags`.
Each sample: `uid` (EEA record id), `sample_date`, `season`, `sample_status` (as written: `preSeasonSample`, `shortTermPollutionSample`, `confirmationSample`,
`replacementSample`, `missingSample`; null for a routine sample), `observation_status` (the EEA record-reliability code as written, `A`, `I`, `O` or `U`; not interpreted),
`has_remarks` (the text is not stored or served), and for each of `escherichia_coli` and `intestinal_enterococci` an object `{value, reported_value, status, kind}`:

| `kind` | Meaning | `value` | `reported_value` |
|---|---|---|---|
| `quantified` | no EEA status: a measured concentration | the number | the number |
| `confirmed-high` | status `confirmedValue` (an exceptionally high value, confirmed): a measured concentration, flagged | the number | the number |
| `detection-limit` | status `limitOfDetectionValue`: the number is a limit of detection, NOT a concentration | null | the limit of detection as reported |
| `missing` | status `missingValue` (the source writes a placeholder 0) or no value | null | null (the placeholder is not shown) |
| `unknown-status` | a status the project has not seen: kept, never used | null | the number as reported |
| `invalid` | a value that is not a non-negative whole number | null | null |

`summary` covers ALL samples matching the filters, not only the page, per indicator: `n_samples_in_range`, `n_quantified`, `n_confirmed_high` (included in `n_quantified`),
`n_detection_limit`, `n_missing`, `n_unrecognised`, `min`, `max`, `mean` (sum over `n_quantified`, 6 decimals) and `median` (exact: the middle value, or the mean of the two middle
values). Only `quantified` and `confirmed-high` values are in them. `flags`: `no-samples-in-range`, `range-outside-data`, `no-samples-for-bathing-water`, `store-not-ready`,
`truncated`, `detection-limit-values-excluded`, `missing-values-excluded`, `unrecognised-status-values-excluded`, `confirmed-high-values-included`. 404 for a bathing water that neither
the classification store nor the samples store knows (the detail names the store state when it is not ready); a known bathing water without samples is a 200 with the flag.
422 for a malformed date, `season`, `limit`, `order`, an inverted window or an unknown language. No field of the response is a limit, a threshold, a class or a verdict.

`GET /bathing-waters/{bw_id}/samples/change` and `GET /bathing-waters/samples/change` (the second for a country: `country`, two letters, `EL` is read as `GR`) take `a_from`, `a_to`,
`b_from`, `b_to` (`YYYY-MM`, both ends included; period A against period B) and `language`. They reuse the period machinery of `docs/period_change.md` with the parameter declared
MEASUREMENT ONLY: the same coverage rule (a period needs 3 quantified samples at one bathing water; below that `status` is `insufficient-data` and the numbers are still given), the
same flags (`period-outside-data` with `data_range`, `partial-period`, `periods-overlap`, `relative-change-undefined`, `no-data-for-scope`, `few-sites`) and nothing is shifted or filled. Bathing
waters are sampled in the bathing season only (almost all data lie in months 03 to 10 in Italy and 05 to 10 in Greece), so any period that includes other months carries `partial-period`; compare like with like.
Site response: `scope`, and for each indicator `status`, `min_samples_per_period`, `periods` (`a`, `b`: `n_samples` of quantified values, `mean`, `median`, `min`, `max`, `n_detection_limit`,
`n_missing`, `n_unrecognised`, `n_confirmed_high`, `meets_minimum_samples`, `flags`), `change` (of the mean: absolute = mean_B minus mean_A, `relative_percent`, direction), `change_of_median`,
`data_range` (first and last month with a quantified value, all time) and `flags`; plus `change_notice` (no significance is tested, no limit exists, so no limit crossing). Country response: paired
bathing waters only (a bathing water must meet the minimum in BOTH periods; the same set is used in both), `n_sites_considered`, `n_sites_paired`, `n_sites_excluded`, `exclusion_reasons`, per period
`n_sites`, `n_samples`, `mean_of_site_means`, `median_of_site_medians`, the counts of flagged values over ALL bathing waters of the country in the period (`..._all_sites`), `change_of_site_means`,
`change_of_site_medians`, `median_site_relative_change_percent`, `sites_increased`, `sites_decreased`, `sites_unchanged`; a country with no samples (Norway, a store that is not built) answers 200
with the response flag `no-samples-for-country` or `store-not-ready`. No limit, no `crossed_limit`, no significance claim anywhere. A country comparison of Italy reads about 50,000 monthly cells and takes
a few seconds.

`/countries`: the `bathing_water` block of Greece and Italy gains `samples` (`origin`, `bathing_waters_with_samples`, `n_samples`, `n_quantified` per indicator, `first_sample_date`, `last_sample_date`,
`first_season`, `last_season`, `unit`, `attribution`, `content` `individual-samples-no-thresholds`), null when the samples store is not built; the response gains `bathing_samples` (the store state).

## `POST /chat` (backend package 2)

Code: `src/oah/chat/` (`tools.py`, `agent.py`, `prompts.py`), `ChatSpendGuard` in `src/oah/api/llm_guard.py`,
orchestration `_chat_with_budget` in `src/oah/api/services.py`. Design, tools, limits and threat model:
`docs/chat_agent.md`. Protected like every route except `/health` (`X-API-Key`, general rate limit) plus its own per-host
limit.

Request (JSON): `message` (1 to 500 characters, not blank), `country` (optional ISO-2, `EL` is read as `GR`, must be a code
of `GET /countries`), `index` (optional: `water-quality`, `water-parameters` or `data-quality`), `history` (optional, at
most 6 turns of `{role: user|assistant, text}`, 1 to 500 characters each; untrusted).

Package 5 adds the tools `compare_periods(scope, id_or_country, parameter, a_from, a_to, b_from, b_to)` and `compare_bathing_seasons(country, season_a, season_b)`
(`docs/chat_agent.md`, `docs/period_change.md`).

The tools also reach the Waterbase store (package 3): `list_sites` takes `country` and an optional name `query` (at most 64 characters)
and lists sandbox and Waterbase sites with their `source`; `get_site_measurements` works for both sources (a Waterbase result carries
`attribution` and `data_freshness` `snapshot`); `get_site_index` refuses a Waterbase site (no index); `list_countries` adds
`latest_year` and `sources`. The system prompt states the data facts (labels, annual aggregates, latest year per country, lakes
without a limit regime, no groundwater).

Package 4 additions: `index` also accepts `microbiology`, which narrows the tools to `list_countries`, `list_bathing_waters` and
`get_bathing_water_history`. `list_bathing_waters(country?, query?, quality?, type?, limit?)` (limit 1 to 50, default 20) and
`get_bathing_water_history(bathing_water_id)` return the EEA bathing-water CLASSIFICATION (origin `real-eea-bathing-water`, with the
attribution and the notice); the selected country is enforced like for sites; the profile URL is not sent to the model. Measurement
records of the added groups carry `group`. The system prompt states that E. coli and intestinal enterococci concentrations and
protozoa are NOT available, that Greece and Italy have bathing-water classification (Norway has none in that file) and that a class
is never a concentration. `list_countries` adds `parameter_groups` and `bathing_water` per country.

Response: `origin` (the source(s) the tool results came from: `real-sandbox`, `real-eea-waterbase`, `real-eea-bathing-water`, `real-eea-bathing-samples`, `external-open-meteo`, `external-gbif` or `real-mixed`), `status` (`answered`, `budget-exceeded`,
`withheld`, `withheld-ungrounded`, `no-answer`), `answer` (null when `withheld` or `withheld-ungrounded`), `country`, `index`, `steps` (one entry per tool call:
`step`, `tool`, sanitised `arguments`, `ok`, short `summary`), `citations` (tool results consulted: `tool`, `site_id`,
`parameter`, `period_start`, `period_end`, `value`, `unit`, `limit_basis`, `source`), `data_freshness`, `grounded`,
`evidence`, `evidence_truncated`, `ungrounded_numbers`, `unit_mismatches`, `unsafe`, `output_flags`, `input_notes` (what was removed or cut from the
question and history), `disclaimer` (the same fixed text as `/explain`), `model`, `usage` (`model_calls` used by this conversation, `max_steps`, token counts;
the process-wide remaining budget, `conversations_remaining_today` and `model_calls_remaining_today`, is NOT public any more), `cached`, and the language fields
(`language`, `answer_en`, `translation_status`, `translated`, `translation_reasons`, `notices`, `translation_checks`).

Errors: 422 invalid input (including an unknown country), 429 with `Retry-After` (60 for the per-minute limit, 3600 for the
daily cap), 502 provider failure (fixed text, upstream text only in the server log; the model client makes no hidden
retries), 503 with the FIXED text "The language-model service is not available." when no model key is configured (it names no
variable or file), sandbox data unavailable, or the audit log cannot be written (nothing is sent in that case). A 429 or 503
before the agent runs consumes no conversation.

Statuses (security hardening, group 2). `answered` only for a grounded, safe answer. `withheld`: an unsafe answer (the flags say
why). `withheld-ungrounded` (new): the grounding check (unchanged) found a number or unit that does not trace to the tool results,
so NO text is returned: `answer` and `answer_en` are null, `grounded` is false, `ungrounded_numbers` and `unit_mismatches` say what,
`notices.withheld_ungrounded_notice` is the fixed, localised reason, and `steps` and `citations` still list the tool results that were
consulted so the web app can show that data. The same holds in every language (never translated, no model call for it).

Evidence summary (new, maintainer-approved; `docs/chat_agent.md` section 10). `evidence` (list of items or null) and `evidence_truncated` (bool,
default false). `evidence` is present ONLY when `status` is `withheld-ungrounded` or `withheld` (an empty list when no consulted tool
returned figures), and null for every other status, an `answered` response included. Each item is the data of one tool result, built by the
backend from the tool results and never from model text: `tool`, `scope` (`type` `site`, `country` or `bathing-water`, `id`, optional `name`),
`parameter` (a parameter or an indicator), `unit`, `period` (first/last period), `origin`, `attribution`, optional `data_kind` (external context), and exactly one of
`values` (at most 10 entries `{period, statistic, value, n, comparator}`, the numbers copied unchanged) or `summary`
(`{kind: "observed-range", n, minimum, maximum, n_censored, first_period, last_period}`: an observed range, not a statistical interval). At most 20 items
and 12000 characters; `evidence_truncated` is true when items were left out. When `evidence` is not null `notices.evidence_notice` is the fixed,
localised explanation for the web app (25 languages).

Rendering rules: plain text only, show `grounded` and the `disclaimer`; when `status` is `withheld` or `withheld-ungrounded` the
`answer` is null and the flags, the notice and the citations are shown instead. `/explain/*` follows the same rule (next sections).

## Access control and abuse limits (security hardening, group 2)

* **Order of checks (F2).** Every route except `GET /health` runs ONE dependency (`oah.api.deps.authenticate_and_limit`): the `X-API-Key`
  is checked FIRST. A wrong or missing key gets 401 (the same body for both, no hint about the key, its length or its form) and is
  charged only to a separate per-client limiter of failed attempts (60 per 60 s per client address; beyond it 429 with
  `Retry-After: 60`); it never touches the bucket of authenticated callers, so a flood of bad requests cannot make legitimate
  callers receive 429. An accepted key (or the local-demo flag) then goes through the normal rate limiter (`OAH_RATE_LIMIT_MAX_REQUESTS` per
  `OAH_RATE_LIMIT_WINDOW_SECONDS` per client address). No key configured and no local-demo flag: 503 (fail closed), no bucket used. The
  comparison is constant-time. `/health` needs no key and has no limit.
* **Key strength (F11).** On Cloud Run (the platform sets `K_SERVICE`) the service REFUSES TO START unless `OAH_API_KEY` is set and has at
  least 32 characters, and refuses to start when `OAH_INSECURE_NO_AUTH` is on. Elsewhere a shorter key only logs a warning ("too short",
  never the key or its length) and keeps working, so local development is not broken. Use a random key of 32 or more characters.
* **Client address behind Cloud Run (F3a).** `OAH_TRUSTED_PROXY_HOPS` (default 0 = off, the old behaviour, range 0 to 5): the number of
  trusted proxies in front of the service, counted from the RIGHT of `X-Forwarded-For`; the client is the entry that many places from the right,
  so a spoofed leading entry changes nothing. A chain shorter than the hop count, an empty entry or an entry that is not an IP address falls
  back to the peer. It is safe only when every request really passes through that many proxies (Cloud Run's front end: 1; verify it before
  relying on it). A peer listed in `OAH_TRUSTED_PROXIES` keeps the address-based rule, which takes precedence. Not enabled in the service file yet.
* **End-user token (F3b).** `POST /chat` and `GET /explain/*` accept an optional `X-OAH-End-User` header: an opaque token of 16 to 64
  characters of `A-Z a-z 0-9 _ -`, which the trusted web server layer (Vercel) can set to a keyed hash of a visitor. It is UNTRUSTED input (anyone
  holding the shared key can send any value) and is a FAIRNESS AID, not authentication: it only adds a second part to the key of the per-minute
  chat and explanation limiters, so visitors who share one proxy address stop sharing one per-minute bucket. An absent or invalid value is
  ignored (the bucket is the client address alone). It is never logged and never stored; the general limiter, the daily caps and the shared
  key (the access control) are unchanged. A key holder who rotates tokens escapes the PER-MINUTE bucket only; the daily caps still bound spend.
  The real per-visitor limiting and bot protection (firewall rule, challenge, per-visitor limit in the route handler) must live at the Vercel layer.
* **Write routes (F5).** `POST /review/{specimen_id}/decide`, `POST /fhir/export` and `POST /fhir/export/indicators` change state or write files, so they
  answer 404 with the body `{"detail": "Not Found"}` (as if the route did not exist) unless `OAH_ENABLE_WRITE_ROUTES` is truthy (`1`, `true`, `yes`; default off).
  The key is checked first, so an unauthenticated caller learns nothing about the switch. The routes stay in `docs/openapi.json` (the committed contract and
  the route table of `docs/architecture.md` list them) with the 404 documented. The read-only review queue (`GET /review/queue`, the `review-queue` index,
  now titled "Review queue (read-only)", applicability unchanged), `/reliability/campaign` and `/risk/{site_id}` stay available: the campaign parameters are
  bounded (seed 0 to 2,000,000,000, 2 to 30 observers, 1 to 200 specimens per site, 2 to 10 annotators per specimen) and its result is cached (last 32 distinct
  requests, least recently used out), and the risk route is a tiny fixed graph.
* **Audit log (F9).** The audit records hold digests, counts and flags only: no question text, not even a redacted excerpt (`question_excerpt` is gone from
  `chat-dispatch`; `chat-tool-result` carries `error_sha256` instead of the message). Each record is also written as one JSON line on stdout
  (`severity`, `message` `oah-llm-audit`, `audit` = the record) so Cloud Logging keeps it across restarts, and at most 4 rotated files are kept next to the current
  one (`oah.explain.audit.MAX_ROTATED_FILES`, oldest removed first); `verify_all` verifies what remains. Details: `docs/architecture.md`.

## External context: `GET /sites/{site_id}/weather`, `/discharge`, `/species` and `GET /external/status` (backend package 7)

Optional, additive, protected like every route (`X-API-Key`, general rate limit). Design, providers, limits, formulas, threat model and
the taxon keys: `docs/external_context.md`. The data come from public providers, fetched by the backend only (a hardened GET client
behind a cache and a call budget), and are EXTERNAL context: `origin` is `external-open-meteo` or `external-gbif` (a closed set of
its own, `ExternalOrigin`; the shared `Origin` is unchanged), `data_kind` says what the numbers are (`modelled-reanalysis`,
`modelled-river-discharge`, `opportunistic-occurrence-records`), `attribution` (display it next to the data), `attribution_url`,
`attribution_verified` (false when the credit wording could not be verified at the provider), `licence`, `data_note`, `flags`, `cached`,
`site` (id, name, `kind` `waterbase-site` / `sandbox-site` / `bathing-water`, country, `water_category`, and the latitude and longitude
at the precision actually sent, `coordinate_decimals` 2), `language` and `notices` (the fixed strings that apply, localised; the keys
are `external_context_notice`, `external_reanalysis_notice`, `external_discharge_notice`, `external_occurrence_notice`,
`external_licence_notice`, `external_no_causation_notice` and, when the provider could not be used, `external_unavailable_notice`).
These values are never the site's own measurements and never evidence of causation, and they do not enter an index, a limit
comparison or a period comparison. No route takes a latitude, a longitude, a URL or a host: coordinates come only from the site (a contract test pins the parameter
names). Unlike the stores' routes these responses carry no `data_freshness`: they are live or cached provider answers, and `cached` says which.

`status`: `ok`; `no-data` (the provider answered but holds nothing for the period, or the period lies outside its data); `external-unavailable`
with a `reason` (`disabled`, `budget-exhausted`, `cooling-down`, `timeout`, `rate-limited`, `network-error`, `http-error`, `bad-response`,
`response-too-large`, `redirect-refused`, `blocked-target`). A provider problem is an HTTP 200 with that status (the context is optional and must
never look like a core failure; a client shows a card state), never a 500. Errors: 404 unknown site, 422 an invalid or unlocated site (no
coordinates or a restricted Waterbase site: the detail says `no-location`, and no provider is called), an invalid, inverted or too long period, an unknown `group`, a `limit` outside 1 to 200, a bathing water for discharge or
species, or an unsupported `language`; 429 rate limit; 401/503 as everywhere.

The in-memory protections of this section (the result cache, the per-minute and per-day call budgets, the cool-down and the circuit breaker) **reset on every restart**
(a crash, a deploy, a scale-to-zero, a failed probe) and are per instance, so they smooth bursts and repeated questions but promise no daily ceiling: **the providers' own
budgets are the real ceiling** (`docs/external_context.md`, sections 4 and 6).

| Route | Query | Response (besides the common fields) |
|---|---|---|
| `GET /sites/{site_id}/weather` | `date_from`, `date_to` (ISO dates, required, at most 1096 days), `language` | `dataset`, `period`, `data_limits` (`first_day` 1940-01-01, `last_day_requestable`, `era5_delay_days` 5, `latest_day_expected_final`, `model` `era5`, `day_boundary` UTC), `grid` (requested and used grid cell, `distance_km`, `resolution_note`), `months` (per `YYYY-MM`: `days_in_window`, `precipitation_sum_mm`, `precipitation_n_days`, `precipitation_coverage`, `temperature_mean_c`, `temperature_n_days`, `temperature_coverage`, `flags`), `n_days_expected`, `n_days_with_data`. Flags: `era5-delay` (the period ends within 5 days of today), `period-end-clipped`, `period-start-clipped`, `period-outside-data`, `partial-month`, `implausible-values-ignored`. A site, a sandbox site or a bathing water is accepted. |
| `GET /sites/{site_id}/discharge` | same | `dataset`, `period`, `data_limits` (`first_day` 1984-01-01, `documented_history_end` 2022-07-31 and a note, `model` `consolidated_v4`), `site_water_category`, `grid`, `data_range` (first and last day with a value), `months` (`river_discharge_mean_m3s`, `n_days`, `days_in_window`, `coverage`, `flags`), `n_days_expected`, `n_days_with_data`. Flags: `nearest-cell-may-not-be-the-river` (always), `site-not-a-river` (a lake or coastal category), `period-outside-data` (a month with no value), `beyond-documented-history` (a month after July 2022, the end of the provider's documented history), `partial-month`. Water-quality sites only. |
| `GET /sites/{site_id}/species` | `group` (optional: `ephemeroptera`, `plecoptera`, `trichoptera`, `ept`, `odonata`, `chironomidae`, `gammaridae`, `unionida`), `date_from`, `date_to` (event date, optional), `limit` (1 to 200, default 50), `language` | `search` (a 10 km square: centre and bounds), `filters`, `limit`, `total_records` (GBIF's count), `returned`, `n_records_skipped`, `group_counts` (GBIF's facet counts per searched group, with a caveat), `records` (per record: `gbif_id`, `scientific_name`, `group`, `basis_of_record`, `event_date`, `year`, rounded coordinates, `coordinate_uncertainty_m`, `distance_km`, `licence` `CC0-1.0` / `CC-BY-4.0` / `CC-BY-NC-4.0` / `other-or-unspecified`, `licence_text`, `non_commercial_only`, `dataset_key`, `dataset_name`, `publishing_organization_key`, `institution_code`, `rights_holder` (always null: an individual's name is not passed on), `record_url` (only an https URL on gbif.org, else null), `coordinate_issues`, `citation`), `datasets` (title and citation text as GBIF provides it, at most 5), `licence_summary`, `taxa_file`. Flags: `truncated`, `citations-partial`, `non-commercial-licence-records`. Neither the observer's name nor the rights holder is passed on. Water-quality sites only. |
| `GET /external/status` | `language` | `enabled`, `providers` (per provider: `enabled`, `cooling_down`, `attribution`, `attribution_url`, `attribution_verified`, `licence`, `licence_note`, `limits`, `data_note`, `budget_unit`, `budget` with the limit and what remains per minute and per day), `contact_url_configured` (the URL itself is never shown), `coordinate_decimals`, `max_period_days`, `species_*` limits, `species_groups` (id, name, rank, GBIF key, match confidence, caveat), `species_group_aliases`, `taxa_discovered_on`, `notices`. No secret. |

Chat: three tools `get_weather_context(site_id, date_from, date_to)`, `get_river_discharge_context(site_id, date_from, date_to)` and
`get_species_nearby(site_id, group?, date_from?, date_to?)` (`docs/chat_agent.md`); the selected `index` `water-quality` and `water-parameters` also
offer them and `microbiology` offers the weather tool; a chat answer whose tool results were all external has `origin` `external-open-meteo` or
`external-gbif` (`ChatOrigin`), any mix is `real-mixed`.

## Answer languages (language package)

Design, threat model, checks and limits: `docs/language_support.md`. Code: `src/oah/i18n/`, wiring in `src/oah/api/services.py`.

**Input.** `POST /chat` takes an optional `language` in the body; `GET /explain/indices/{location_id}` and
`GET /explain/review/{specimen_id}` take an optional `language` query parameter. A code of `GET /languages`, case-insensitive,
`_` or `-`; a bare `es` means `es-MX`; `no` means `nb`. Omitted: `OAH_DEFAULT_LANGUAGE` (default `en`). An unknown code (or a value
that is not 2 to 12 characters) is a 422 whose message lists the supported codes; nothing is reserved or sent before that check.

**Output (additive, required fields of `ChatResponse` and `ExplanationResponse`).**
`language` (canonical code), `answer_en` (the validated English answer; null when English was requested or when nothing is shown),
`translation_status` (`not-needed`, `ok`, `rejected`, `failed`), `translated` (true only for a model translation that passed the
checks), `translation_reasons` (codes such as `number-added`, `contains-url`, `budget`, `provider-error`, `timeout`,
`llm-not-configured`, `english-answer-unsafe`; never text), `notices` (fixed notices in the answer language: always
`interpretation_notice`; `machine_translation_notice` when `ok`; `translation_fallback_notice` when `rejected` or `failed`;
`withheld_notice` when unsafe; `withheld_ungrounded_notice` when withheld as not grounded). `disclaimer` is localised. `translation_checks` (new):
how far a translation into the language is verified, `neutral-and-denylist` (numbers, links and markup, length, copied instructions and a
best-effort list of potability and safety words; es, it, el, fr, de, pt, nb) or `neutral-only` (the same without the word list; the other 19), null for
English; `GET /languages` carries it per language. A client labels every translated text "machine translation" and shows `answer_en`; for
`neutral-only` it should also say the translation is unverified. Neither level proves the meaning is preserved.
`answer` (chat) and `explanation` (explain) are the translation when `ok`, otherwise the English text.

Rules: the grounding and unsafe flags describe the English answer. An unsafe English answer is never translated
(`translation_status` `not-needed`, reason `english-answer-unsafe`) and is never returned in either route: chat `answer` and `answer_en`
are null, and so are explain `explanation` and `answer_en` (changed: explain used to return the unsafe text marked `unsafe`).
The explanation routes gain a required `status` (`answered`, `withheld`, `withheld-ungrounded`) and `explanation` is nullable; an English
answer that is not grounded is withheld like the chat (`withheld-ungrounded`, reason `english-answer-ungrounded`, no text, no translation, no
translation cost) and the `evidence` stays in the response so a client can still show the data. `not-needed` also covers a chat budget-exceeded or no-answer text,
which is a fixed string in the requested language (no model call). A rejected or failed translation is never a 4xx or 5xx: the English
answer comes back with the status. For an `assess` explanation the translated text follows the model's wording; a client that needs
the `Concern level:` line must read it from `answer_en`.

**Cost.** The English answer is produced exactly as before. One more model call translates it. Explain: one more unit of the daily
cap (`OAH_EXPLAIN_DAILY_CAP`); when the cap is reached the translation is `failed` with reason `budget` and the route still answers.
Chat: the call is counted by `try_reserve_model_call` (the rolling model-call cap, `daily cap x max steps`), not as a conversation, so
a translated conversation can use `max_steps + 1` model calls and `usage.model_calls` includes it. The English result and each
translation are cached separately; the translation key holds the language and the translation model, so languages never share a
text and the English entry is reused. Only an accepted translation is cached.

**Audit.** `translation-dispatch` (before the call), then `translation-result`, `translation-rejected` or `translation-error`, and
`translation-cache-hit`: language, model, SHA-256 and sizes, reason codes, tokens; never the text. An unwritable log is a 503.

**Settings.** `OAH_TRANSLATION_MODEL` (default: the model of `OAH_LLM_MODEL`), `OAH_TRANSLATION_TIMEOUT_SECONDS` (default 30, at most 60),
`OAH_DEFAULT_LANGUAGE` (default `en`, validated at start-up).

### `GET /languages`

Protected like the other routes. `default_language`, `source_language` (`en`), `languages` (26 entries: `code`, `name`, `endonym`,
`status` `source` or `translated-by-model`, `script`, `direction`, `tier`, `fixed_strings_review_status` `source` or
`machine-draft`) and a `note`. The 26 are the 24 official EU languages (Spanish as `es-MX` and `es-ES`) and Norwegian Bokmal. Every
language except English is machine-translated and flagged as such; none was reviewed by a human.

## OpenAPI file

`scripts/export_openapi.py` writes `docs/openapi.json` from `app.openapi()` (sorted keys, no server, no network); `--check`
fails when it is stale. `tests/contract/test_openapi_file.py` fails when the committed file differs from the app, so run the
script after changing a route or a model.
