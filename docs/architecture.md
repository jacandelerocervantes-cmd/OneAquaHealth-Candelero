# Architecture

The sole application package is `src/oah`. `oah.paths` resolves the root from the `pyproject.toml` marker; no module may depend on the directory from which the process starts.

Official inputs are frozen in `reference/` and validated with SHA-256. `oah-extract-ig` verifies the archive and extracts its official `input/`, `models-src/`, and `sushi-config.yaml` contents into `ig/oah`. Real OAH FHIR profiles come from that extraction, not from reference repositories. Sandbox data, responses, and caches live outside the repository through `OAH_DATA_DIR`, or in the user cache when it is unset.

The planned flow is: ingest -> qc -> fhir -> indices/reliability/uncertainty -> review/risk/privacy -> audit/api. Layers do not import source repositories; provenance belongs in `SOURCES.yaml`.

The first ingest slice performs GET-only, paginated reads and snapshots only to `OAH_DATA_DIR`. QC returns immutable findings; it never changes source resources. FHIR validation has an R4B structural layer and a deliberately limited profile-derived layer.

`src/oah/indices/` splits the CCME water-quality index work by responsibility.
`water_parameter_limits.py` is pure (no I/O): the closed FHIR-code-to-limit mapping, UCUM unit
conversion, profile matching, and physical-plausibility checks. `sandbox_loader.py` is generic
sandbox-resource loading with freshness (snapshot fallback, then the live sandbox, then a stale
snapshot as a last resort) -- not CCME-specific, and used by `oah.api.services` too.
`apply_to_sandbox.py` keeps only the CCME WQI pipeline itself and the site-listing join
(`apply_ccme_wqi_to_sandbox`, `list_sites_with_status`, the veto assessment), built on top of the
other two modules.

## API layer (`src/oah/api`)

`src/oah/api/app.py` holds the single FastAPI instance (`app`). `src/oah/api/__init__.py`
deliberately does not re-export it, to avoid a package/submodule name collision; always import
it as `from oah.api.app import app`, or reference it as the string `"oah.api.app:app"` (used
by `scripts/run_api.py` for uvicorn). The API adds no business logic of its own -- every route
is a thin wrapper around an already-tested `oah.*` function, either directly or via
`src/oah/api/services.py`. Every response that can describe either kind of data carries an
explicit `"origin"`: `"real-sandbox"` or `"synthetic"`.

`oah.api.services` holds the orchestration steps that are more than routing but still add no new
business logic of their own: the freshness-aware sandbox fetch+cache machinery
(`get_cached_observations`/`get_cached_locations`, backed by a TTL cache, and
`get_data_freshness`), the LLM explanation budget (`_explain_with_budget`, the cache/daily-cap
sequence over `oah.explain`), the reliability-campaign pipeline (`run_reliability_campaign`,
sequencing `oah.synthetic` and `oah.reliability`), and the FHIR export pipelines
(`export_findings_bundle`, `export_indicators_bundle`, over `oah.fhir.output.export`). Functions
there that wrap a seam the test suite monkeypatches (`get_llm_client`, `get_llm_guard`, `export_path`)
take that seam as an explicit parameter supplied by the route, which looks it up as `deps.NAME` at call
time, so the monkeypatch targets stay on `oah.api.deps` without `services.py` importing it back (see
"Module layout" below).

### Module layout (refactor of 2026-10-03, no behaviour change)

The former single modules were split by responsibility; every public name is re-exported by the original
import path, and the route table, the OpenAPI document and the tool definitions sent to the model are
byte-identical.

| Path | Holds |
| --- | --- |
| `oah/api/app.py` | the FastAPI instance `app` (ASGI entry point `oah.api.app:app`), the limit-override check at startup, `GET /health`, the protected router |
| `oah/api/routes/` | one `APIRouter` module per domain: `quality` (QC report, FHIR exports), `sites` (sites, countries, measurements, index), `catalog`, `bathing`, `change`, `external`, `explain`, `chat`, `languages`, `synthetic`; `__init__` builds `protected_router` (rate limit, then API key, plus the shared 401/429/503) |
| `oah/api/deps.py` | settings, rate limiter, spend guards, review store, LLM client, sandbox accessors and the `enforce_*` dependencies: the test seams, always looked up as `deps.NAME` |
| `oah/api/payloads.py`, `oah/api/chat_context.py` | payload assembly shared by routes and chat (`_indices_payload` and `get_external_context` are seams, looked up as `payloads.NAME`); the chat `ToolContext` |
| `oah/api/middleware.py` | CORS and the security headers |
| `oah/api/schemas/` | response models, one module per domain, all re-exported by `oah.api.schemas` |
| `oah/api/services.py`, `oah/api/llm_services.py` | sandbox fetch and cache, reliability and export pipelines; the explanation budget, translation and chat orchestration |
| `oah/chat/tools/` | `context`, `definitions`, `validation`, `results`, the handlers by family (`sites`, `bathing`, `comparison`, `samples`), `approximate` (the `approximate` block of the statistics tools), `dispatch`, `citations` |
| `oah/chat/precision.py`, `oah/chat/evidence.py` | the presentation-rounding policy (significant figures by sample count, outward observed range; not statistical uncertainty); the evidence summary of a withheld chat answer, built from the tool results (`docs/chat_agent.md` sections 10 and 11) |
| `oah/indices/period_change/` | `periods` (inputs), `stats` (arithmetic), `limits` (limit machinery), `compare` (site and country) |
| `oah/indices/scope_guard.py`, `oah/indices/sqlite_aggregates.py`, `oah/waterbase/scope_read.py` | the process-wide concurrency guard and result cache of country-scope comparisons; the shared SQLite aggregates (exact sum, month mask, read guard); the Waterbase SQL aggregation (`docs/period_change.md` section 11) |
| `oah/bathing_samples/`, `oah/waterbase/` | `build.py` sequences the stages; `extract`/`normalise`/`storage` (samples) and `aggregate`/`spatial`/`storage`/`archive` (Waterbase) hold them |

The registration order of the routes is by domain module, not the former file order; no two routes overlap
ambiguously across modules (a probe of every path template confirmed the same route answers each URL).

Every route except `GET /health` sits behind `protected_router`, which attaches ONE
dependency to every route it holds, `oah.api.deps.authenticate_and_limit` (security hardening F2): the key
decision of `oah.api.auth.key_decision` comes FIRST (fail closed: `503` with no key and no local-demo flag; a
wrong or missing `X-API-Key` is a `401` charged only to a separate failed-attempt limiter, 60 per 60 s per client
address, then `429`), and only an accepted request goes through `oah.api.rate_limit` (a fixed-window limiter per
client host, default 60 requests/60s via `OAH_RATE_LIMIT_MAX_REQUESTS`/`OAH_RATE_LIMIT_WINDOW_SECONDS`, `429`
once exceeded). A flood of unauthenticated requests therefore cannot use up the authenticated bucket. The three
state-changing routes (`POST /review/{specimen_id}/decide`, `POST /fhir/export`, `POST /fhir/export/indicators`)
add `oah.api.deps.require_write_routes` and answer 404 unless `OAH_ENABLE_WRITE_ROUTES` is on (default off;
`docs/api_routes.md`, "Access control and abuse limits"). CORS is configured once at app construction from `OAH_CORS_ORIGINS`
(comma-separated; default: common local frontend dev ports 3000/5173 on localhost and
127.0.0.1). `/health` is deliberately exempt from all three, so health checks and load
balancers never need the key and are never rate-limited.

| Method & path | Wraps | Origin |
| --- | --- | --- |
| `GET /health` | -- | -- |
| `GET /qc/report` | `oah.qc.report.build_report` over cached sandbox Observations | real-sandbox |
| `GET /sites` | `oah.indices.apply_to_sandbox.list_sites_with_status` (sandbox Locations with a map position, joined to their own CCME WQI result) followed by the EEA Waterbase sites of `oah.waterbase.store` (measurements only); bounded by `limit` (default 200, at most 500), `offset`, `country`, `q`, `source` (`docs/api_routes.md`, `docs/waterbase_store.md`) | real-sandbox, real-eea-waterbase (each site labelled; `real-mixed` for a list holding both) |
| `GET /countries` | `oah.indices.countries.countries_overview` over `list_sites_with_status`, the regime tables, the Waterbase country summaries (with the parameter groups held) and the bathing-water block per country, with a per-source breakdown (`docs/api_routes.md`) | real-sandbox, real-eea-waterbase, real-eea-bathing-water (the `bathing_water` block) |
| `GET /catalog` | `oah.indices.catalog` (pure rules) fed by `oah.api.payloads._catalog_payload`: the families and indices of the web app sidebar for ONE required `country` (`EL` is read as `GR`; unknown is 422 with the known codes), each with `applies` and, when not, a `reason_code` and a localised `reason`; applicability is derived from the data held (the `/countries` summaries, the located-site counts of the Waterbase and bathing-water stores, the samples store, the external-context switches), never from a country list; optional `language` (`docs/api_routes.md`, `docs/indices_catalog.md`) | real-sandbox, real-mixed (like `/countries`; each index names its own `origins`) |
| `GET /sites/{location_id}/measurements` | `oah.indices.site_measurements.site_measurement_records` -- per-parameter values behind the score; for a Waterbase site `oah.waterbase.measurements.annual_records` -- annual aggregates, optional `group` filter (`docs/api_routes.md`, `docs/waterbase_store.md`) | real-sandbox, real-eea-waterbase |
| `GET /sites/{site_id}/change` | `oah.api.change.site_change` over `oah.indices.period_change.compare_site` (pure period comparison: n, mean, min, max, below-LOQ, change, direction, limit and `crossed_limit`) fed by `oah.waterbase.change` (monthly store) or `oah.indices.sandbox_change` (annual aggregates, flagged `annual-only`); query `parameter`, `a_from`, `a_to`, `b_from`, `b_to` (YYYY-MM), `language` (`docs/period_change.md`, `docs/api_routes.md`) | real-sandbox, real-eea-waterbase |
| `GET /countries/{country_code}/change` | `oah.api.change.country_change` over `oah.indices.period_change.compare_country`: PAIRED sites only, one result per source (never combined), optional `source`; same query as the site route (`docs/period_change.md`) | real-sandbox, real-eea-waterbase, real-mixed (one result per source) |
| `GET /bathing-waters/change` | `oah.bathing.change.season_change` -- counts of classification transitions between two seasons in the README order excellent, good, sufficient, poor; `country`, `season_a`, `season_b`, `type`, `language`; no concentration (`docs/bathing_water_store.md`) | real-eea-bathing-water |
| `GET /bathing-waters` | `oah.bathing.store.list_bathing_waters` -- EEA bathing waters with the classification of their latest season; bounded by `limit` (default 200, at most 500), `offset`, `country`, `q`, `type`, `quality` (`docs/bathing_water_store.md`) | real-eea-bathing-water (a classification, never a concentration) |
| `GET /bathing-waters/{bw_id}` | `oah.bathing.store.history` -- the classification of one bathing water by season, with calendar and management status; the `samples` block says whether individual samples exist and the last sample date | real-eea-bathing-water |
| `GET /bathing-waters/{bw_id}/samples` | `oah.bathing_samples.service.samples_for` over `oah.bathing_samples.store` -- the individual E. coli and intestinal enterococci results (cfu/100ml) of one bathing water with both values, both EEA statuses, the sample status and a summary (counts by kind, min, max, mean, exact median of the quantified values); `date_from`, `date_to`, `season`, `limit`, `order`, `language`; no threshold (`docs/bathing_samples_store.md`) | real-eea-bathing-samples (a measurement, never a classification) |
| `GET /bathing-waters/{bw_id}/samples/change` | `oah.bathing_samples.change.site_change` over `oah.indices.period_change.compare_site` (measurement only): per indicator and period n, mean, median, min, max, flagged-value counts, the change of the mean and of the median; query `a_from`, `a_to`, `b_from`, `b_to` (YYYY-MM), `language`; no limit and no significance claim | real-eea-bathing-samples |
| `GET /bathing-waters/samples/change` | `oah.bathing_samples.change.country_change` over `oah.indices.period_change.compare_country`: PAIRED bathing waters only for one country (`country`, EL read as GR), same periods and `language`; no limit, no significance claim | real-eea-bathing-samples |
| `GET /sites/{site_id}/weather` | `oah.external.service.ExternalContext.weather` over `oah.external.openmeteo.weather_context` (Open-Meteo Historical Weather API, ERA5 reanalysis): MONTHLY precipitation sum and mean temperature of a site or bathing water, with `n_days`, `coverage`, the archive limits and the flags (`era5-delay`, `period-outside-data`, `partial-month`); query `date_from`, `date_to` (at most 1096 days), `language`; coordinates only from the stores' sites; a failing provider is HTTP 200 `external-unavailable` (`docs/external_context.md`) | external-open-meteo (MODELLED reanalysis, never a measurement) |
| `GET /sites/{site_id}/discharge` | `ExternalContext.discharge` over `oah.external.openmeteo.discharge_context` (Open-Meteo Flood API, GloFAS v4 consolidated): monthly mean river discharge (m3/s) of the nearest river cell with its distance, `data_range` and the flags `nearest-cell-may-not-be-the-river`, `period-outside-data`, `beyond-documented-history`; water-quality sites only; same query | external-open-meteo (MODELLED discharge, not a gauge) |
| `GET /sites/{site_id}/species` | `ExternalContext.species` over `oah.external.gbif.species_context` (GBIF occurrence search, discovered taxon keys of `oah.external.taxa`): records of freshwater macroinvertebrate groups in a 10 km square around a site with the licence, dataset, publisher and citation of each record and GBIF's own counts per group; query `group`, `date_from`, `date_to`, `limit` (default 50, at most 200), `language`; water-quality sites only | external-gbif (OPPORTUNISTIC records, not monitoring) |
| `GET /external/status` | `ExternalContext.status`: providers with switch, attribution, licence, limits and budget left (no secret), the species groups and the fixed notices; `language` | -- |
| `GET /indices/{location_id}` | `oah.indices.apply_to_sandbox.apply_ccme_wqi_to_sandbox`, filtered to one site | real-sandbox |
| `POST /fhir/export` | `oah.fhir.output.export.build_findings_bundle`; writes to `<data dir>/exports/`; 404 unless `OAH_ENABLE_WRITE_ROUTES` is on | real-sandbox |
| `POST /fhir/export/indicators` | `oah.fhir.output.export.build_indicators_bundle` over `apply_ccme_wqi_to_sandbox`; writes to `<data dir>/exports/`; 404 unless `OAH_ENABLE_WRITE_ROUTES` is on | real-sandbox |
| `GET /reliability/campaign` | `oah.synthetic.campaign` + `oah.reliability` (Dawid-Skene vs. majority vote) | synthetic |
| `GET /review/queue`, `POST /review/{specimen_id}/decide` | `oah.review` + `oah.store.ReviewStore`; the decision route is state-changing and answers 404 unless `OAH_ENABLE_WRITE_ROUTES` is on, the queue is read-only | synthetic (only synthetic conformal output feeds the queue today) |
| `GET /risk/{site_id}` | `oah.risk` over the documented synthetic demo topology (`oah.risk.demo_topology`) | synthetic |
| `GET /explain/indices/{location_id}?mode=&language=` | `oah.explain` over `GET /indices/{location_id}`'s own evaluated-or-skipped result; `language` adds a verified translation of the validated English answer (`oah.i18n`, `docs/language_support.md`) | real-sandbox |
| `POST /chat` | `oah.chat` -- a bounded tool-use agent over read-only wrappers of the routes above (official records only); design, tools and limits in `docs/chat_agent.md`; the optional `language` field adds a verified translation of the validated English answer | real-sandbox, real-eea-waterbase, real-eea-bathing-water, real-mixed (the sources its tool results came from) |
| `GET /explain/review/{specimen_id}?mode=&language=` | `oah.explain` over one `oah.review` queue item (`prediction_set` + `probabilities`); `language` as above | synthetic |
| `GET /languages` | `oah.i18n.languages` -- the 26 answer languages (24 official EU languages with Spanish as es-MX and es-ES, plus Norwegian Bokmal), their status and the default | -- |

Every real-sandbox route works only on official records: `oah.ingest.official.split_official` removes demo,
simulated, synthetic-tagged and third-party Observations first (`docs/official_record_filter.md`). The routes
`GET /countries` and `GET /sites/{location_id}/measurements`, the `kind` field of `/sites`, and the committed
OpenAPI file `docs/openapi.json` are described in `docs/api_routes.md`. The optional EEA Waterbase store (rivers and lakes of
GR, IT and NO, annual aggregates, built by `scripts/build_waterbase_store.py`) is described in `docs/waterbase_store.md`; without it
every route answers as before and says `waterbase.state: not-built`. The optional EEA bathing-water classification store (Greece and
Italy; the file has no Norwegian row; built by `scripts/build_bathing_water_store.py`) is described in `docs/bathing_water_store.md`;
without it the routes answer with `bathing_water.state: not-built`. The optional EEA bathing-water SAMPLES store (Greece and Italy, individual E. coli and enterococci results, no thresholds; built by `scripts/build_bathing_samples_store.py`) is described in `docs/bathing_samples_store.md`; without it the routes answer with `bathing_samples.state: not-built`.

Real-sandbox reads are cached in-process (`src/oah/api/swr_cache.py`, stale-while-revalidate, see "Sandbox cache" below) so
repeated requests do not refetch the live sandbox on every call; the cache is exposed as a
plain function (`get_cached_observations`) so tests can replace it without network access.

## Period comparison (`oah.indices.period_change`)

`GET /sites/{site_id}/change` and `GET /countries/{country_code}/change` answer "how much has X changed between two periods" with deterministic
arithmetic only (no model). `oah.indices.period_change` is pure (cells in, dictionaries out); `oah.waterbase.change` feeds it from the monthly Waterbase store
(schema 3: n, sum, min, max, below-LOQ and lower-reliability counts per site, determinand, matrix, unit, year and month) and `oah.indices.sandbox_change` from
the sandbox annual aggregates (flag `annual-only`, never a pretended monthly resolution); `oah.api.change` assembles the answer for the routes and the chat tool
`compare_periods`. A country uses only sites with enough data in both periods; each period mean is compared with the project limit where one exists through the
existing limit machinery; a period beyond the data is reported with `data_range` and never shifted; the approximation notice (national aggregation rules are not
reproduced; screening aid, not a compliance assessment) is a fixed, localised string. `GET /bathing-waters/change` counts classification transitions between two
seasons in the README order only. Definitions, constants, flags, a worked example and the limitations: `docs/period_change.md`.

Country-wide comparisons are the one expensive read of the API, so they are bounded (security fix F4, `docs/period_change.md` section 11). `oah.waterbase.scope_read` and
`oah.bathing_samples.store.country_window_aggregates` aggregate INSIDE SQLite (Waterbase: `GROUP BY` site and period; `n`, below-LOQ counts, minimum and maximum, an exact `fsum`-equivalent
sum and a month bit mask from the shared aggregates of `oah.indices.sqlite_aggregates`; samples: one sequential pass per indicator over a partial index of the quantified values, with a small aggregate in
`oah.bathing_samples.country_scan` that returns n, sum, minimum, maximum, month mask and the exact median: about 3.4 s for Italy instead of 61 s, `docs/period_change.md` section 11 point 6), so memory grows with the number of sites, not with the rows scanned, and every result
number is unchanged (`compare_country_stats` takes per-site statistics; `compare_country` still takes cells and builds the same statistics). `oah.indices.scope_guard` holds the
one process-wide guard that both sources and both entry points (routes and chat) go through: 2 concurrent comparisons, a 5 second bounded wait then a 503 `ScopeBusy` with
`Retry-After`, a 64-entry 10-minute TTL+LRU result cache keyed by source, store file, country, parameter series and windows (never the language), and a hard cap (2,000,000 monthly
rows, 1,500,000 samples, 120 seconds) that fails with a 422 `ScopeTooLarge`. All of it is per process and resets on every restart. The row-materialising paths
(`oah.waterbase.change.country_change_rows`, `oah.bathing_samples.change.country_change_rows`) remain as the reference of the parity tests and of
`scripts/check_country_scope_parity.py`; no route uses them.

## Bathing-water samples (`oah.bathing_samples`)

The individual E. coli and intestinal enterococci results of Greece and Italy (cfu/100ml) come from the EEA Discodata SQL service, read once by `scripts/build_bathing_samples_store.py` with keyset pages (`OFFSET` is refused by the service), politely paced, resumable and verified against the service's own row count, and stored in their own SQLite store (`OAH_BATHING_SAMPLES_STORE`). The origin is `real-eea-bathing-samples`, a separate label from the classification's `real-eea-bathing-water`. The reader, the three routes (`GET /bathing-waters/{bw_id}/samples`, `.../samples/change`, `GET /bathing-waters/samples/change`), the `samples` link and the `/countries` blocks are read-only over that store; the period comparison reuses `oah.indices.period_change` with the parameter declared measurement only. No threshold, limit or classification rule is applied: values flagged below the limit of detection, missing or of unrecognised status are counted apart and never turned into plain numbers. Without the store the routes answer with `bathing_samples.state: not-built`. Source, observed endpoint limits, value kinds, real build numbers and limitations: `docs/bathing_samples_store.md`.

## External context (`oah.external`)

Optional, server-side only, additive: weather (ERA5 reanalysis, MODELLED), river discharge (GloFAS, MODELLED) and GBIF occurrence records (OPPORTUNISTIC) around a
site, from `GET /sites/{site_id}/weather`, `/discharge`, `/species`, `GET /external/status` and three chat tools (`get_weather_context`, `get_river_discharge_context`,
`get_species_nearby`). Coordinates come only from the stores' sites, are rounded to two decimals and never come from a caller. All outbound traffic goes through one
hardened GET-only client (`oah.external.http`: a three-host allow-list, https, no cross-host redirect, JSON only, size and time caps, bounded retries, a descriptive
User-Agent with the optional `OAH_CONTACT_URL`) behind a TTL+LRU cache and a process-wide call budget (`oah.external.runtime`, in the style of the spend guards). A provider
that is off, over budget, cooling down or failing yields HTTP 200 with `status: external-unavailable` and a `reason`; it never blocks another feature. The values are
labelled with their `origin` (`external-open-meteo`, `external-gbif`), `data_kind`, attribution and licence, carry fixed localised notices, and are never merged with the
EEA or sandbox data nor used in an index or a limit comparison. The chat refuses any causal claim about them (`oah.chat.causation`). Switches: `OAH_EXTERNAL_ENABLED`
and one per provider. Providers, limits, formulas, threat model, taxon keys: `docs/external_context.md`.

## Answer languages (`oah.i18n`)

English pivot: `/chat` and `/explain/*` always produce and validate the answer in English (all guards and the grounding
check unchanged). A `language` other than English adds ONE more, constrained model call that translates the validated
English text; the translation is accepted only after language-neutral checks (identical numeric tokens, no other numeral
systems, no links or HTML, no invisible characters, bounded length, no copied instructions, optional best-effort
denylist for tier-1 languages) and otherwise the English answer is returned with `translation_status` `rejected` or
`failed`. The response always carries `answer_en`. The translation is counted against the existing spend guards (explain:
one more unit of the daily cap; chat: the model-call cap), is cached under a key that includes the language, and is audited
(`translation-*` events: digests only). Fixed notices come from `oah/i18n/strings/` (machine drafts). Settings:
`OAH_TRANSLATION_MODEL`, `OAH_TRANSLATION_TIMEOUT_SECONDS`, `OAH_DEFAULT_LANGUAGE`. Full design, threat model and limits:
`docs/language_support.md`.

## Explanation layer (`oah.explain`)

The two `/explain/*` endpoints add a single, non-agentic Claude Messages API call (`anthropic`
SDK) on top of data another, already-tested `oah.*` module already computed -- never a second
opinion on the underlying numbers, only a plain-English gloss on them for a human reviewer. This
is the concrete "AI-Supported Assessment" (hackathon Track 3) piece of the project's Track 7
submission: "AI prompts, validation checks, explainable AI, human-in-the-loop workflows."

- **Two modes** (`?mode=describe` default, or `?mode=assess`; `oah.explain.prompts.Mode`), each
  its own system prompt and its own API call -- deliberately two separate calls, not one
  combined response, so a caller who needs only the auditable factual description never has to
  pay for or receive the opinionated one:
  - `describe` (`DESCRIBE_SYSTEM_PROMPT`): a strictly factual restatement. Every number, code,
    and label written must come from the EVIDENCE JSON block, mirroring this project's own
    never-invent-a-FHIR-code discipline applied to explanations.
  - `assess` (`ASSESS_SYSTEM_PROMPT`): an interpretive reading on the same evidence -- a concern
    level (low/moderate/high/critical) and a recommended next step for the human reviewer. Its
    qualitative judgment is expected to go beyond the raw evidence (that is the point of this
    mode); any NUMBER it writes is still held to the same never-invent rule.
- **Grounding check** (`oah.explain.grounding`): a deterministic, non-LLM post-hoc check applied
  identically to both modes -- every number the model wrote must trace back to a number already
  present in the evidence (handling rounding to half a unit of the last digit, percentages of fractions, thousands separators, scientific notation and spelled-out numbers; a unit that contradicts the evidence's unit is reported in `unit_mismatches`; measured rates and blind spots are in `docs/math_registry.md`); it only flags invented
  numbers, so `assess` mode's qualitative judgment itself is never flagged. This is the
  "validation check" half of the story: a response is never silently trusted just because the
  model produced fluent text. A response that fails is still returned (never hidden), with
  `"grounded": false` and the exact offending numbers in `"ungrounded_numbers"`, so a human
  reviewer sees the flag.
- **Model** (`oah.config.Settings.llm_model`, env `OAH_LLM_MODEL`, default `claude-sonnet-5-5`): the
  Anthropic client itself is only constructed from `ANTHROPIC_API_KEY` (`.env` or process
  environment); if it is unset, both endpoints return `503` with a clear message rather than a
  generic authentication error.
- **Real Anthropic API failures are caught and translated** (`oah.explain.errors`), not left to
  surface as a raw traceback and a generic `500`: any `anthropic.APIError` (a real one was hit
  live during this block's own development -- an account with an insufficient credit balance)
  is wrapped as `LLMRequestError` with a clean, safe `detail` message extracted from the SDK
  error's own response body, and mapped to `429` when Anthropic itself rate-limited the request
  or `502` for every other upstream failure (bad/rejected request, invalid key, network error).
- **No mocked business logic in production**: unit tests never call the real Anthropic API (a
  fake client double is injected, matching this project's existing pattern for the sandbox
  client and the review store; real `anthropic.APIError` instances are constructed directly, with
  no network call, to test the error-translation path); `scripts/eval_explain.py` is the one
  place that calls the real API, run manually and documented in the ledger, the same pattern
  already used for the official HL7 validator's optional pipeline stage.

**First real run (2026-09-26, `scripts/eval_explain.py`, model `claude-opus-5`, 4 calls, evidence from a
100-hour-old local snapshot because the sandbox host did not resolve).** All four responses passed the grounding
check, and a human read of them found: the numbers in both `describe` outputs matched the evidence; the `assess`
output wrote `6.4x` for a worst excursion of 6.36 (an excursion is a relative excess, so the reading was 7.36 times
the limit) and called a conductivity exceedance "possibly real", because the model was never told that the limits
are proxies (that exceedance is an artefact of a drinking-water-type limit on a brackish coastal stream); the
`assess` output for the review item stated that the candidate families span different pollution-tolerance profiles,
a claim that is not in the evidence. The first two are the documented blind spot of a number check (a right number on
the wrong claim), now observed in a real output. Changes made: each veto entry carries `worst_value`, `limit`, `unit`
and `times_limit`; the indices evidence and `/indices/{id}` carry `objective_limits_source`; the WQI prompt has a
glossary that defines excursion and says exceedances of proxy limits are flags, never proof; `Explanation` records
token usage. **Second real run, after those changes (same day, 4 calls, 2,906 tokens in and 2,214 out, an upper-bound cost
of about 0.21 USD if the price were 15 / 75 USD per million tokens; the real price was not checked).** The
misreadings disappeared in the WQI outputs: both wrote the correct factor (7.36 / about 7.4 times), gave the value,
unit and limit (18,400 uS/cm against 2,500 uS/cm), said the limits are proxies and that the exceedance is a flag to
investigate, and the `assess` concern level fell from high to moderate with a note that a saline baseline may make the
limit inappropriate. The number check then flagged 2 of the 4 outputs for harmless enumerators ("Two points for your
decision", "those two families"), a 50 percent false-alarm rate on this tiny real sample. Only the first kind is now
exempt (2-10 directly before points, things, reasons, steps, options, caveats, notes or questions); a count of data
items ("those two families") is still flagged on purpose. Four outputs from one model support no general claim.

Remaining known gaps, stated rather than silently assumed away: the shared `OAH_API_KEY` is a
single secret, not per-user identity or scoped permissions; the rate limiter is single-process
and does not coordinate across multiple uvicorn workers or machines (a real distributed limiter
needs a shared store such as Redis, out of scope here); and none of this replaces TLS, which
must be terminated by whatever reverse proxy fronts this API in any non-local deployment. This
is a hardened local/demo API, not a production-grade public deployment.

## Origin labelling fails closed (added 2026-09-26)

`oah.ingest.sources.source_records` and `origin_from_resource` no longer label an untagged resource as `real-sandbox` by default. A `synthetic` tag always wins; an untagged dictionary is accepted only when the caller declares `default_origin` (the sandbox-facing callers, `/qc/report`, `/fhir/export`, the QC CLI and the pipeline scripts, declare `real-sandbox`). An empty QC batch needs a declared origin. `_tag` in `oah.fhir.output.builders` is idempotent and refuses to mark a synthetic resource `real-derived`. Tests: `tests/unit/test_sources.py`, `tests/unit/test_fhir_export.py`.

## Authentication fails closed (added 2026-09-26)

Protected routes now require `X-API-Key` matching `OAH_API_KEY`. When the key is unset the API answers 503 instead of opening itself; local demos opt out explicitly with `OAH_INSECURE_NO_AUTH=1`, which must never be set on a reachable host. Since the first version the rate limiter ran before the key check so that wrong-key guesses were limited; that let an unauthenticated flood use up the shared bucket, so (F2) the key is now checked FIRST and wrong keys are limited by their own failed-attempt limiter (see "API layer" above). The key comparison encodes both sides to bytes, so a non-ASCII header is a 401, not a 500. `Settings` no longer prints the API key or the Anthropic key in its `repr`. `OAH_CORS_ORIGINS` rejects a wildcard, and CORS allows only the `X-API-Key` and `Content-Type` headers. Tests: `tests/unit/test_auth_fail_closed.py`; `tests/conftest.py` isolates every test from a developer's local dotenv file and sets the opt-in flag by default.

## UI authentication is undecided, deliberately left for later (added 2026-09-27)

`frontend/src/api.ts` sends no `X-API-Key`: a shared secret compiled or configured into a browser
bundle is visible to anyone who opens the network tab, so it is not a secret once it reaches the
client. The frontend can therefore only call the protected routes today against a backend started
with `OAH_INSECURE_NO_AUTH=1` (local/demo only, never a reachable host -- see "Authentication fails
closed" above).

Two production-shaped options were identified and neither is built:
- **Same-origin proxy / backend-for-frontend**: a small server the browser talks to injects
  `X-API-Key` server-side; the browser never holds it. Keeps today's shared-key model at the API
  layer; closes the browser-exposure gap without adding per-user identity.
- **Per-user sessions**: real login, an httpOnly session cookie, and the API validating a session
  instead of a shared key. Gives `reviewer_id` (see "LLM audit trail..." below) a real identity
  instead of a self-reported pseudonymous handle, at the cost of building login, user management
  and revocation.

The user explicitly chose, when asked, to defer this decision rather than pick either option now:
the frontend phase proceeds in local-demo mode (`OAH_INSECURE_NO_AUTH=1`) with this documented as a
known limitation, not a silently-assumed one. Revisit before any deployment reachable by someone
other than the operator running it locally.

## LLM audit trail, health-claim guard and reviewer handle (added 2026-09-26)

- Every request to the LLM provider is recorded in an append-only JSONL file under the external data directory (`oah.paths.llm_audit_path`, `oah.explain.audit`): a `dispatch` line before anything is sent, then a `result` or `error` line, plus a `cache-hit` line when the cache answers. Lines hold the kind, mode, model, a SHA-256 of the evidence, sanitisation notes, token counts, grounding result and safety flags, never the evidence, the model text or a client address. If the dispatch cannot be recorded, the call is not sent (the API answers 503).
- `guard_output` adds the flag `unsupported-health-claim` for potability, drinkability, safety, contamination, diagnosis or health-risk statements (English, Spanish, Italian patterns); both system prompts now forbid such determinations. Every `/explain/*` response carries `unsafe` (true when a rendering-safety or health-claim flag is present), a `status` and a fixed `disclaimer`; since the security hardening of 2026-10-03 (F6) an unsafe or not grounded text is NOT returned (`explanation` null, `status` `withheld` or `withheld-ungrounded`, the evidence and flags stay).
- `reviewer_id` is a pseudonymous handle (`[A-Za-z0-9._-]`, up to 64 characters). E-mail addresses and names are rejected because the audit table is append-only and cannot honour an erasure request.
- Not wired: `oah.privacy` (k-anonymity, coordinate generalisation, consent). No route exposes person-level data, and monitoring-site coordinates are institutional points, so nothing calls it yet; it must be wired before any endpoint returns observer-level data.
Tests: `tests/unit/test_llm_audit.py`, `tests/unit/test_explain_safety.py`, `tests/unit/test_api_abuse.py`.

## Data freshness (added 2026-09-26)

`/qc/report`, `/sites`, `/indices/{id}` and `/explain/indices/{id}` carry `data_freshness` (`status` one of `live`, `snapshot`, `snapshot-stale`, `unknown`; `as_of`; `age_seconds`). `oah.indices.apply_to_sandbox.load_sandbox_resources_with_freshness` reports where each batch came from; the API records it per resource type and returns the least trustworthy status with the oldest `as_of`. A stale snapshot is therefore never presented as live data, and neither is a cached copy past the cache TTL ("Sandbox cache"). The explanation evidence includes the status and `as_of` but not the age, so the cache key stays stable. Tests: `tests/unit/test_api_fallback.py`. Time handling follows `docs/time_policy.md`.

## Sandbox cache (stale-while-revalidate, added 2026-10-04)

Problem: a full sandbox fetch (Observations plus Locations, paged GET requests) takes about 12 s. With a plain TTL cache every
visitor arriving after expiry, or right after an instance start, waited for it. `oah.api.swr_cache.RevalidatingCache` (one per
resource type, wired in `oah.api.services`) removes that wait without hiding the age of the data.

| Age of the held copy | Behaviour |
| --- | --- |
| below the TTL (`OAH_SANDBOX_CACHE_TTL_SECONDS`, default 300) | served as is, `data_freshness` as recorded (`live`) |
| TTL up to the maximum staleness (`OAH_SANDBOX_MAX_STALE_SECONDS`, default 21600 = 6 h) | served AT ONCE; the request may start one background refresh; `data_freshness.status` is lowered to `snapshot` (`snapshot-stale` above 24 h), never `live` |
| above the maximum staleness, or no copy at all | the request waits for a fetch (concurrent requests share one fetch); if the sandbox is unreachable the existing fallback applies (an older file snapshot labelled `snapshot-stale`, else a 503) |

- Refresh trigger is REQUEST-DRIVEN. No timer is used. The first request after expiry returns the stale copy and starts a daemon
  thread (`oah-sandbox-refresh`); a single-flight token allows one refresh per cache at a time. A refresh that raises keeps the
  stale copy and backs off exponentially (30 s, 60 s, ... capped at 600 s) so a down sandbox is not hammered; a refresh running
  longer than 120 s is abandoned (a late result is discarded) and counts as a failure. A background refresh only replaces the
  copy with LIVE data: if the live sandbox is unreachable it does not swap in an older file snapshot.
- Start-up: the FastAPI lifespan (`oah.api.app`) starts one warm-up thread per cache and returns at once, so start-up and the
  container health check are not delayed; a failed warm-up is logged and the first request fetches as before.
  `OAH_SANDBOX_WARMUP=0` switches it off (offline development).
- LIMITATION (Cloud Run with CPU throttling, as deployed): CPU is available only while a request is being processed, plus the
  start-up boost. The warm-up normally finishes inside that boost. A refresh started by a request may be frozen when the
  response is sent and only finish during the next request. Consequence: after an idle period the first visitor sees a copy
  as old as the idle time (bounded by the maximum staleness, labelled `snapshot` with its `as_of` and `age_seconds`), and the
  copy becomes current only after the following requests give the thread CPU. This is stale data told honestly, not live data.
  The visitor who finds a copy older than the maximum staleness still waits once. Nothing guarantees the sandbox data changed
  or did not change in between.
- Freshness label: `get_data_freshness` combines the per-type records as before and lowers a type's status when its cache is
  past the TTL (`snapshot`: a held copy younger than 24 h, the meaning that word has for a file snapshot; `snapshot-stale` older).
  The status is computed when the response is built, so a refresh that completes between the data read and the label can
  label a response as live although it was built from the previous copy for a few milliseconds; the age fields are then
  those of the new copy. This race is accepted and not guarded.
- No field or schema changed (`docs/openapi.json` is untouched). `oah.api.cache.TTLCache` is no longer used by the API (kept,
  with its tests, as a plain blocking TTL cache).
- Tests: `tests/unit/test_swr_cache.py` (fake clock and thread starter, real-thread single flight, back-off, maximum
  staleness, timeout, warm-up), `tests/unit/test_sandbox_cache_service.py` (freshness labels in each state, live-only
  refresh, warm-up, lifespan), `tests/unit/test_sandbox_cache_config.py` (settings, empty value, validation).

## Typed API contract (added 2026-09-26)

Every protected route declares a response model in the `src/oah/api/schemas/` package (`SitesResponse`, `QcReportResponse`, `IndexResponse`, `ExplanationResponse`, `FindingsExportResponse`, `IndicatorsExportResponse`, `ReliabilityCampaignResponse`, `ReviewQueueResponse`, `ReviewDecisionResponse`, `RiskResponse`) and, through the router, the shared error responses 401, 429 and 503 (404 per route where it applies). `origin` is a closed set (`real-sandbox` or `synthetic`) and `data_freshness.status` is one of `live`, `snapshot`, `snapshot-stale`, `unknown`. Shapes that carry evolving nested detail (the QC report, a per-location index, the explanation evidence) type their stable core and allow extra keys. A client can generate its types from `/openapi.json`. Tests: `tests/contract/test_openapi_contract.py` fails if a protected route is added without a model or without the shared errors.

## Review integrity and API hardening (added 2026-09-29, independent re-audit)

- **Review decisions are atomic and tamper-evident.** A decision and its audit event are written in one SQLite transaction (`ReviewStore.commit_with_audit`): both persist or neither does. Audit events are hash-chained (`prev_hash`, `event_hash`); `ReviewStore.verify_audit_chain()` recomputes the chain and finds an edited, reordered or removed event that is followed by a later one. It cannot detect removal of the most recent events (no external anchor) and skips events written before the chain existed. Event ids are random (`uuid4`).
- **No silent overwrite.** A decided item cannot be resubmitted (that would reset it); a second decision needs the explicit `allow_override` and is recorded as `OVERRIDE_DECISION` with both states. The API answers 409 for a decided item and 422 when `final_label` is neither one of the item's predicted labels nor `other`.
- **Reviewer identity remains self-asserted** (the shared API key is not per-user identity); the audit `actor` is the handle the caller sends. Per-user authentication belongs to the deferred UI authentication decision above.
- **Errors do not leak.** Upstream language-model errors are logged on the server and the caller receives a fixed generic detail (429 or 502); the sandbox 503 no longer carries URL or transport text.
- **Sandbox client bounds.** At most 200 pages, 100,000 resources and 25 MiB per response; a repeated next link stops the loop; entries without a resource are skipped and a non-object body is rejected. `OAH_SANDBOX_URL` must be https (http only for localhost), name a host and carry no credentials.
- **Thread safety.** The rate limiter, the explanation spend guard (check-and-append of the daily cap) and the sandbox cache are lock-protected; a cache miss triggers one fetch and an expired entry one background refresh (single flight, "Sandbox cache"). Idle rate-limit keys are evicted. The daily cap is still per process and global.
- **Docs and schema routes are off by default** (`/docs`, `/redoc`, `/openapi.json`); set `OAH_ENABLE_DOCS=1` for local development. `app.openapi()` remains available in process.
- **Exports are written atomically** (temporary file, then rename).
- The items first left open by that audit are now implemented (see the next section).

## Proxy-aware limits, HSTS, audit-log chain, dependency lock and limit signatures (added 2026-09-29)

- **Client address behind a proxy** (`oah.api.client_ip`): the rate limits and the explanation budget are keyed by the client address. `X-Forwarded-For` is believed only when the immediate peer is listed in `OAH_TRUSTED_PROXIES`; the chain is read from the right and the first address that is not itself a trusted proxy is the client (entries to its left are client-supplied). A malformed chain falls back to the peer. From any other peer the header is ignored. Optional since F3: `OAH_TRUSTED_PROXY_HOPS` (default 0 = off) takes the entry that many places from the right of the chain, for a platform whose proxy addresses are not known (Cloud Run); and `X-OAH-End-User` (an opaque 16 to 64 character token from the trusted web layer) is an extra part of the chat and explanation per-minute bucket only, a fairness aid and not authentication (`docs/api_routes.md`, `docs/chat_agent.md` section 9).
- **HSTS:** `Strict-Transport-Security: max-age=31536000` is sent when the request is https, directly or through a trusted proxy that sets `X-Forwarded-Proto: https`; never on plain http.
- **LLM audit log** (`oah.explain.audit`): each record stores `prev_hash` and its own `hash` (SHA-256 over the previous hash and the record). `verify_chain(path)` and `verify_all()` recompute it and find an edited, reordered or removed record followed by a later one. The log rotates at 5 MiB (`llm_calls.<UTC>.jsonl`) and the first record of the new file carries the last hash of the rotated one, so the chain continues. Removal of the newest records cannot be detected without an external anchor. Lines written before the chain existed are skipped. Security hardening F9: (1) records hold digests, counts and flags ONLY, never user text (the 80-character question excerpt of `chat-dispatch` was removed, and `chat-tool-result` stores `error_sha256`, not the message); (2) each record is also written as one structured JSON line on stdout (`{"severity": "INFO", "message": "oah-llm-audit", "audit": {...}}`) so a log collector (Cloud Logging) keeps it when the in-memory file system is lost on a restart; the stdout copy is the durable one and is not chained; (3) at most `MAX_ROTATED_FILES` (4) rotated files are kept, the oldest deleted first when a rotation happens; `verify_all` then verifies what remains, starting the first remaining file from the hash its first record names as its predecessor, so an edit or removal inside what remains is still found, and a deliberate deletion of the oldest files cannot be told apart from pruning (the limit of a chain without an external anchor).
- **Chat and explanation answers.** A not grounded or unsafe answer is withheld (`withheld-ungrounded`, `withheld`) and never returned as text; the model client makes no SDK retries (`max_retries=0`), and a missing model key is a fixed 503 text (F6, F12, F15; `docs/chat_agent.md`).
- **Dependency lock:** `requirements-lock.txt` is a hash-pinned resolution of `pyproject.toml` with the `dev` extra (`pip-compile --generate-hashes`), so transitive dependencies no longer float. Install with `pip install --require-hashes -r requirements-lock.txt`. Regenerate it when `pyproject.toml` changes and audit it with `pip-audit -r requirements-lock.txt --disable-pip --no-deps` (clean on 2026-09-29 after raising `pytest` to 9.0.3; the CI audit job blocks on a new advisory).
- **Limit verification** (`oah.indices.limit_verification`, procedure in `docs/limits_verification.md`): every numeric limit the index can apply has a key and appears with its verification state (`[unverified]`, `[verified by <handle> on <date>]` or `[verification stale ...]`) in each site's `limit_basis`. No limit is signed yet.
- **Default model** is now `claude-sonnet-5-5` (was `claude-opus-5`); `OAH_LLM_MODEL` still overrides it. The identifier comes from the model list in this session's environment and was not exercised against the API by the tests.

## Changing limits without editing code (added 2026-09-29)

`oah.indices.limit_overrides` loads an optional JSON file named by `OAH_LIMITS_FILE` and applies it on top of the
shipped tables (drinking-water limits, surface limits, national country limits, ranges and dated limits, location
countries and regimes). Validation is strict (units must match the parameter's unit, values finite and positive,
sources required); a half-valid file changes nothing; the file is re-read when it changes; every output labels the
change (`limit_basis` reads `override: <source>`, the result carries `limit_overrides`), and an overridden limit never
reads as verified. The pipeline calls it before using the tables and the API calls it at startup in strict mode, so
a wrong file stops the server with a clear message. Rationale: the project is a hackathon deliverable whose shipped
values are reference values, so changing them must be easy and visible rather than a code change.
