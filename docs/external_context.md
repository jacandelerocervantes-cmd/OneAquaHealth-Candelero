# External context (weather, river discharge, species records)

Status: 2026-10-03, backend package 7. Demo version. Everything here is English; the fixed notices are data
(`src/oah/i18n/strings/`). The feature is OPTIONAL: with `OAH_EXTERNAL_ENABLED=0` (or any provider switched off) the rest of
the API behaves exactly as before.

## 1. What it is, and what it is not

Around a site (a Waterbase site, a sandbox site, or, for weather only, a bathing water) the backend can fetch context from
two public providers, **from the server only**, behind a cache and a process-wide budget:

| Context | Provider | What the numbers ARE | `origin` | `data_kind` |
|---|---|---|---|---|
| Weather: monthly precipitation and mean temperature | Open-Meteo Historical Weather API (ERA5) | MODELLED reanalysis for a grid cell of 0.25 degrees (about 25 km), not a measurement at the site | `external-open-meteo` | `modelled-reanalysis` |
| River discharge: monthly mean | Open-Meteo Flood API (GloFAS v4 consolidated) | MODELLED discharge of the nearest river cell of a 0.05 degree grid (about 5 km), not a gauge reading | `external-open-meteo` | `modelled-river-discharge` |
| Species records near the site | GBIF occurrence search | OPPORTUNISTIC records, many from citizen-science platforms; not monitoring, not an inventory | `external-gbif` | `opportunistic-occurrence-records` |

Never to be said or implied: that these are the site's own measurements, that they are monitoring, that rainfall, flow or a
species "caused" or "explains" a water-quality value (the strongest allowed statement is "rainfall may be relevant", and only
when both series were returned), or that the absence of a species record means the species is absent. The values are never merged
with the EEA or sandbox data and never enter an index, a limit comparison or a period comparison. Coordinates come only from the
stores' sites; no route or tool accepts a raw latitude or longitude.

## 2. Design

```
route or chat tool (site id, period) -> SiteLocator (store coordinates, 404 / 422)
   -> provider function (validates the period, rounds the point) -> runtime.cached(key) --hit--> parsed result
        miss -> runtime.call: switch? -> breaker? -> budget (every attempt) -> hardened GET (allow-list, https, JSON, size cap)
              -> parse and validate -> aggregate to months -> cache the small parsed result
   any failure -> status "external-unavailable" + reason (HTTP 200 on the REST routes; never a 500, never a block)
```

Modules (`src/oah/external/`): `settings` (variables and ceilings), `constants` (hosts, labels, attribution, documented limits),
`http` (the GET client), `guard` (TTL+LRU cache, rolling budget, circuit breaker), `runtime` (the one network path and the
process-wide state), `coords` (validation, rounding, GBIF square, haversine), `sites` (site locator), `openmeteo`, `gbif`, `taxa`
(+ `data/gbif_taxa.json`), `envelope` (the common response frame), `service` (what routes and tools call).

A provider failure, timeout, malformed answer, exhausted budget or switched-off provider gives
`status: "external-unavailable"` with a `reason` (`disabled`, `budget-exhausted`, `cooling-down`, `timeout`, `rate-limited`,
`network-error`, `http-error`, `bad-response`, `response-too-large`, `redirect-refused`, `blocked-target`); `no-data` means the
provider answered but holds nothing for the period. A failure is never cached. The REST routes answer HTTP 200 for both so that a
client shows a card state instead of an error (decision: the context is optional and must never look like a core failure);
404 is an unknown site, 422 an invalid site, period, group or limit.

## 3. Providers: facts read on 2026-10-03

All from the providers' own pages, fetched with a plain GET on that date (a summarising tool was used earlier; these were read
again directly, and where a statement could not be read it is marked UNVERIFIED).

**Open-Meteo** (`https://open-meteo.com/en/terms`, `/en/licence`, `/en/pricing`, `/en/docs/historical-weather-api`,
`/en/docs/flood-api`):

* Licence: API data under CC BY 4.0; the free API is for NON-COMMERCIAL use ("Operating websites or apps that have subscriptions
  or display advertisements" and "Integrating our service into commercial products" are listed as commercial). Free tier: fewer
  than 10,000 calls per day, 5,000 per hour, 600 per minute (the pricing table also lists 300,000 per month). Open-Meteo reserves
  the right to block misuse.
* Attribution (licence page): give credit, link to the licence, indicate changes; "You must include a link next to any location
  Open-Meteo data are displayed", with the example link text `Weather data by Open-Meteo.com` pointing to `https://open-meteo.com/`.
  The responses carry this text in `attribution` and the URL in `attribution_url`; a UI must show it next to the data.
* Calls are counted by size: "Requests for data covering more than 10 weather variables or extending over a period of more than
  2 weeks for a single location are considered multiple API calls" (examples: 2 weeks with 15 variables = 1.5 calls, 4 weeks =
  3.0). The budget here charges `max(1, days / 14) * max(1, variables / 10)` units per request (section 5); the exact rule is
  UNVERIFIED.
* Historical Weather API: host `archive-api.open-meteo.com`, endpoint `/v1/archive`, parameters `latitude`, `longitude`,
  `start_date`, `end_date`, `daily`, `timezone`, `models`. ERA5: global, 0.25 degrees, 1940 to present, "daily with 5 days delay".
  The daily variables used are `precipitation_sum` (mm) and `temperature_2m_mean` (degrees C). The request names `models=era5`
  (observed to work; without it the "best match" mixes several models) and `timezone=GMT` (a day is a UTC day). Observed on
  2026-10-03: a request ending today returns `null` for the last days; a `start_date` before 1940-01-01 or an end date after today
  is a 400 ("allowed range from 1940-01-01 to <today>").
* Credit text of the historical page: "Generated using Copernicus Climate Change Service information 2022" and the ERA5 citation
  (Hersbach et al., 2023, DOI 10.24381/cds.adbb2d47). The responses name the ERA5 credit; whether this satisfies the C3S licence
  is not asserted.
* Flood API: host `flood-api.open-meteo.com`, endpoint `/v1/flood`, parameters `latitude`, `longitude`, `start_date`, `end_date`,
  `daily=river_discharge` (m3/s), `models`. GloFAS v4 reanalysis at 0.05 degrees "1984 - July 2022". "Due to the 5 km resolution
  the closest river might not be selected correctly. Varying coordinates by 0.1 degrees can help" (the project does NOT nudge the
  point; it reports the cell used and its distance, and flags the caveat).
* GloFAS credit: the Open-Meteo licence page lists GloFAS with its own licence (a Copernicus Emergency Management Service licence
  PDF), but the PDF link returned 404 on 2026-10-03, so the exact credit wording is **UNVERIFIED**. The text shown
  (`River discharge: GloFAS (Copernicus Emergency Management Service), provided through Open-Meteo.com`) is the project's own
  neutral naming, and `attribution_verified` is `false` for it. **Check the CEMS wording before any public use.**
* Observation that differs from the page: the `consolidated_v4` model returned values for dates after July 2022 (for example
  2024) and `null` from about mid 2025 for one test cell. The page's "July 2022" is therefore NOT used as a cut-off: the real end of
  the data is read from the nulls of each answer (`data_range`), months after July 2022 are flagged `beyond-documented-history`,
  and a month with no value is flagged `period-outside-data`.
* Server versus browser use is not stated by the provider; the backend calls it, never the browser.

**GBIF** (`https://api.gbif.org/v1`):

* `GET /v1/occurrence/search` needs no key for reads (observed), accepts a WKT `geometry` (counter-clockwise polygon),
  repeated `taxonKey`, `occurrenceStatus`, `hasCoordinate`, `hasGeospatialIssue`, `eventDate` (a range `from,to`; `*` for an open
  end, observed to work), `limit`, `offset`, and `facet` (the answer has `count`, `results`, `facets`). A search of 200 records is
  about 1 MB; the response cap here is 4 MiB.
* Licences: the licence of each record is passed on (observed values are URLs such as `http://creativecommons.org/licenses/by-nc/4.0/legalcode`);
  CC0 1.0, CC BY 4.0 and CC BY-NC 4.0 get a short label, anything else is shown as `other-or-unspecified` with the raw text. A
  `CC-BY-NC-4.0` record is marked `non_commercial_only`. The record carries `dataset_key`, `publishing_organization_key`,
  `institution_code` and, resolved by one `GET /v1/dataset/{key}` per distinct dataset (at most 5 per response,
  cached for a day), the dataset title and `citation` text as GBIF provides it: the attribution a licence needs is the dataset title, the
  publisher (`publishing_organization_key`, `institution_code`), the licence and the citation. The names of individuals are deliberately
  NOT passed on: `recordedBy` and, since 2026-10-03, `rightsHolder` (which can be a person's name or a username; the schema field
  `rights_holder` stays for compatibility and is always null). The `record_url` is kept only when GBIF's `references` field is an https URL on
  `gbif.org` (or a subdomain; no credentials, no unusual port); any other link, for example a page on a third-party platform, is dropped
  (`record_url` null), because the field is written by the publisher.
* A User-Agent that names the project and, when `OAH_CONTACT_URL` is set, a contact URL is sent with every request. A 429
  opens a cool-down for `Retry-After` (default 60 s, at most 600 s) and is never retried. GBIF's terms pages and numeric limits
  were NOT read in full: the courtesy limits of this project (30 per minute, 1,500 per day by default) are its own (UNVERIFIED
  against GBIF terms).

## 4. Settings

All optional, none secret. Names for the example environment file (the maintainer adds them; this package did not edit it):

| Variable | Default | Meaning |
|---|---|---|
| `OAH_EXTERNAL_ENABLED` | `1` | master switch; `0` disables every provider |
| `OAH_EXTERNAL_OPEN_METEO_ENABLED` | `1` | weather (archive host) |
| `OAH_EXTERNAL_GLOFAS_ENABLED` | `1` | river discharge (flood host) |
| `OAH_EXTERNAL_GBIF_ENABLED` | `1` | species records |
| `OAH_CONTACT_URL` | unset | an https URL for the User-Agent (no credentials, query or fragment); unset sends `OneAquaHealth/0.1 (research prototype)` |
| `OAH_EXTERNAL_TIMEOUT_SECONDS` | `8` (ceiling 20) | per request |
| `OAH_EXTERNAL_CACHE_TTL_SECONDS` | `3600` (ceiling 7 days) | parsed results; dataset citations use a fixed day |
| `OAH_EXTERNAL_CACHE_SIZE` | `256` (ceiling 2048) | entries (LRU) |
| `OAH_EXTERNAL_OPEN_METEO_PER_MINUTE` / `_DAILY` | `200` / `3000` (ceilings 400 / 8000) | estimated call units, shared by weather and discharge |
| `OAH_EXTERNAL_GBIF_PER_MINUTE` / `_DAILY` | `30` / `1500` (ceilings 120 / 10000) | requests |

The defaults stay well below the published Open-Meteo limits (600 per minute, 10,000 per day); a value above a ceiling is lowered
to it. A three-year weather request costs about 78 units (a one-year request about 26), so at most about 38 uncached three-year
requests fit in the default daily budget; repeated questions are served from the cache.
Booleans accept `1`, `0`, `true`, `false`, `yes`, `no`, `on`, `off`. An invalid value stops start-up with the variable named.

**How to disable:** set `OAH_EXTERNAL_ENABLED=0` (all providers) or one `OAH_EXTERNAL_*_ENABLED=0`. Routes then answer with
`external-unavailable` / `disabled`, the tools say so, nothing is sent, and no other feature changes.

## 5. Formulas, rounding and other derived transformations

* **Coordinate rounding.** `round(value, 2)` degrees (about 1.1 km), before sending and as the cache key. It is coarser than
  every grid in use and finer than a town; the site block of a response states the precision (`coordinate_decimals`).
* **Weather months.** For each calendar month touched by the (clipped) period: `precipitation_sum_mm` = the sum of the daily
  `precipitation_sum` over the days that have a value; `temperature_mean_c` = the mean of the daily `temperature_2m_mean` over
  those days; `n_days` = the days with a value; `days_in_window` = the days of the month inside the requested period;
  `coverage` = `n_days / days_in_window` (3 decimals). Sums and means are rounded to 2 decimals. A day with no value is NEVER
  filled; the month is flagged `partial-month`, and a month with no value `period-outside-data`. Daily values outside physical
  sanity bounds (precipitation 0 to 2000 mm, temperature -90 to 60 degrees C, discharge 0 to 1,000,000 m3/s: the order of the world
  records, there only to reject a corrupt number, not quality thresholds) are ignored and flagged `implausible-values-ignored`.
* **Discharge months.** `river_discharge_mean_m3s` = the mean of the daily values with a value, with `n_days`, `days_in_window`, `coverage`.
* **ERA5 delay.** The provider says ERA5 is about 5 days behind. A period ending later than today minus 5 days (UTC) is flagged
  `era5-delay`; the real missing days are the nulls. A period ending after today is clipped to today (`period-end-clipped`), one
  starting before 1940-01-01 (weather) or 1984-01-01 (discharge, from the API's own message) is clipped (`period-start-clipped`);
  a period wholly outside is `no-data` with `period-outside-data` and nothing is requested. What was asked is always reported as asked.
* **Request units** (budget only): `max(1, days / 14) * max(1, variables / 10)` (section 3; UNVERIFIED rule).
* **GBIF square.** A square of half side 5 km around the rounded point: `dlat = 5 / 111.32` degrees, `dlon = dlat / cos(lat)`,
  written as a counter-clockwise WKT polygon with 4-decimal vertices. It is a square (10 km by 10 km), not a circle. Sites beyond
  80 degrees of latitude or whose square crosses the antimeridian are refused.
* **Haversine distance** (grid cell to the site, record to the centre): sphere of radius 6371.0088 km.
* **Counts per group** are GBIF's own facet counts (`ORDER_KEY` for an order group, `FAMILY_KEY` for a family group) over the same
  filtered search; nothing is counted here. `total_records` is GBIF's `count`; `returned` is at most the `limit` (default 50,
  maximum 200), and the flag `truncated` says records were left out (GBIF returns them in its own order, not newest first).

## 6. Threat model

| Threat | Control | Residual |
|---|---|---|
| A caller makes the server fetch an arbitrary URL (SSRF) | no route or tool takes a URL, host, path or coordinate; hosts are constants checked against a three-host allow-list; the path matches `^/v1/[A-Za-z0-9._/-]{1,120}$`; parameters are rendered by the code; a site id must match `^[\w.\-]{1,128}$` and resolve in a store | none known |
| Redirect to another host, plain http, credentials in a URL, another port | automatic redirects are off; a redirect is followed only to the SAME https host on port 443 (at most 2); anything else is `redirect-refused` | none known |
| Oversized, non-JSON or malformed answer | `Content-Type` must be JSON, the declared and the streamed size are capped (1 MiB, search 4 MiB, dataset 2 MiB), the body must be a JSON object, every field is type- and range-checked, only whitelisted fields are copied, text is stripped of control and markup characters and cut | a provider can still send plausible wrong numbers: they are labelled modelled or opportunistic, never treated as measurements |
| Prompt injection through a record (a dataset name, a scientific name) | whitelisted fields, cleaned and cut; in the chat the sanitiser removes instruction-like text and URLs; the tool results are untrusted data like every result | pattern lists miss novel wording |
| Provider outage, slowness, rate limit | timeouts (8 s), bounded retries (2) only for timeout, network error or 5xx, a 429 is never retried and opens a cool-down, three consecutive failures open a 30 s breaker; every failure is a graceful `external-unavailable` | in-process state: one instance, a restart resets it (see the note below the table) |
| Cost or ban from over-use | process-wide rolling budget (per minute and per day) charged for every attempt, a cache of parsed results (TTL and size bounded), the route and chat rate limits in front | counters do not coordinate across workers; an operator running several instances must lower the budget per instance |
| Personal data | the observer name and the rights holder (can be a person's name or username) are not passed on, and a record link is kept only on `gbif.org` over https; the contact URL is sent only as the operator chose; no user text, token or key is ever sent to a provider; logs hold the host and a reason code, never a URL or coordinate | the dataset title, publisher and citation text can still name an organisation or a project; a dataset's own citation may name people, as GBIF publishes it |
| Misreading of modelled or opportunistic data | `origin`, `data_kind`, fixed notices in 26 languages, flags, the no-causation rule in the chat prompt | a user can still over-read a chart; the label is the control |
| Licence breach | attribution and per-record licence shown; `non_commercial_only` marked; the project is a non-commercial demo | public or commercial use must re-check the Open-Meteo and GloFAS terms and the GBIF licence of each record |

**Caps and caches are in memory and reset on every restart** (2026-10-03, security note F10). The cache, the per-minute and per-day budgets, the
cool-down and the circuit breaker live in the process. A crash, a deploy, a scale-to-zero or a failed health probe starts a new process with full
budgets and an empty cache, and several instances each hold their own counters. So these controls limit bursts and repeated questions, they do not
promise a daily ceiling: **the providers' own budgets (Open-Meteo's 10,000 calls a day and 600 a minute, GBIF's own limits and its right to block)
are the real ceiling**, which is why the defaults stay well below them and an operator with several instances must lower the budget per instance.

## 7. Taxon keys (`src/oah/external/data/gbif_taxa.json`)

The GBIF taxon keys were DISCOVERED on 2026-10-03 with one read-only GET per name,
`https://api.gbif.org/v1/species/match?name=<name>&rank=<rank>&kingdom=Animalia`, and kept only when `matchType` was `EXACT`, `status`
`ACCEPTED` and the rank the expected one. The file records the key, the rank, the match type and the confidence of each, the
date, the method, a one-line justification and a caveat. The list is small and explicit and is the project's own selection, not an official
list:

| Group id | Name | Rank | GBIF key | Confidence |
|---|---|---|---|---|
| `ephemeroptera` | Ephemeroptera (mayflies) | ORDER | 1225 | 98 |
| `plecoptera` | Plecoptera (stoneflies) | ORDER | 787 | 98 |
| `trichoptera` | Trichoptera (caddisflies) | ORDER | 1003 | 98 |
| `odonata` | Odonata (dragonflies, damselflies) | ORDER | 789 | 98 |
| `chironomidae` | Chironomidae (non-biting midges) | FAMILY | 3343 | 98 |
| `gammaridae` | Gammaridae (freshwater shrimps) | FAMILY | 4434 | 98 |
| `unionida` | Unionida (freshwater mussels) | ORDER | 9301143 | 98 |

`ept` is an alias for the first three (the usual EPT bioindicator trio). A plain name-only match was rejected where it was wrong:
`Plecoptera` first matched the class Insecta (`HIGHERRANK`, key 216), `Oligochaeta` is a synonym of a class that includes terrestrial
worms, `Hirudinea` fuzzily matched a bird genus and `Astacidea` a family: all four are listed under `rejected_matches`. To re-run the
discovery, repeat the GET for each name with its rank and `kingdom=Animalia`, compare `usageKey`, `rank`, `status`, `matchType`
and `confidence`, then edit the file and `discovered_on`. The loader (`oah.external.taxa`) refuses a file that breaks the rules.
Presence of a group near a site says nothing about the water quality of the site.

## 8. Notices (fixed strings, 26 languages)

Each response names the localised fixed strings it must show (`oah.external.service.NOTICE_KEYS`) and the route returns their text in
`notices` for the requested `language`: `external_context_notice` (not a measurement of this site, orientation only),
`external_reanalysis_notice` (weather: modelled reanalysis for a coarse grid cell, the most recent days may be missing),
`external_discharge_notice` (modelled for the nearest river cell, may not be this site's river), `external_occurrence_notice`
(opportunistic, a missing record is not an absent species), `external_licence_notice` (each record keeps its own licence, some are
non-commercial only), `external_no_causation_notice` (context only, nothing shows causation) and `external_unavailable_notice` (the
provider could not be used, nothing was estimated). Weather carries context, reanalysis and no-causation; discharge context, discharge and
no-causation; species context, occurrence and licence; any unavailable result adds the unavailable notice. They live in
`src/oah/i18n/strings/*.json` as machine drafts (25 files, new `source_sha256`), like the other fixed strings; none exceeds 200 characters in
English, so the chat sanitiser (which cuts a string at 200) never truncates one. The attribution text itself (`Weather data by Open-Meteo.com`)
is a required link text and is not translated.

## 9. Routes, tools and the real smoke

Routes (`docs/api_routes.md`): `GET /sites/{site_id}/weather`, `/discharge`, `/species` and `GET /external/status`. Chat tools
(`docs/chat_agent.md`): `get_weather_context`, `get_river_discharge_context`, `get_species_nearby`. A bathing water is accepted for weather only.

**Real end-to-end smoke, 2026-10-03** (the real helper against each provider, a handful of GET requests; the tests never do this). Site
`IT01001065`, "PO - CARIGNANO", an Italian river site of the EEA Waterbase store (latitude 44.91, longitude 7.69 after rounding), one month, March 2021:

* Weather (ERA5, requested with `models=era5`): precipitation sum 10.1 mm and mean temperature 10.13 degrees C, 31 of 31 days in both, coverage 1.0,
  no flag. The grid cell used was 45.0, 7.75, 11.1 km from the rounded site point.
* Discharge (GloFAS `consolidated_v4`): mean 0.47 m3/s, 31 of 31 days, `data_range` 2021-03-01 to 2021-03-31, flag `nearest-cell-may-not-be-the-river`; the cell used
  was 44.925, 7.675, 2.0 km from the point. A river of the Po's size would be expected to carry far more than 0.47 m3/s (an expectation, not a verified
  figure): the nearest 5 km cell here is evidently a small stream, not the Po. This is exactly the caveat the provider's page gives, and the reason the response always carries
  the flag and the distance and the chat tool must never present the number as the Po's discharge. The project does not nudge the point (the page suggests varying it by 0.1 degrees).
* Species (GBIF, all groups, event date from 2015-01-01, `limit` 5): 105 records in the 10 km square, by GBIF's own counts 102 Odonata and 3 Unionida (no
  Ephemeroptera, Plecoptera, Trichoptera, Chironomidae or Gammaridae record in that square since 2015); the 5 records returned were all human observations of Odonata,
  3.9 to 5.0 km from the centre, licence CC BY-NC 4.0 (so the flag `non-commercial-licence-records`), dataset "iNaturalist Research-grade Observations" with the
  citation text GBIF gives ("iNaturalist contributors, iNaturalist (2026). iNaturalist Research-grade Observations. iNaturalist.org. Occurrence dataset
  https://doi.org/10.15468/ab3s5x accessed via GBIF.org on 2026-10-03."). Flags `truncated` and `non-commercial-licence-records`.
* The same questions through the FastAPI routes (after the wiring, same day, real stores and providers, `language=it` for the weather notices): weather 10.1 mm and 10.13 degrees C
  with the Italian fixed notices; discharge 0.47 m3/s, 2.0 km from the cell; `group=ept` gave 6 records, all Trichoptera (0 Ephemeroptera, 0 Plecoptera), 3 returned and the flag `truncated`;
  all groups from 2020-01-01 gave 67 records, 3 returned, all CC BY-NC 4.0. The ERA5 delay is visible: a period of 2026-09-20 to 2026-10-03 carries `era5-delay`, September holds 8 days with a value
  (`partial-month`) and October none (`period-outside-data`). The consolidated discharge of that cell ends within May 2025: 2025-05 has 31 days (flagged `beyond-documented-history`) and
  2025-06 to 2025-09 none (`period-outside-data`), against the page's "July 2022".
* Budget after the first calls: 195.57 of 200 weather and discharge units per minute (a 31 day request is charged 2.21 units), 28 of 30 GBIF requests (the search and one
  dataset lookup). A second weather question for the same site and period was answered from the cache.

## 10. Known limits and provisional items

* GloFAS credit wording and the GBIF terms are UNVERIFIED; the Open-Meteo units rule is an estimate.
* ERA5 at 25 km and GloFAS at 5 km describe a cell, not the site; the discharge cell may be another river (the real smoke of section 9 shows it: 0.47 m3/s for a site
  named after the Po). A possible improvement, not done: also query neighbouring cells and report the largest, which costs several calls per question and is a new
  derived transformation to document and approve.
* The model name `consolidated_v4` is read from the Flood API page; the page's history end (July 2022) disagrees with the observed data.
* GBIF records are not sorted by date; a limited search returns GBIF's own order. The square is 10 km by 10 km, a choice of this project, not a documented radius.
* The chat refuses a causal claim with a regular-expression heuristic (`oah.chat.causation`): English only and easy to evade by rewording; the prompt and the grounding check
  are the other controls. It can also withhold an answer that merely hedges ("may have contributed").
* The REST routes answer `external-unavailable` with HTTP 200 (decision, section 2); a client or operator that prefers 503 would need a small change in `oah.api.external.payload`.
* The counters (cache, budget, breaker) are per process; with several instances the budget is per instance.
* No live call is made by the tests; the real smoke is in section 9 and the ledger entry of package 7.
* Needs `code-reviewer` and `qa-test-engineer` before merge.
