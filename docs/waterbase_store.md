# EEA Waterbase store (backend package 3)

Date: 2026-10-02 (package 3); extended the same day by package 4 with the solids-turbidity and organic-matter groups (below) and by
package 5 with MONTHLY resolution (schema version 3, below; `docs/period_change.md`).
Code: `src/oah/waterbase/` (`mapping.py`, `build.py`, `store.py`, `measurements.py`, `service.py`), command line
`scripts/build_waterbase_store.py`. This is the first ingestion of real data beyond the sandbox. Everything read from it is labelled
`origin` / `source` `real-eea-waterbase` and is never mixed silently with `real-sandbox` data (`docs/api_routes.md`).

## Source, licence, attribution

- Dataset: EEA Waterbase - Water Quality ICM, 2026 edition (data 1900-2025, published 7 July 2026), WISE6 tables, `v01_r00`.
  Page: https://www.eea.europa.eu/data-and-maps/data/waterbase-water-quality-icm-2
- Licence: CC BY 4.0, European Environment Agency (EEA legal notice; the dataset page does not restate it; see `SOURCES.yaml`).
- Attribution string shown by the API: `EEA Waterbase - Water Quality ICM 2026 (CC BY 4.0)`. Keep it next to any figure shown to a reader.
- Archive (kept OUTSIDE the repository, in the data directory): `eea_t_waterbase-water-quality-icm-2026_p_1900-2025_v01_r00.zip`,
  4,573,371,134 bytes, SHA-256 `dd333082eeedb676f70bc195b55c29993bef15d0afef6b020d58bf4d83b5f8f9` (verified by hand on 2026-10-02, see the ledger).
  The store records the hash read from the `.sha256` file next to the archive (or computed with `--compute-sha256`).
- Archive layout used (verified on 2026-10-02): an outer stored ZIP with one top-level folder containing
  `WISE6_DisaggregatedData-csv.zip` (1.6 GB; a compression method Python's `zipfile` cannot read, so it is streamed with 7-Zip,
  28.5 GB of CSV, 96.6 million rows) and `WISE6_SpatialObjects_DerivedData-csv.zip` (2.8 MB, deflate; 24 MB of CSV). All CSVs start
  with a UTF-8 BOM (read as `utf-8-sig`; a BOM-prefixed header name once broke an earlier scan) and use CRLF.

## Exact filters (what the store keeps)

Applied in this order to the disaggregated table; every drop is counted in the provenance (`row_counts`).

| Step | Kept | Dropped counter |
|---|---|---|
| Country (`countryCode`) | `EL` (stored as `GR`; the project already treats EL as an alias of GR), `GR` (accepted, absent in this edition), `IT`, `NO` | counted as scanned only |
| Water body category (`parameterWaterBodyCategory`) | `RW` river, `LW` lake. Groundwater (`GW`), coastal (`CW`) and transitional (`TW`) waters are excluded: the project's limit regimes cover rivers and drinking water only | `dropped_category` |
| Determinand (`observedPropertyDeterminandCode`) | the 29 codes of the mapping table below (21 water chemistry, 8 measurement-only) | `dropped_determinand` |
| Matrix (`procedureAnalysedMatrix`) | per determinand: `W` and `W-DIS` for the 21 chemistry codes; ONE matrix for each measurement-only code (`W`, and `W-DIS` only for dissolved organic carbon). Anything else, for example the `W-SPM` and `S` variants, is dropped | `dropped_matrix` |
| Observation status (`resultObservationStatus`) | everything except `L`, `M`, `N`, `O`, `W` (the dataset definition's "missing observed value" statuses) | `dropped_missing_value_status` |
| Sampling year | `phenomenonTimeSamplingDate` year >= `MIN_YEAR` (2010) | `dropped_before_min_year`, `dropped_bad_date` |
| Unit and site | a non-empty `resultUom` and `monitoringSiteIdentifier` | `dropped_no_unit_or_site` |
| Value | `resultObservedValue` is a finite number, unless the row is flagged below the limit of quantification (next paragraph) | `dropped_no_numeric_value` |

- There is NO year column in the disaggregated table (the definition file mentions `phenomenonTimeReferenceYear`, the file does not
  have it): the year is the first four characters of `phenomenonTimeSamplingDate` (format `YYYYMMDD`).
- `MIN_YEAR = 2010` is a choice of this project (recent monitoring, smaller store), not a property of the data. `--min-year` changes it;
  the value used is stored in the provenance `filters`.
- Below the limit of quantification (`resultQualityObservedValueBelowLOQ` = `1`): the row is counted in `n_below_loq` and its
  `resultObservedValue` (which holds the quantification limit or a placeholder such as 0) is NEVER used as a measurement. A below-LOQ
  row is counted even when its value is not numeric (it is information that a sample was taken and not quantified).
- `metadata_observationStatus` `U` (lower reliability) or `V` (unvalidated): the row is kept and counted in `n_lower_reliability`
  (counted over quantified and below-LOQ rows alike). `A` is a normal record.
- Rows whose quoted field spans several lines (the statements column can) are joined before the country check, so a continuation line is
  never read as a record of its own.

### Aggregation, monthly resolution and the median limitation

The 28.5 GB table is streamed once, so no sample values are kept: per (country, site, category, determinand code, matrix, unit, year,
MONTH) the store holds `n` (quantified samples), the SUM of those samples, `min`, `max`, `n_below_loq` and `n_lower_reliability` (U or V).
Keeping the sum and the count makes every coarser mean exact: a year, a period or a country mean is `sum of the sums / sum of the counts`
(not a mean of monthly means). The month is the 5th and 6th characters of `phenomenonTimeSamplingDate` (`YYYYMMDD`; the dashed spelling
`YYYY-MM-DD` is read too; a month outside 1 to 12 is `dropped_bad_date`). **There is no median.** (The sandbox records are judged on their
median; Waterbase records on the mean. The two are not interchangeable, see Limitations.) The unit is part of the key, so a determinand reported
in two units is never averaged across them. The filters, the mapping, the below-LOQ handling and the units are exactly those of the annual
store (package 4); only the grain changed, and the same counters give the same totals (1,678,198 quantified and 745,133 below-LOQ rows kept).

## Store layout

SQLite file, outside the repository: `OAH_WATERBASE_STORE` when set (absolute path, validated like the other path settings), else
`<data dir>/waterbase/waterbase_icm_2026.sqlite` (`oah.paths.waterbase_store_path`). Written atomically (temporary file, then rename),
rows in key order, so the same input gives the same tables (only `build_date_utc` differs).

- Schema version 3 (package 5: monthly resolution; version 2, package 4, added `country_determinands` and the measurement-only codes; version 1 had
  neither). A version 1 or 2 store is reported as `rebuild-required` (`waterbase.state` of `/sites` and `/countries`, with a clear detail text) and is
  never read; rebuild it with `scripts/build_waterbase_store.py`. Any other unknown version or a damaged file is `unreadable`; no file is `not-built`.
- `country_determinands(country, determinand, n_sites, n_records)`: which determinands each country holds (primary key
  `(country, determinand)`), so `/countries` lists the parameter groups per country with one small read.
- `measurements(country, site_id, category, determinand, matrix, unit, year, month, n, sum_value, min, max, n_below_loq, n_lower_reliability)`,
  primary key `(site_id, determinand, matrix, unit, year, month)` (WITHOUT ROWID, rows written in primary-key order), and NO secondary index:
  a second index would roughly double the file, so a read for a whole country goes through the sites of the country (one primary-key seek per
  site; a test checks the query plan). `min` and `max` are null when `n = 0` (every sample of the month was below the quantification limit; `sum_value` is then 0).
  The annual view the reader still offers (`site_series`, the default of `/sites/{id}/measurements`) is computed from the months with `GROUP BY year`.
- `country_ranges(country, first_month, last_month)`: the first and last month (`YYYY-MM`) with any kept record per country, so `/countries`
  shows what each source covers with one small read.
- `sites(site_id, country, category, name, water_body_id, water_body_name, lat, lon, confidentiality, first_year, last_year, n_records)`:
  one row per site that has at least one kept record, joined to the spatial table (`WISE6_SpatialObjects_DerivedData`, rows with a
  `monitoringSiteIdentifier`). `lat` and `lon` are null when blank, out of range or restricted; `confidentiality` is the file's
  `confidentialityStatus` (`F` free, `N` not for publication; the coordinates of `N` sites are blank in the 2026 edition, and the
  build and every reader enforce the rule even when an edition supplies them: see "Confidentiality of sites" below). The placeholder name `UNKNOWN`
  is stored as null. A site whose records span two categories (3 in the real build) takes the category with most records, ties
  alphabetical. A site id that appears under two countries keeps the first country (counted; none in the real build).
- `provenance(key, value)`: source, source URL, edition, licence, attribution, archive name, size and SHA-256 (and where the hash came
  from), build date (UTC), filter parameters (JSON), row counts (JSON), schema version.

## Confidentiality of sites (privacy, defence in depth)

Date: 2026-10-03 (security fix F1). The spatial table gives every site a `confidentialityStatus`: `F` (free for publication) or `N` (not
for publication). In the 2026 edition the 167 Italian sites flagged `N` have NO coordinates in the source, so nothing was ever exposed;
the rule below makes sure it stays that way if a later edition supplies them. Source of the rule: the file's own status column; the
choice to treat every value other than `F` as restricted (a blank or unknown value included) is this project's, privacy by default.

- **Build** (`oah.waterbase.spatial.read_spatial`, `oah.waterbase.storage.write_store`): a site whose status is not exactly `F` (after
  trimming blanks; `f`, `X`, a blank and a missing status all count as restricted) is stored with `lat` and `lon` NULL, whatever the
  source row says. A site that appears in two spatial rows is restricted when either row is. The raw status is still stored in
  `confidentiality`. The provenance `row_counts` carry two new counters: `sites_confidential` (held sites whose status is not `F`) and
  `sites_confidential_with_coordinates_dropped` (of those, how many had coordinates in the source and lost them). No schema change: the
  version stays 3, and an older store without the counters is still read.
- **Read** (`oah.waterbase.store._site`, `located_counts`, `countries_summary`): a restricted site has no location whatever the stored
  values are, so a hand-edited or older store cannot leak one. `site_info` and the `/sites` entries (`latitude` and `longitude` null,
  `location_status: no-location`), the measurement records' site block, the located counts of `/countries` and `/catalog`, and
  `sites_without_location` all follow from it.
- **External context** (`oah.external.sites.SiteLocator`): an entry marked `no-location`, or a Waterbase entry whose `confidentiality` is
  present and not `F`, is refused with HTTP 422 (`no-location`) before any coordinate is used, so weather, discharge and species never
  call a provider for it, in the routes and in the chat tools.
- **Verification on the real store**: `python scripts/verify_waterbase_confidentiality.py` (read-only; path from `oah.paths`, or
  `--store`) asserts that no restricted site has coordinates and prints the counts. Run on 2026-10-03 against the real store: GR 454
  sites (all `F`, 454 with coordinates), IT 4,420 `F` (4,260 with coordinates) and 167 `N` (0 with coordinates), NO 2,451 `F` (2,451 with
  coordinates): `OK: 167 restricted site(s), none with coordinates`. The real store was NOT rebuilt (no schema change, and it already has
  no coordinates on restricted sites); it therefore lacks the two new counters until its next rebuild.
- Tests: `tests/unit/test_waterbase_confidentiality.py` (a synthetic archive whose flagged site HAS coordinates in the source CSV, a
  hand-built store with coordinates on a flagged site, each route and chat tool, the locator).

## Mapping to the project's closed parameter names (one table)

Source of the left columns: the Waterbase file as scanned on 2026-10-02 (codes, labels and unit labels are exactly those found; units
had no variants in the real build). Source of the closed names: `oah.indices.water_parameter_limits.PARAMETER_UNITS`. The table is
`oah.waterbase.mapping.DETERMINANDS`; a test checks that every closed name exists in `PARAMETER_UNITS` and `CLOSED_PARAM_MAPPING`.
A determinand with no exact counterpart stays UNMAPPED: it is listed with its values and compared with nothing.

| Waterbase code | Label | Unit in the file | Closed name (project) | Matrix compared | Treatment |
|---|---|---|---|---|---|
| `EEA_3152-01-0` | pH | `[pH]` | pH | W | none (range 6.5-9.5, as in the index) |
| `EEA_3132-01-2` | Dissolved oxygen | mg/L | Dissolved Oxygen | W | none; Italy: not scored (see below) |
| `EEA_3131-01-9` | Oxygen saturation | % | unmapped | - | no closed name; the national deviation criterion is derived per sample |
| `EEA_3121-01-5` | Water temperature | Cel | Water temperature | W | none; interpretive only in IT and GR, as in the index |
| `EEA_3142-01-6` | Electrical conductivity | uS/cm | Electrical conductivity | W | none |
| `CAS_14797-55-8` | Nitrate | mg{NO3}/L | Nitrate | W | none: same basis (ion), basis label must be `NO3` |
| `CAS_14797-65-0` | Nitrite | mg{NO2}/L | Nitrite | W | none: same basis (ion), basis label must be `NO2` |
| `CAS_14798-03-9` | Ammonium | mg{NH4}/L | Ammonium | W | none: same basis (ion), basis label must be `NH4` |
| `CAS_14265-44-2` | Phosphate | mg{P}/L | unmapped | - | orthophosphate is not total phosphorus |
| `CAS_7723-14-0` | Total phosphorus | mg{P}/L | Total phosphates | W | x PO4/P = 3.0662 (see below) |
| `CAS_18785-72-3` | Sulphate | mg/L | Sulphate | W | none |
| `CAS_16887-00-6` | Chloride | mg/L | unmapped | - | no closed name |
| `CAS_7440-43-9` | Cadmium and its compounds | ug/L | Cadmium dissolved | W-DIS | none |
| `CAS_7439-97-6` | Mercury and its compounds | ug/L | Mercury dissolved | W-DIS | none |
| `CAS_7439-92-1` | Lead and its compounds | ug/L | Lead dissolved | W-DIS | none |
| `CAS_7440-02-0` | Nickel and its compounds | ug/L | Nickel dissolved | W-DIS | none |
| `CAS_7440-38-2` | Arsenic and its compounds | ug/L | Arsenic dissolved | W-DIS | none |
| `CAS_7440-66-6` | Zinc and its compounds | ug/L | Zinc dissolved | W-DIS | none |
| `CAS_7440-50-8` | Copper and its compounds | ug/L | Copper dissolved | W-DIS | none |
| `CAS_7439-89-6` | Iron and its compounds | ug/L | Iron dissolved | W-DIS | none |
| `CAS_7429-90-5` | Aluminium and its compounds | ug/L | Aluminium dissolved | W-DIS | none |

- The matrix rule is conservative. The project's metal names are DISSOLVED concentrations, so only matrix `W-DIS` is compared; a metal
  in matrix `W` (whole water) is listed under the Waterbase label (for example "Lead and its compounds") with status `not-scored` and
  the reason. Every non-metal is compared only in matrix `W`; the same determinand in `W-DIS` (it exists in the data for every
  determinand) is listed, not compared. These are choices of this project, not rules of the data; widen them only with a documented reason.
- Provisional: the choice not to map orthophosphate to "Total phosphates", and the matrix rule above.

### Parameter groups and the measurement-only determinands (package 4)

Every determinand has a `group`, a label of THIS project for display and filtering (not a Waterbase attribute):

| Group | Determinands | Limit regime |
|---|---|---|
| `water-chemistry` | the 21 rows of the table above (the closed parameter names and the listed-but-not-compared ones) | rivers: the existing `surface` regime of the country; lakes: none |
| `solids-turbidity` | Turbidity, Total suspended solids, Secchi depth | NONE in this project |
| `organic-matter` | Total organic carbon (TOC), Dissolved organic carbon (DOC), BOD5, CODCr, Chlorophyll a | NONE in this project |

`solids-turbidity` and `organic-matter` are MEASUREMENT ONLY: the project has no limit regime for them and none is invented (no limit
of the repository, of a directive or of a national table was used or added). Their records carry `limit` null, `limit_regime`
`no-limit-regime`, `status` `not-scored` (the existing status for "shown, not judged"; no new status value was added), the flags
`no-limit-regime` and `measurement-only`, and a `limit_basis` that says so, whatever the water category (a river is not given a
surface limit for them either). `organic-matter` is a label only: no claim beyond the label is made about what the values mean.

**Colloids.** "Colloids" as such are not measured in Waterbase or anywhere in this project. Turbidity and total suspended solids (and,
less directly, Secchi depth) are PROXIES for particulate and colloidal matter; they are not a colloid concentration and must not be
presented as one. A display should say "turbidity and suspended solids" and may add "proxies for particulate/colloidal matter".

Rows of the added determinands. Code, label, unit and matrix are exactly what the disaggregated table holds in the 2026 edition, found
by scanning the table on 2026-10-02 (Italy, Norway and Greece, every category and matrix). The "kept" column is what the build keeps;
the unit must equal the expected label exactly, otherwise the record is `excluded` with the flag `unit-mismatch` (no conversion is
applied; the unit is part of the aggregation key, so two units are never averaged together).

| Waterbase code | Label (as observed) | Group | Unit expected | Matrix kept | Scan rows, kept matrix (IT / NO / EL) | Other matrices seen, dropped |
|---|---|---|---|---|---|---|
| `EEA_3112-01-4` | Turbidity | solids-turbidity | `{NTU}` | `W` | 12,339 / 4,097 / 0 | IT `W-DIS` 1,452 |
| `EEA_31-02-7` | Total suspended solids | solids-turbidity | `mg/L` | `W` | 66,745 / 12,789 / 0 | IT `W-DIS` 400 and `W-SPM` 21,557; EL `W-DIS` 316 |
| `EEA_3111-01-1` | Secchi depth | solids-turbidity | `m` | `W` | 31,657 / 2,606 / 0 | IT `W-DIS` 5; EL `W-DIS` 1,648 (the only Greek rows) |
| `EEA_3133-06-0` | Total organic carbon (TOC) | organic-matter | `mg{C}/L` | `W` | 9,781 / 31,586 / 201 (groundwater, dropped by category) | IT `W-DIS` 1,221; IT `S` (sediment, `%` and `mg/kg`) 179 |
| `EEA_3133-05-9` | Dissolved organic carbon (DOC) | organic-matter | `mg{C}/L` | `W-DIS` ONLY | `W-DIS`: 12,899 / 2,426 / 0 | IT `W` 17,735; NO `W` 3,049 |
| `EEA_3164-01-0` | Chlorophyll a | organic-matter | `ug/L` | `W` | 41,413 / 6,176 / 938 | IT `W-DIS` 812 and `W-SPM` 2,973 |
| `EEA_3133-01-5` | BOD5 | organic-matter | `mg{O2}/L` | `W` | 70,636 / 277 / 0 | IT `W-DIS` 2,542; EL `W-DIS` 1,319 (all Greek BOD5 rows) |
| `EEA_3133-03-7` | CODCr | organic-matter | `mg{O2}/L` | `W` | 51,540 / 125 / 0 | IT `W-DIS` 2,174 |

(The scan counts are all categories, before the river/lake and year filters: a sanity check, not a store figure. They agree with
the figures the maintainer gave for the scan.)

Consequences of the matrix rules in the 2026 data: Greece has only Chlorophyll a (lakes) in the added groups, because its Secchi depth,
suspended solids and BOD5 rows are `W-DIS` only and its TOC rows are groundwater. Italy and Norway have all eight. The rules were set by
the maintainer; they are not a property of the data, and widening them needs a documented reason.

Real store content after the package 4 rebuild (kept annual groups, years 2010-2024): solids-turbidity 13,320 groups (66,154
quantified samples, 18,233 below the quantification limit); organic-matter 31,347 groups (126,009 quantified, 42,361 below); the
water-chemistry figures are unchanged from package 3 (355,112 groups, 1,486,035 quantified, 684,539 below). Sites per country and
determinand in `country_determinands`: Italy turbidity 211, suspended solids 2,822, Secchi depth 165, BOD5 3,362, CODCr 2,548, DOC 737, TOC 196,
chlorophyll a 172; Norway turbidity 524, suspended solids 413, Secchi depth 96, BOD5 35, CODCr 23, DOC 156, TOC 1,536, chlorophyll a 236; Greece
chlorophyll a 53.

## Unit and basis conversions (never silent)

`oah.waterbase.mapping.to_project_unit` is the only conversion. It splits the unit label into a plain unit and a species basis
(`mg{NO3}/L` -> `mg/L`, `NO3`), refuses the value (status `excluded`, flag `unit-mismatch`) when the basis is not the one the table
expects or the unit family is not convertible, converts mass prefixes (`ng`, `ug`, `mg`, `g` per litre; `uS/cm`, `mS/cm`) with the
project's existing `convert_to_unit`, and multiplies by the table's basis factor. The record keeps `original_unit` (what Waterbase
reported). No factor is applied unless the table names it and its source.

- Nitrate, nitrite, ammonium: Waterbase reports the ion (`mg{NO3}/L`, `mg{NO2}/L`, `mg{NH4}/L`). The project's limits that were stated
  as nitrogen (Italy DM 260/2010 LIMeco N-NO3 1.2 and N-NH4 0.06 mg/L; Greece HWQI N-NO3 0.60, N-NH4 0.06 mg/L and N-NO2 8 ug/L) are
  ALREADY converted to the ion in `oah.indices.regimes` (`NO3_PER_N`, `NH4_PER_N`, `NO2_PER_N`, decision of 2026-09-29, atomic weights
  N 14.0067, O 15.999, H 1.008), and the EU values (nitrate 50, nitrite 0.50, ammonium 0.50 mg/L) are ion values already. So no
  conversion is applied here (factor 1.0); the existing machinery is reused, not duplicated. A nitrate reported as `mg{N}/L` would be
  refused, not converted (a test uses one; the real build had none).
- Total phosphorus: Waterbase reports `mg{P}/L`. The project compares total phosphorus as phosphate (decision of 2026-09-29, "Total
  phosphates", national limits written as P multiplied by `PO4_PER_P`). The same factor is applied to the Waterbase value:
  `PO4_PER_P = (30.973762 + 4 x 15.999) / 30.973762 = 3.0662` (standard atomic weights P 30.973762 and O 15.999, the constants already
  in `oah.indices.regimes`). Check used by a test: 100 ug/L as P converted equals the Italian limit in the regime table, and 165 ug/L as P
  equals the Greek one. A phosphorus value labelled `mg{PO4}/L` would be refused, not multiplied twice.
- pH (`[pH]`) and temperature (`Cel`) need no conversion.

## Limits applied

Rivers (category `RW`) use the existing `surface` regime of the site's country: `resolve_limit`, `limit_basis` (with its
verification label), `classify_quantity` / `classify_range_quantity`, `resolve_range_limit`, the `OAH_LIMITS_FILE` overrides. The
quantity compared is the ANNUAL MEAN of the quantified samples (`statistic: mean`); `status` is `within-limit` or `exceeds-limit` by
the same comparison as the sandbox records. No new formula and no CCME index: Waterbase sites have `status: measurements-only`.

- Lakes (`LW`): the project has limit regimes for rivers (surface) and drinking water only, so lake values are shown with
  `limit_regime: no-limit-regime`, no limit and status `not-scored`. River limits are never applied to lakes.
- Italy, dissolved oxygen: the national criterion is the per-sample deviation from oxygen saturation (`|100 - % saturation| <= 20`),
  derived from dissolved oxygen and temperature of the same sample. An annual mean cannot reproduce it, so the record is `not-scored`
  (flag `oxygen-saturation-criterion-not-derivable`). Greece compares dissolved oxygen in mg/L (minimum 6.4).
- Water temperature in IT and GR: `not-scored` (interpretive only), as in the index.
- Cadmium: hardness-dependent, `not-scored` (flag `surface-limit-needs-hardness`).
- Norway has no national table: rivers use the EU surface values or the drinking-water proxies, labelled in `limit_basis`.
- A year in which every quantified sample is below the quantification limit has `n = 0`: `indeterminate`, the limit is shown.

## Limitations (read before showing a number)

1. No median and no individual samples. Monthly (and so annual or periodic) mean, min, max and `n` only. A month holds at least one sample; the
   sampling day is not kept.
2. The annual mean is not the statistic every limit is written for. AA-EQS values are annual averages, but national classification
   criteria (LIMeco, HWQI) are defined on their own aggregation rules that were not reproduced; treat `status` as a reference
   comparison, like every value in the project (`interpretation_notice`), never as a legal exceedance.
3. Values below the quantification limit are excluded from the mean, which biases the mean upward when many samples are below it
   (31 % of the kept rows in the real build were below LOQ). The record says so (`below-loq-excluded-from-mean`, `n_below_loq`).
4. The arithmetic mean of pH is not rigorous (pH is logarithmic); `arithmetic-mean-of-ph` is set on every pH record. `min` and `max` are exact.
5. Dissolved metals are compared with limits for dissolved or bioavailable concentrations as the sandbox is (`docs/limits_verification.md`);
   Waterbase `W-DIS` is dissolved water, which is the closest match, not proof of the bioavailable fraction.
6. Records flagged `U` or `V` by Waterbase are in the mean and counted (`n_lower_reliability`).
7. The shown "latest year" differs by country (real build: GR 2021, IT and NO 2024 for this slice), and the last year of a country can
   be partial. The chat answers use the `latest_year` of `/countries`.
   Since package 5 the last month with data is known too (`country_ranges`, `data_range` in `/countries`); a period beyond it is reported by
   the period comparison as `period-outside-data` and is never shifted or filled (`docs/period_change.md`).
8. Sites with `confidentiality` other than `F` (for example `N`) or no coordinates are listed with `location_status: no-location`; their
   coordinates are never stored, shown or sent to an external provider (next section).
9. "Almyros" in Waterbase (Crete) is a groundwater body without coordinates and is NOT the sandbox river `Loc-Almyros`; groundwater is
   excluded from the store and the two are never equated.
10. Bathing water and microbiology are not part of this store; the EEA bathing-water CLASSIFICATION is a separate store (`docs/bathing_water_store.md`).
11. The added groups have no limit regime: a value of turbidity, suspended solids, Secchi depth, organic carbon, BOD5, CODCr or chlorophyll a is
    shown, never judged. Colloids as such are not measured (proxies only, above).
12. The store is a snapshot of one published edition; `data_freshness` is `snapshot` dated by the build, the edition is in `waterbase.edition`.

## Rebuild

Prerequisites: the archive in `<data dir>/data/waterbase/2026/`, 7-Zip, about 1.7 GB of scratch space under `<data dir>/waterbase/work/`
(the inner archives are copied there and removed afterwards) and roughly 2 GB of memory (355,000 aggregated groups).

```
python scripts/build_waterbase_store.py --dry-run     # shows the resolved archive, store and 7-Zip
python scripts/build_waterbase_store.py               # builds the store
```

Options: `--archive`, `--output` (absolute external paths), `--min-year` (default 2010), `--compute-sha256`. 7-Zip is found through
`OAH_SEVENZIP_PATH` (absolute path to the executable), then `7z` on the PATH, then the standard Windows install folder. Settings
(never committed; `.env.example` lists them): `OAH_WATERBASE_STORE` (store path override) and `OAH_SEVENZIP_PATH`. Real build on
2026-10-02 (arm64 laptop, annual store): 284 s, 77.2 MB store, 96,597,294 rows scanned, 20,079,488 of the four countries, 1,486,035 quantified and
684,539 below-LOQ rows kept, 355,112 annual groups, 7,476 sites (GR 454, IT 4,580, NO 2,442; 327 without coordinates, all Italian).
Rebuild after package 4 (schema version 2, 29 determinands, same day): 186 s, 86.6 MB (86,597,632 bytes), the same 96,597,294 rows
scanned and 20,079,488 of the four countries; kept 1,678,198 quantified and 745,133 below-LOQ rows in 399,779 annual groups, 7,492
sites (GR 454, IT 4,587, NO 2,451; 327 without coordinates, all Italian); dropped: other categories 7,456,768, other determinands
9,861,280, matrices outside the determinand's rule 50,227, before 2010 282,843, missing-value statuses 5,039. Years 2010-2024 (GR 2012-2021).
Rebuild after package 5 (schema version 3, monthly, same day): 201 s, 167.2 MB (167,247,872 bytes; about 1.9 times the annual store), the same
96,597,294 rows scanned and 20,079,488 of the four countries, the same 1,678,198 quantified and 745,133 below-LOQ rows kept (so the filters are
unchanged), in **2,151,267 monthly groups** (399,779 annual groups, as before), 7,492 sites (GR 454, IT 4,587, NO 2,451; 327 without coordinates).
Months with data (`country_ranges`): GR 2012-01 to 2021-12, IT 2010-01 to 2024-12, NO 2010-01 to 2024-12. A country-wide period comparison of one
parameter reads about 25,000 monthly rows in about 0.6 s (Italy, total phosphates, two periods of two years).
Without the store every route answers as before and reports `waterbase.state: not-built`; a store of schema version 1 or 2 reports
`rebuild-required`; another version or a damaged file reports `unreadable`.

## Tests

`tests/unit/test_waterbase_build.py`, `test_waterbase_reader.py`, `test_waterbase_mapping.py`, `test_waterbase_measurements.py`,
`test_waterbase_api.py` and `test_waterbase_groups.py` (the added groups, the group filter, the version 1 store), and for the monthly
resolution `test_period_change_api.py`, `test_period_change_adapters.py` and `test_period_change_strings.py` (months, sums, old stores, bounds, query plan) use tiny SYNTHETIC archives built in temporary directories (`tests/unit/waterbase_fixtures.py`): the real
layout (outer ZIP with a top-level folder, inner deflate ZIPs, BOM, CRLF), `EL` code, W and W-DIS, below-LOQ flags, missing-value
statuses, unit labels with a basis, lakes, a groundwater row, a site without coordinates, a quoted multi-line field. The values are
invented for the tests and are not measurements. No test uses the network or the 4.5 GB archive; the 7-Zip streaming test is skipped
where 7-Zip is not installed.

## Plausibility bound on pH (2026-10-04)

A live check of the Italian pH data showed values that cannot be pH readings. The build now drops an observed pH value
(`EEA_3152-01-0`) outside 0 to 14 and counts it in `dropped_implausible_value` (stored in `row_counts`); the bound is
listed in the provenance `filters` as `plausible_ranges`. Why 0 to 14: it is the extent of the pH scale for dilute
aqueous solutions, a property of the quantity itself and not a judgement about typical river water, so no value inside
the range is touched, however unusual. No other determinand is bounded (the project has no source for such limits).
Source of the rule: the definition of the pH scale (no dataset value is involved). Provisional in one respect: values
inside 0 to 14 that are still wrong (for example a unit slip) are not detected. The change takes effect only when the
store is rebuilt; an older store keeps its old counters. Tests: `tests/unit/test_waterbase_build.py`.
