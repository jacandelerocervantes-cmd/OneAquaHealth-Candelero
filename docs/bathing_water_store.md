# EEA bathing-water classification store (backend package 4)

Date: 2026-10-02. Code: `src/oah/bathing/` (`constants.py`, `xlsx.py`, `build.py`, `store.py`, `service.py`), command line
`scripts/build_bathing_water_store.py`. This is the Microbiology item of the catalogue (`docs/indices_catalog.md`), and it is
**a classification, not a measurement of bacteria**. Everything read from it is labelled `origin` / `source`
`real-eea-bathing-water` and is never mixed silently with `real-sandbox` or `real-eea-waterbase` data.

## What this data is and what it is not

The file holds, for each bathing water and each season, the CLASSIFICATION assigned under Directive 2006/7/EC, plus the
monitoring calendar and management status of that season. It does **not** hold E. coli or intestinal enterococci
concentrations (colony counts per 100 mL). Those individual sample results are a SEPARATE dataset, read from the EEA Discodata
service and stored in their own SQLite store with their own origin `real-eea-bathing-samples` (backend package 6,
`docs/bathing_samples_store.md`); the two stores share the bathing-water identifier (8,309 of the 8,349 sampled identifiers are in this
store) and are never merged into one figure. About THIS store and its routes:

- no concentration, no limit and no threshold appears anywhere in the store, the API or the chat tools, and none is invented;
- the classes are shown as the file writes them (`1 - Excellent`, ...) and are never converted into a number;
- the classification is not a statement of legal compliance and not a health or safety determination (`notice` on every response);
- protozoa (Giardia, Cryptosporidium) are not available in any form.

What the README of the archive says (quoted exactly, nothing added):

- "Member States are also requested to monitor the concentration in water of E. coli and intestinal enterococci."
- "Based on the monitoring results for these bacteria, bathing waters are classified into four quality categories: excellent, good, sufficient, or poor."
- "At least four water samples per bathing water need to be collected and analysed" (the rest of that sentence in the README
  contains a damaged character and is not quoted).

These sentences are stored in the provenance (`readme_statements`). The classification rule itself (which percentile of which
counts gives which class) is not in the README or in this project, so it is not reproduced.

## Source, licence, attribution

- Dataset: EEA, Bathing Water Directive - Status of bathing water, 2025 v.1.0 (seasons 1990-2025), `v01_r00`.
  Page: https://www.eea.europa.eu/data-and-maps/data/bathing-water-directive-status-of-bathing-water-12
- Licence: EEA CC BY 4.0 (EEA legal notice; the dataset page does not restate it).
- Attribution string shown by the API: `EEA Bathing Water Directive - Status of bathing water, 2025 v.1.0 (EEA CC BY 4.0)`.
- Archive (kept OUTSIDE the repository, in `<data dir>/data/bathing_water/2025/`): `eea_t_bathing-water-status_p_1990-2025_v01_r00.zip`,
  43,402,140 bytes, SHA-256 `27278b3f2795197c24c302def4d78f08030b883d45e4859f63832bbb1fd4ae2d` (computed by the build, recorded in the store).
- Archive layout (verified 2026-10-02): a ZIP with one top-level folder holding `README.md`, a metadata XML, `BW.png` and
  `bw_assessment_eea_datahub_1990_2025.xlsx` (43 MB, a STORED member). The workbook has the sheet
  `bw_assessment_datahub_1990_2025` (694,918 data rows, 13 columns, 291 MB of sheet XML, 90,825 distinct shared strings) and a
  second sheet `Ark1`, not used.
- Columns used (names exactly as in the file): `countryCode`, `bathingWaterIdentifier`, `groupIdentifier`, `bathingWaterName`,
  `bathingWaterType`, `geographicalConstraint`, `lon`, `lat`, `bwProfile`, `season`, `quality`, `monitoringCalendar`, `management`.

## Countries in the file (read this before promising coverage)

The file's `countryCode` values (verified on the full sheet): AL, AT, BE, BG, CH, CY, CZ, DE, DK, EE, **EL**, ES, FI, FR, HR, HU,
IE, **IT**, LT, LU, LV, ME, MT, NL, PL, PT, RO, SE, SI, SK, UK. Consequences:

- Greece is written **EL** (61,697 rows); the project treats EL as an alias of GR everywhere, so it is stored and served as `GR`
  (`GR` is accepted too if an edition uses it).
- Italy is `IT` (189,853 rows).
- **Norway has no row in this file** (no `NO`, and no `IS` or `LI` either). The build still accepts `NO`, so a later edition that
  carries it works without a change, but today the store holds Greece and Italy only. The earlier plan of "GR/IT/NO" cannot be met
  with this dataset; the API, the chat prompt and `/countries` say so (Norway has no `bathing_water` block).

## Exact filters (what the store keeps)

| Step | Rule | Counter |
|---|---|---|
| Country | `countryCode` in `EL`, `GR` (stored `GR`), `IT`, `NO` | `rows_other_countries` (443,368 in the real build) |
| Identifier | `bathingWaterIdentifier` not blank | `dropped_no_identifier` |
| Season | `season` is a whole number from 1900 to 2100 | `dropped_bad_season` |
| Seasons | ALL seasons are kept (1990-2025) | - |

Everything else is kept and counted, never dropped: a blank `quality` is stored as null (`rows_without_quality`); a `quality`
value the project has not seen is stored as written and listed in the provenance (`unknown_quality_values`); a coordinate that is
missing, not a number or out of range is stored as null (`rows_coordinates_invalid_or_partial`, `bathing_waters_without_coordinates`);
the placeholder name `UNKNOWN` is stored as null (shown as the identifier); a `bwProfile` that is not an `http(s)` URL is stored as
null (`profile_url_not_http`; this stops a `javascript:` value from ever reaching a client).

- One bathing water appears once per season, with the name, type, coordinates and profile of THAT season. The `sites` row takes the
  attributes of the latest season; the coordinates come from the latest season that has them (an earlier season supplies them when
  the latest has none). A bathing water listed under two countries keeps the first country in key order (counted; none in the real build).
- Two rows for the same bathing water and season are counted (`duplicate_site_season_rows`, `..._conflicting`) and one is kept: the
  one with the smallest `(quality, calendar, management)` tuple, so the result never depends on the input order. The real 2025 v1.0
  file has none.

## Store layout

SQLite file, outside the repository: `OAH_BATHING_WATER_STORE` when set (absolute path), else
`<data dir>/bathing_water/bathing_water_2025.sqlite` (`oah.paths.bathing_water_store_path`). Written atomically (temporary file,
then rename), rows in key order, so the same input gives the same tables (only `build_date_utc` differs). Schema version 1.

- `sites(bw_id PK, country, group_id, name, type, geographical_constraint, lat, lon, profile_url, first_season, last_season,
  n_seasons, latest_quality, latest_quality_class)`; indexes on `(country, bw_id)`, `(country, type)`, `(country, latest_quality)`.
- `classifications(bw_id, season, quality, quality_class, monitoring_calendar, management)`, primary key `(bw_id, season)`.
  `quality` is the file's string; `quality_class` is the text after the code (`1 - Excellent` -> `Excellent`), null when the
  string has no such shape. That label split is the only derived field.
- `provenance(key, value)`: source, source URL, edition, licence, attribution, archive name, size and SHA-256 (computed), workbook
  and sheet names, build date (UTC), filters, content statement, README sentences, value counts per column (`quality`, `type`,
  `monitoring_calendar`, `management`), unknown quality values, row counts, schema version.

## Values observed in the real file (countries kept: GR and IT)

`quality` (all seasons, 251,550 rows; written as in the file, "Good or Sufficient" and "Not classified" are NOT among the four
categories the README names and the README does not explain them, so they are kept as written and not interpreted):

| Value | GR | IT |
|---|---|---|
| `0 - Not classified` | 2,143 | 7,839 |
| `1 - Excellent` | 57,649 | 165,157 |
| `2 - Good` | 562 | 4,029 |
| `3 - Good or Sufficient` (seasons 1990-2012 only) | 991 | 6,742 |
| `3 - Sufficient` | 73 | 1,474 |
| `4 - Poor` | 279 | 4,612 |

- Latest season (2025): GR 1,684 excellent, 42 good, 1 sufficient, 7 not classified, none poor; IT 4,972 excellent, 340 good, 104
  sufficient, 72 poor, 47 not classified.
- `bathingWaterType`: `coastalBathingWater`, `lakeBathingWater`, `riverBathingWater`, `transitionalBathingWater` (GR: 2,419 coastal, 7 lake;
  IT: 5,241 coastal, 843 lake, 72 river, 68 transitional bathing waters).
- `monitoringCalendar`: `1 - Implemented`, `0 - Not implemented`; present only for seasons 2018-2025 (blank, shown as null, for
  1990-2017: 193,872 of the 251,550 rows). `management`: `1 - Continuously monitored`, `2 - Newly identified`, `3 - Quality changes`,
  `4 - Monitoring gap`; present for seasons 2013-2025, blank before. Blank is shown as null.
- `geographicalConstraint` is the text `FALSE` (8,168 bathing waters) or `NOT KNOWN` (482); passed through, not interpreted.
- The source file has damaged characters (a replacement character) in some names of other countries (seen in a Danish name); none
  was found in the Greek or Italian names kept here.

## Real build (2026-10-02)

86 s the first time, 44 s the second (arm64 laptop): 694,918 data rows scanned, 251,550 of Greece and Italy kept (443,368 other countries
dropped, nothing else dropped), **8,650 bathing waters (GR 2,426, IT 6,224; none for NO)**, 251,550 classification rows, seasons
**1990-2025** for both countries (7,269 bathing waters have a 2025 row), 359 bathing waters without coordinates (all Italian), 487
without a usable profile link, 1 with the placeholder name, no unknown classification value, no duplicate. Store size 19.5 MB
(19,460,096 bytes).

## Reader, API and chat

- Reader `src/oah/bathing/store.py`: read-only connection (`mode=ro`, `query_only`), parameterised SQL, page at most 500 rows, text
  filters cut at 64 characters, LIKE wildcards escaped, history at most 200 seasons. States: `ready`, `not-built`, `unreadable`
  (another schema version or a damaged file). Nothing raises for a missing store.
- `GET /bathing-waters` and `GET /bathing-waters/{bw_id}` (`docs/api_routes.md`), the `bathing_water` blocks of `GET /countries`,
  and the chat tools `list_bathing_waters` and `get_bathing_water_history` (`docs/chat_agent.md`). `quality` filters on the LATEST
  season's class, by the whole string or its label, case-insensitively.
- `bw_profile_url` is returned as plain text, never fetched or followed by this project, and is not sent to the chat model (the
  safety layer removes URLs from tool results anyway). A client must render it as text, not as an automatic link.

## Season comparison (package 5)

`GET /bathing-waters/change?country=&season_a=&season_b=&type=&language=` and the chat tool `compare_bathing_seasons` count how the classification of a
country's bathing waters moved between two seasons (`src/oah/bathing/change.py`, `docs/period_change.md` section 8). ONLY the order the README names is used:
`excellent`, `good`, `sufficient`, `poor` (best first), matched on the label after the code (`1 - Excellent` is Excellent). `0 - Not classified`,
`3 - Good or Sufficient` and a blank or unknown class are not comparable: a bathing water that has one of them in either season is counted in
`not_comparable` (by pair of strings as written) and enters no transition. A bathing water with a row in only one of the two seasons is counted as
`only_in_season_a` or `only_in_season_b` and never imputed. The route returns per-season totals per class string, `paired_bathing_waters`, `comparable`,
`moved_up`, `moved_down`, `unchanged` and the non-zero transitions. No concentration, no threshold and no meaning beyond the order is used or stored; the
fixed notices (`bathing_water_classification_notice`, `bathing_change_notice`) are localised. SQL: two grouped, parameterised joins of `sites` with
`classifications` (primary key `(bw_id, season)`), `type` case-insensitive; the store schema is unchanged (version 1).

## Limitations

1. Classification only. No concentration, no per-sample result, no limit, no threshold; a class must never be shown as a number.
2. Not legal compliance. The class is the EEA's published assessment for the season; this project does not recompute it.
3. Greece and Italy only; the file has no Norwegian bathing water.
4. The latest season differs per bathing water (most have 2025; a few stop earlier). `/countries` gives `latest_season` per country.
5. The README names four categories; the file also has `0 - Not classified` and `3 - Good or Sufficient`. Their meaning is not given
   there and is not guessed. Treat them as "other" in a display, with the file's text.
6. `monitoringCalendar` is blank before the 2018 season and `management` before 2013.
7. The store is a snapshot of one published edition; `data_freshness` is `snapshot` dated by the build.
8. The licence text is the EEA general one (the dataset page does not restate it); `SOURCES.yaml` records it as inferred, to be confirmed.
9. The concentrations behind these classes are NOT in this store. For the individual E. coli and enterococci results (Greece 2008-2024, Italy 2010-2024, no thresholds)
   see `docs/bathing_samples_store.md`; a class here must still never be shown as a number, and a sample result there is never turned into a class.

## Rebuild

Prerequisites: the archive in `<data dir>/data/bathing_water/2025/`. No 7-Zip and no third-party package: the sheet is read with
`zipfile` and `xml.etree` (`oah.bathing.xlsx`), streaming, so memory stays flat (about 300 MB of XML is parsed row by row).

```
python scripts/build_bathing_water_store.py --dry-run
python scripts/build_bathing_water_store.py            # about one to two minutes
```

Options: `--archive`, `--output` (absolute external paths). Setting (never committed; add it to `.env.example`):
`OAH_BATHING_WATER_STORE` (optional absolute path of the store). A compressed workbook member (the real one is stored) is first copied
to `<data dir>/bathing_water/work/` and removed afterwards.

## Tests

`tests/unit/test_bathing_xlsx.py` (cell kinds, shared and inline strings, sheet lookup, a 60,000-row sheet streamed under a 2 MB
memory peak), `test_bathing_build.py` (filters, EL alias, unknown class, blank class, coordinates, profile URL, duplicates, provenance,
atomic and deterministic writes, the command line), `test_bathing_store.py` (states, filters, bounds, injection, read-only),
`test_bathing_api.py` (routes, `/countries`, tools, prompt facts, the chat route with a scripted fake client). The workbooks are
SYNTHETIC, built in the test with `zipfile` and plain XML (`tests/unit/bathing_fixtures.py`); names, identifiers and classes are
invented. No test uses the network or the real archive.
