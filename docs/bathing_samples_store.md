# EEA bathing-water SAMPLES store (backend package 6)

Date: 2026-10-03. Code: `src/oah/bathing_samples/` (`constants.py`, `client.py`, `build.py`, `store.py`, `service.py`, `change.py`), the API assembly
`src/oah/api/samples.py` with the models in `src/oah/api/samples_schemas.py`, the command line `scripts/build_bathing_samples_store.py`, the chat tools in
`src/oah/chat/tools/`. This is the Microbiology item of the catalogue (`docs/indices_catalog.md`) as **individual measurements**: the E. coli and
intestinal enterococci results of every bathing-water sample of Greece and Italy that the EEA published through its Discodata service. It is a different dataset
from the classification (`docs/bathing_water_store.md`), so it has its own origin, `real-eea-bathing-samples`, and the two are never merged into one figure.

**No threshold, limit or classification rule for these bacteria exists in this project, and none is applied or invented.** A value is a measurement: it is
never called good, bad, safe, unsafe, compliant or over a limit. `limit` is null in spirit and absent in the contract; there is no `crossed_limit` and no significance claim.

## 1. Source, licence, attribution, unit

- Service: EEA Discodata, a public, read-only, key-less SQL endpoint, `https://discodata.eea.europa.eu/sql?query=<T-SQL>&p=<page>&nrOfHits=<n>` (GET).
- Table: `[WISE_BWD].[latest].[timeseries_MonitoringResult]`. The Discodata metadata (`https://discodata.eea.europa.eu/md`, read 2026-10-03) says of it:
  "Bathing water reporting table: Data set with the monitoring results on intestinal Enterococci and Escherichia coli." and marks `[latest]` as a view (`isProxy`) of
  `[WISE_BWD].[v5r1].[timeseries_MonitoringResult]`: the store records that observation as `latest_view_proxy_observed`, because `[latest]` can move to a newer release
  and a rebuild would then read different data (the provenance has the build date).
- Columns read: `UID`, `season`, `bathingWaterIdentifier`, `sampleDate`, `escherichiaColiValue`, `intestinalEnterococciValue`, `escherichiaColiStatus`,
  `intestinalEnterococciStatus`, `sampleStatus`, `metadata_observationStatus`, and whether `remarks` is null (the remark text is not read, see section 4).
- **Unit, verified from the table metadata (not assumed):** the description of both value columns is "Measured concentration of Escherichia coli per sample in "colony
  forming unit" per 100 ml (cfu/100ml)." (and the same for intestinal enterococci). The API says `cfu/100ml` and quotes this as `unit_statement`.
- Licence: EEA CC BY 4.0 per the EEA legal notice; the Discodata pages do not restate a licence, so this is **inferred and to be confirmed** (`SOURCES.yaml`, same wording as the
  classification dataset). Attribution string of every response: `EEA Bathing Water Directive, monitoring results via Discodata (EEA CC BY 4.0)`.
- The country is not a column: it is the first two characters of `bathingWaterIdentifier`. Greece is `EL` there (the project treats `EL` as an alias of `GR` everywhere, so it is
  stored and served as `GR`); Italy is `IT`. `NO` has no row (Norway is not in the Bathing Water Directive data) and the build still asks for it, so each build proves it
  (`rows_by_prefix_extracted` shows `NO: 0`). Only the prefixes `EL`, `IT` and `NO` are asked for (`GR%` was checked once and has no row).

## 2. The service as observed on 2026-10-03 (all read-only GET requests, a descriptive User-Agent)

| Question | Observation |
|---|---|
| Rows in the table | `SELECT COUNT(*)`: 2,847,533 in all (all countries); `EL%` 208,176; `IT%` 546,275; `NO%` 0 (1 to 3 s each) |
| `UID` | an integer, unique in the table (2,847,533 distinct values, minimum 225, maximum 24,900,550): the keyset |
| `OFFSET ... FETCH` | refused: `{"errors": [{"error": "Your query is not allowed execution...", "errorcode": 10002}]}` (HTTP 200 with an `errors` body) |
| System tables (`INFORMATION_SCHEMA`) | refused: `"system tables are not allowed"`, error code 10001 |
| Other refusals | some valid-looking aggregate queries were refused with 10002 (a column alias combined with `ORDER BY` on a grouped query, and one query with `LEFT()` and ordinal `ORDER BY`); the guard's rules are not documented and were not isolated. The build uses only the two query shapes below, both verified live |
| `p` and `nrOfHits` | with `TOP 250` and `nrOfHits=100`, `p=1`, 2, 3 returned 100, 100 and 50 rows in order; a query without `p` returned all `TOP n` rows whatever `nrOfHits` said; **`p` without `nrOfHits` (and `p=0`) is answered with `{"errors": [{"error": "Service currently offline"}]}`**, an error with no error code that is a malformed request and not an outage. The earlier research note of a "default page size 100" was NOT confirmed: no default page size was observed |
| Row cap | none met: `TOP 20,000` (5.1 MB, 2.9 s), `TOP 50,000` (12.7 MB, 5.0 s), `TOP 100,000` (26.0 MB, 4.9 s) and `TOP 300,000` (82.0 MB, 12.1 s) were each answered completely, with or without `nrOfHits` |
| Timeout | none met (the longest reply took 12 s); the client allows 120 s per request |
| Failures | none in 45 requests of the real build (no retry was needed); the retry logic is exercised with a scripted fake service |
| Errors | an HTTP 200 body with `errors` (not an HTTP error status). With an `errorcode` (10002 query refused, 10001 system tables) the client treats it as a refusal and stops; WITHOUT an error code ("Service currently offline") it treats it as transient, retries with backoff and then reports it |

The page size of the build is 20,000 rows (about 5 to 6 MB per reply), a conservative value far below what the service answered. The build always sends `p=1&nrOfHits=<page size>` together with `TOP <page size>`
(the two agree, so the service's paging never cuts a page).

## 3. Extraction (`scripts/build_bathing_samples_store.py`, `oah.bathing_samples.client`, `oah.bathing_samples.build`)

The two query shapes (the full text, with the page size and prefix filled in, is in the store provenance as `query_texts` and `count_query_text`):

```
SELECT TOP <n> UID, season, bathingWaterIdentifier, sampleDate, escherichiaColiValue, intestinalEnterococciValue,
       escherichiaColiStatus, intestinalEnterococciStatus, sampleStatus, metadata_observationStatus,
       CASE WHEN remarks IS NULL THEN 0 ELSE 1 END AS hasRemarks
FROM [WISE_BWD].[latest].[timeseries_MonitoringResult]
WHERE bathingWaterIdentifier LIKE '<EL|IT|NO>%' AND UID > <last UID of the previous page> ORDER BY UID

SELECT COUNT(*) AS n FROM [WISE_BWD].[latest].[timeseries_MonitoringResult] WHERE bathingWaterIdentifier LIKE '<EL|IT|NO>%'
```

- KEYSET, never OFFSET: each page continues after the last `UID` of the previous one; the order is `ORDER BY UID` (a unique key), so the result does not depend on the service.
  A page whose UIDs do not strictly increase above the position asked, or a row without an integer UID, stops the build (`DiscodataError`) instead of duplicating or skipping rows.
- Only an EMPTY page ends a prefix (a short page is not taken as the end, so a silent row cap could not end the data early; `short_pages_before_end` in the provenance counts such pages and was 0).
- The query text is built in code from constants and validated integers only (prefix from a closed set, `UID` a non-negative integer, page size 1 to 50,000); nothing a user types reaches it, and the host is
  fixed (`https`, `discodata.eea.europa.eu`; any other URL is refused before a socket is opened).
- Politeness: at most about two requests per second (`--min-interval`, default 0.5 s, refused below 0.25 s), a descriptive User-Agent (`OneAquaHealth-store-build/0.1 (read-only; EEA Discodata; ...)`), one connection at a time.
- Retries: a transient failure (network error, timeout, HTTP 408, 425, 429, 500, 502, 503, 504, a body that is not JSON or has no `results`) is retried up to 5 attempts with exponential backoff
  (2, 4, 8, 16 s, capped at 60 s, honouring a `Retry-After` up to the cap); an `errors` reply or any other HTTP status is a refusal and stops the build at once.
- Hard limits: at most 400 pages and 3,000,000 rows per prefix, 400 MB per reply.
- Resumable: every page is saved as one file in the work directory (`<data dir>/bathing_samples/work/`, from `oah.paths.bathing_samples_work_dir`, outside the project), written atomically. A rerun resumes
  from the last valid page; a file that is unreadable, of another query text, out of sequence or whose last UID does not match is discarded with the later ones. `--restart` clears them, `--keep-work` keeps them after a
  good build, `--max-pages N` stops after N new pages per prefix (a test and caution aid: the work directory is kept, **no store is written** and the exit code is 3).
- Completeness check: the rows extracted per prefix must equal the service's own `COUNT(*)` for the prefix, or the build stops without writing (exit code 2, work files kept).
- `--dry-run` prints the paths, the bounds and the query texts and makes NO request.
- The write is atomic (a temporary file, then rename) and deterministic: the normalised rows go to a temporary SQLite table in the work directory (flat memory, one page at a time) and are copied in key order, so
  the same data gives the same tables whatever the page size (only the build date differs); a failed write leaves the previous store untouched.

## 4. What is stored: raw samples and the KIND of each value

Nothing is aggregated. One row per sample: `bw_id`, `sample_date` (`YYYY-MM-DD`), `uid` (the EEA record id), `country` (`GR` or `IT`), `season`, for each indicator the value as reported (`ec_value`, `ie_value`), its EEA status as
written (`ec_status`, `ie_status`) and its KIND (`ec_kind`, `ie_kind`), `sample_status`, `obs_status` (`metadata_observationStatus`) and `has_remarks` (0 or 1). **The remark text is not stored**: it is free text (one Italian
remark was seen with markup, and 285 distinct Italian remark texts exist), has no analytic use here and must never reach a chat model; only the fact that a remark exists is kept (143,763 rows).

The EEA says of the status columns: "Information regarding missing values, values below the limit of detection, or exceptionally high values." Statuses observed in the real build (Greece and Italy together), and
what the project does with each. A value is a CONCENTRATION only for the kinds `quantified` and `confirmed-high`; every other kind is counted apart and never enters a statistic.

| EEA status as written | Kind (store letter) | Rows, E. coli / enterococci | Meaning and handling |
|---|---|---|---|
| none (null) | `quantified` (Q) | 641,890 / 630,093 | a measured concentration |
| `confirmedValue` | `confirmed-high` (C) | 28 / 17 | the EEA's "exceptionally high values": a measured concentration, flagged; it IS in the statistics and counted separately (`n_confirmed_high`, flag `confirmed-high-values-included`). E. coli range 500 to 69,100 |
| `limitOfDetectionValue` | `detection-limit` (D) | 110,091 / 121,899 | the number is a LIMIT OF DETECTION, not a concentration; excluded from every statistic and counted (`n_detection_limit`, flag `detection-limit-values-excluded`). The API shows `value` null and the number as `reported_value` |
| `missingValue` | `missing` (M) | 2,442 / 2,442 | the source writes a placeholder 0 (every one of the 2,442 had the value 0); stored as written, never a concentration, and not shown in the API (`reported_value` null) |
| any other text | `unknown-status` (U) | 0 / 0 | kept as written, never used; none in the real build |
| not a non-negative whole number, or a flagged status without a number | `invalid` (I) | 0 / 0 | none in the real build |

Findings about `limitOfDetectionValue` that matter (observed 2026-10-03):

- It is frequent: E. coli in 17.0 % of Greek samples (35,311 of 208,176) and 13.7 % of Italian ones (74,780 of 546,275); enterococci 12.9 % (26,929) and 17.4 % (94,970). A mean or median over the
  quantified values ALONE therefore describes only the samples that reached the detection limit and is not the typical concentration; every statistic is accompanied by the counts for that reason.
- The DIRECTION of the censoring is not in a structured column. The reported numbers range from 1 to 22 in Greece and from 1 to 35,000 in Italy; free-text remarks on such rows read, for example, "EC value replaced with
  minimum limit of detection" (6,863 + 3,037 Italian rows), "IE value replaced with minimum limit of detection" (24,537 Italian rows with that exact text) and "... replaced with maximum limit of detection" (a few). In the real Italian
  data a short-term-pollution sample of 2024 carries E. coli 24,000 and enterococci 28,000 with this status, which can only be an upper limit, while 1 with the same status is a lower one. The project therefore never states
  which side a detection-limit number censors, does not read the remarks, and excludes all of them rather than substituting a value (no half-limit, no zero, no Kaplan-Meier).
- 1,427 samples have the sample status `missingSample`, fewer than the 2,442 rows with the status `missingValue`: the two columns do not coincide and both are kept.

`sampleStatus` (null for a routine sample): `preSeasonSample` 111,021, `shortTermPollutionSample` 2,904, `confirmationSample` 2,849, `replacementSample` 2,838, `missingSample` 1,427 (Greece 27,252, 69, 69, 55, 127; Italy 83,769,
2,835, 2,780, 2,783, 1,300). The EEA describes the column as "Information regarding missing samples, samples collected outside the bathing season, samples collected during short-term pollution events, etc." Every sample is
kept and shown with its status; no sample status is filtered out, and the statistics cover all of them (a short-term-pollution sample is a real measurement taken during an incident, not a routine one: a reader who wants
routine samples only must filter on `sample_status`, which the route does not do for them).

`metadata_observationStatus` (`obs_status`) is stored and served as written (`A` 752,960; `O` 1,403; `U` 57; `I` 31) and **not interpreted**: the EEA describes it only as the "status of the record regarding its reliability" and
does not explain the letters in the metadata the build read, so no row is dropped or weighted by it. `metadata_endLifeSpanVersion` and `metadata_replacedBy` are null for every Greek and Italian row (no retired record exists);
`metadata_replaces` is set for most rows and is not read.

Other counted oddities: 187 Italian samples are dated 1 January (`sample_date_is_january_1`; the Italian dates otherwise run from March to October, so these look like placeholder dates; they are kept as reported and counted, and
a period that ends before 2010-02 would meet them); the calendar year of `sampleDate` equals `season` for every kept row (`sample_year_differs_from_season` is 0); 133 bathing-water and date pairs have more than one
sample (the EEA's sample-date description allows up to two samples per date at different points of a large bathing water). Both samples are kept.

## 5. Store layout

SQLite file, outside the repository: `OAH_BATHING_SAMPLES_STORE` when set (absolute path), else `<data dir>/bathing_samples/bathing_samples_discodata.sqlite` (`oah.paths.bathing_samples_store_path`). Schema version 2 (version 1 had one index on country and date; a store of version 1 is reported `unreadable` and must be rebuilt).

- `samples(bw_id, sample_date, uid, country, season, ec_value, ec_status, ec_kind, ie_value, ie_status, ie_kind, sample_status, obs_status, has_remarks)`, `WITHOUT ROWID`, primary key `(bw_id, sample_date, uid)`;
  three indexes for the country comparison (schema 2, see "Country comparison read path" below): `idx_samples_kinds (country, sample_date, ec_kind, ie_kind)` (covering) and two PARTIAL indexes,
  `idx_samples_ec_quantified (country, bw_id, ec_value, sample_date) WHERE ec_kind IN ('Q','C')` and `idx_samples_ie_quantified (country, bw_id, ie_value, sample_date) WHERE ie_kind IN ('Q','C')`.
- `sites(bw_id PK, country, n_samples, first_date, last_date, first_season, last_season)`.
- `country_summary(country PK, bathing_waters, n_samples, first_date, last_date, first_season, last_season, n_quantified_ec, n_quantified_ie, first/last quantified date per indicator)` (precomputed: a whole-country scan takes seconds).
- `provenance(key, value)`: source, source URL, endpoint, table, edition, the observed proxy of `[latest]`, licence, attribution, build date (UTC), `complete`, unit and its statement, the content statement, the country rule, the
  query texts, page size, rows extracted and service counts per prefix, rows kept per country and per country and season, the sample date range per country, the value kinds and their counts per indicator, the status counts,
  sample status and observation status counts, the fetch statistics (requests, retries, transient errors, bytes, longest reply, short pages) and every counter.

### Country comparison read path (schema 2, 2026-10-04)

A country comparison (`GET /bathing-waters/samples/change?country=...`, the chat tool) needs, per bathing water and period, the number of quantified samples, their sum, minimum and maximum, the calendar months with a value
and the exact median, plus the counts by kind over the whole country. With the schema 1 index (country, date) every such read looked each row up in the 84 MB table (a covering read of the same rows
costs about one tenth), and the comparison made about 12 passes (two windows times two indicators times aggregates, medians and kind counts): 61 s for Italy, 18 s for Greece.

Now: ONE sequential pass per indicator over its partial index, which holds only the quantified values (kinds Q and C), ordered (country, bathing water, value) and carries the date, so the table is never touched and
the values of one bathing water arrive together. A small user-defined aggregate (`oah.bathing_samples.country_scan`, `oah_window_scan(value, sample_date)`) collects, per window, the integer values and the months seen of the
bathing water in hand and returns `[n, sum, min, max, month mask, median]` per window; the values are sorted in the aggregate (it does not rely on the scan order), the sum is a Python integer (exact), and the median is the middle
value or `(a + b) / 2` of the two middle ones, the expression of `statistics.median`. One extra pass over the covering index `idx_samples_kinds` returns the counts by kind for BOTH indicators and both windows. Per call: three
passes (two indicators and the kinds) instead of twelve; memory is the values of one bathing water. The reader names the indexes (`INDEXED BY`), so a store without them cannot be read: that is why the schema version is 2. The
medians are computed for every bathing water of the country in the same pass (no second per-site filter); only the paired ones are used. Nothing is approximated: the raw values are read, and the result is bit-identical to the
reference row path (`oah.bathing_samples.change.country_change_rows`, one cell per bathing water and month plus every value), proven by `tests/property/test_country_scope_parity.py` on random synthetic stores and by
`scripts/check_country_scope_parity.py` on the real store. The row cap (`MAX_COUNTRY_ROWS`), the wall-clock cap (`COUNTRY_READ_SECONDS`) and the scope guard of `docs/period_change.md` section 11 are unchanged.

Cost of the indexes: the store grows from 83,603,456 to 137,486,336 bytes (about 54 MB, `idx_samples_kinds` and the two partial indexes; the old `idx_samples_country_date` is dropped), and the build writes them in about 3 s more.
Tables are byte for byte the same rows: the `samples`, `sites` and `country_summary` tables of the new build have the same SHA-256 over their rows as the previous store (checked on 2026-10-04).

States of the reader (`oah.bathing_samples.store`): `ready`, `not-built`, `unreadable` (a damaged file or another schema version). Nothing raises for a missing store. Parameterised SQL, read-only connection (`mode=ro`, `query_only`),
a page of at most 500 samples, identifiers of at most 128 characters, a country-scope read of at most 1,500,000 rows, column names from a closed mapping.

## 6. Real build (2026-10-03, with `--restart`: a full download)

- **123 s** wall time (45 requests: 3 counts, 39 pages (Greece 11, Italy 28), 3 empty end pages; 0 retries; 222,975,775 bytes received; the largest reply 6,293,446 bytes for 20,000 rows; `short_pages_before_end` 0; page size 20,000; pacing 0.5 s).
- **754,451 rows scanned and kept**, none dropped, no duplicate `UID`; Greece 208,176 (2,419 bathing waters, seasons 2008-2024, sample dates 2008-05-05 to 2024-10-18), Italy 546,275 (5,930 bathing waters, seasons 2010-2024, sample dates 2010-01-01 to
  2024-10-28), Norway 0. Extracted rows equal the service's own counts. 8,349 bathing waters in all.
- Rows per season, Greece: 2008 23,127; 2009 15,568; 2010 21,550; 2011 12,963; 2012 12,946; 2013 13,352; 2014 9,343; 2015 9,334; 2016 9,571; 2017 9,701; 2018 9,643; 2019 9,886; 2020 9,896; 2021 10,203; 2022 10,135; 2023 10,529; 2024 10,429.
  Italy: 2010 36,690; 2011 36,235; 2012 37,294; 2013 37,488; 2014 37,397; 2015 37,431; 2016 37,465; 2017 37,352; 2018 37,227; 2019 36,802; 2020 32,728; 2021 34,719; 2022 35,581; 2023 35,822; 2024 36,044.
- Quantified values: E. coli 641,918 (641,890 plain and 28 confirmed high; Greece 172,723, Italy 469,195), enterococci 630,110 (630,093 and 17; Greece 181,105, Italy 449,005). Largest quantified value: Greece E. coli 15,000 and enterococci 7,800; Italy 140,000 and 127,000.
- **Store size 83.6 MB (83,603,456 bytes)** at schema 1, **137.5 MB (137,486,336 bytes)** at schema 2 (the three country-comparison indexes), outside the repository.
- **Rebuild at schema 2 (2026-10-04, `python scripts/build_bathing_samples_store.py`, full download): 142 s** (45 requests, 0 retries), the same row counts: **754,451 rows (Greece 208,176, Italy 546,275)**, 8,349 bathing waters, and the same rows (equal hashes of the three data tables).
- The identifiers join the classification store: 8,309 of the 8,349 sampled bathing waters are in it (40 are not: 1 Greek and 39 Italian), and 341 bathing waters of the classification store have no sample row (for example those that exist only from 2025).
- Seasons stop at **2024** in this table; the classification file has 2025. A question about the 2025 season is answered with `data_range`, never with a guess.

## 7. Reader, API, chat

Routes and fields: `docs/api_routes.md`. `GET /bathing-waters/{bw_id}/samples` (the samples with both values, both statuses, the sample status, and a summary over all matches: counts by kind, min, max, mean, exact median of the quantified
values), `GET /bathing-waters/{bw_id}/samples/change` and `GET /bathing-waters/samples/change` (period comparison), the `samples` link of `GET /bathing-waters/{bw_id}`, the `samples` block and the `bathing_samples` state of `/countries`. Chat: `get_bathing_samples`
and `compare_bathing_concentrations` (`docs/chat_agent.md`), chat index `microbiology`. The three fixed notices (samples, no threshold, flagged values) and the comparison notice are localised strings (`oah.i18n.strings`, 25 machine-drafted files).

Why a new `origin` value (a shared-contract change that needs the maintainer's approval): `real-eea-bathing-water` is documented, in code, tests, responses and the chat prompt, as "a classification, never a concentration"; reusing it
for concentrations would make that sentence false for a client that reads the origin. `real-eea-bathing-samples` keeps each label true. It is added to `Origin` (`SitesResponse`, `ChatResponse` and every model that uses it).

## 8. Period comparison (`oah.bathing_samples.change`, over `oah.indices.period_change`)

The existing machinery is reused unchanged: `Period` (calendar months, both ends included), `compare_site` and `compare_country` with the parameter declared measurement only. Monthly cells (`n`, sum, min, max of the QUANTIFIED values of a bathing
water in a calendar month) come from the store. Therefore: the same coverage rule (3 quantified samples per period at a bathing water), the same flags, `data_range` (first and last month with a quantified value, all time), a country uses
paired bathing waters only, and a period beyond the data is reported (`period-outside-data`), never shifted. Added here: the exact median per period (the middle quantified value, or the mean of the two middle ones; for a country the median of the
per-bathing-water medians of the paired bathing waters), the change of the median beside the change of the mean, counts of flagged values per period, and the flags `detection-limit-values-excluded`, `missing-values-excluded`,
`unrecognised-status-values-excluded`, `confirmed-high-values-included`. The flag `below-loq-excluded-bias-upward` of the machinery is NOT used: it asserts a direction, and the direction of a detection-limit number is unknown (section 4).
No limit exists, so there is no limit assessment and no `crossed_limit`; no significance is tested. Formulas are those of `docs/period_change.md` section 2 (mean = sum / n, absolute = mean_B - mean_A, relative percent = 100 x absolute / |mean_A|, direction by
equality after rounding to 6 decimals); the median and the median of site medians are the plain statistics (`statistics.median`), taken from exact integers, so nothing here is a new formula.

Bathing waters are sampled in the bathing season only (almost all Italian samples are dated March to October and all Greek ones May to October), so a period that includes other months always carries `partial-period`; a user who wants a fair
comparison should compare the same months (for example May to September of two years).

## 9. A real worked example (read from the real store on 2026-10-03)

`IT011043006001`, STABILIMENTO RIVA VERDE (`lakeBathingWater`, Italy; classification of the latest season 2025: `2 - Good`), season 2024, `GET /bathing-waters/IT011043006001/samples?season=2024`: 14 samples (2010-04-15 to 2024-09-23 over all seasons: 118 samples).

| Date | Sample status | E. coli (cfu/100ml) | Intestinal enterococci (cfu/100ml) |
|---|---|---|---|
| 2024-04-16 | preSeasonSample | 22 | 6 |
| 2024-05-06 | - | 10 | 18 |
| 2024-05-20 | - | 40 | 100 |
| 2024-06-03 | - | 15 | 30 |
| 2024-06-17 | - | 16 | 110 |
| 2024-07-01 | - | 4 | 140 |
| 2024-07-15 | shortTermPollutionSample | 44 | 700 |
| 2024-07-17 | confirmationSample | 4 | 23 |
| 2024-07-23 | replacementSample | 10 | 30 |
| 2024-07-29 | - | 10 | 380 |
| 2024-08-12 | - | 5 | 45 |
| 2024-08-26 | - | 10 | 50 |
| 2024-09-09 | - | 150 | 290 |
| 2024-09-23 | - | 4 | 25 |

Summary (all 14 values quantified, no flag): E. coli minimum 4, maximum 150, mean 24.571429, median 10; enterococci minimum 6, maximum 700, mean 139.071429, median 47.5. No threshold is applied; the
classification of that bathing water is a separate fact from `GET /bathing-waters/IT011043006001`. A period comparison of this bathing water, April to October 2019 against April to October 2024, gives E. coli mean 30.666667
(6 samples) to 24.571429 (14 samples), median 18 to 10, change of the mean -6.095238 (-19.8758 percent, `decreased`), and enterococci mean 32.166667 to 139.071429, median 34 to 47.5; both periods carry `partial-period`, and period B
carries `period-outside-data` because the last sample of the bathing water is dated 2024-09-23 while the period runs to 2024-10.

A flagged example, `IT011044017003` (DAVANTI TORRENTE SAN EGIDIO, coastal), season 2024: 11 samples, E. coli 5 flagged `detection-limit` (reported 1, 1, 1, 24,000 and 20,000) and 6 quantified (1, 20, 22, 10, 10, 150): the summary says n_quantified 6,
n_detection_limit 5, minimum 1, maximum 150, mean 35.5, median 15; enterococci 4 flagged (reported 1, 1, 1 and 28,000) and 7 quantified, maximum 3,900. The flag `detection-limit-values-excluded` is set and the 24,000 is never shown as a result.

## 10. Limitations

1. Individual samples, not a classification and not a compliance assessment. No threshold, no limit, no guideline value, no significance: never invented, never applied. A sample result is not a health or safety determination;
   the chat declines such questions and points to the competent authority.
2. Detection-limit values are 13 to 17 percent of the samples and are excluded from the statistics; the direction of their censoring is unknown (section 4). Means and medians of the quantified values overstate or understate the typical value
   in a way the data does not let us bound; always read the counts.
3. Seasons 2008-2024 (Greece) and 2010-2024 (Italy) only; the 2025 season is not in the table of the build. Norway has no sample.
4. `[latest]` is a view that the EEA can repoint to a newer release; the build date and the observed proxy name are in the provenance.
5. `metadata_observationStatus` is not interpreted and no row is dropped by it; the 187 Italian samples dated 1 January are kept as reported.
6. Short-term-pollution, confirmation and replacement samples are included in the statistics (they are real measurements); the sample status is shown so a reader can separate them.
7. A mean over a bathing season is not how the Directive classifies a bathing water (the classification rule is not in this project and is not reproduced); it must not be presented as a class.
8. The licence is inferred from the EEA legal notice; the unit is verified from the table metadata (read once, 2026-10-03; the metadata endpoint is not queried at build time).
9. A country comparison of Italy reads every quantified sample of the two windows (one pass per indicator, see "Country comparison read path") and takes about 3.4 s cold on the laptop that measured it (Greece about 1.1 s); an identical question is then answered from the 10-minute scope-guard cache (`docs/period_change.md` section 11).
10. The Discodata service is a third party: a build needs network access and the service to be up; the stores that are already built do not.

## 11. Rebuild and settings

```
python scripts/build_bathing_samples_store.py --dry-run     # plan, paths, query texts: no request
python scripts/build_bathing_samples_store.py               # about two minutes; resumable
python scripts/build_bathing_samples_store.py --restart     # start from the first page
```

Options: `--output`, `--work-dir` (absolute external paths), `--page-size` (1 to 50,000, default 20,000), `--max-pages`, `--min-interval` (at least 0.25 s), `--restart`, `--keep-work`, `--dry-run`. Exit codes: 0 built, 2 extraction error (count mismatch, a
refusal, an empty extraction), 3 incomplete (`--max-pages`). Setting (never committed; add it to `.env.example`): `OAH_BATHING_SAMPLES_STORE` (optional absolute path of the store). The deployment stage script and image must include the new store
file name `bathing_samples_discodata.sqlite` (see `docs/deployment.md`); without it the routes answer with `bathing_samples.state` `not-built`.

## 12. Tests

`tests/unit/test_bathing_samples_client.py` (query text and bounds, injection, the host and scheme, HTTP error mapping, bad JSON, empty pages, retries and backoff, pacing, keyset paging, a service row cap, a service that ignores the keyset, hard bounds),
`test_bathing_samples_build.py` (the kind of every value, filters, EL stored as GR, Norway absent, provenance, determinism, atomic write, resume, damaged work files, count mismatch, `--max-pages`, the command line), `test_bathing_samples_store.py`
(states, bounds, injection, exact statistics, flagged values counted apart, month cells, read-only), `test_bathing_samples_api.py` (routes, contracts and error codes, localisation, `/countries`, the history link, exact period changes by hand, the
May 2021 to May 2026 out-of-range case, paired countries), `test_bathing_samples_chat.py` (the tools, bounds, country enforcement, grounding with a fake model that invents a concentration, a threshold or a percent, the "safe to swim" refusal),
`test_bathing_samples_strings.py`, `test_bathing_samples_properties.py` (hypothesis), `tests/contract/test_bathing_samples_contract.py`. The service is a scripted fake (`tests/unit/samples_fixtures.py`) and every row is SYNTHETIC and labelled; no test uses the
network or the real data.
