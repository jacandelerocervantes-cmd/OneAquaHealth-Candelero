# Index catalogue for the web app sidebar

Status: 2026-10-02, draft for approval. Built from what exists in `src/oah/`, the public sandbox (queried by GET on
2026-10-02) and public sources found by web research the same day. App definition: `docs/web_app_chat_by_country.md`.
Nothing here invents a code, formula or source. "Unverified" marks claims the researcher inferred or could not open;
re-check them in the original source before relying on them.

## 1. Layout idea

ChatGPT or Claude style shell. The sidebar lists indices where those apps list chat sessions; the user and a settings
button sit at the bottom; the country selector stays in the top bar. Choosing an index sets the chat context. Each item
carries a badge: real, synthetic, or unavailable.

## 2. Corrections to earlier documents

- The sandbox now holds **619 Observations and 25 Locations** (older docs say about 415 and 23). About 59 carry a
  `meta.tag` of `simulated` or `demo`, and 161 have no profile; 51 use third-party profiles (StreamPulse forecast,
  citizen-science). These are not official data and must be filtered out by tag and profile before any index or QC count.
- Microbiology: one Observation exists (`coliforms`, 2400 CFU/100 mL, Location 590, 2026-09-23) but it is tagged
  `simulated` and `demo` ("No real sample was taken"). It is not usable as data.
- Biodiversity and biotic: one untrusted third-party Observation created 2026-10-02 (Ephemeroptera note, a `bmwp-score` of 10
  under a non-OAH code system, no location, no tag). Not citable.
- Possible data defect: Almyros total phosphates 2018 has maximum 0.006 below average 0.03 mg/L. Whether the basis is
  phosphate or phosphorus is unconfirmed.

## 3. Catalogue with data and sources

| # | Item | Real data we hold or can reach | Source and licence | Status |
|---|---|---|---|---|
| 1 | Water quality (CCME WQI) | Sandbox, Almyros (Crete): 131 Observations, 2013-2015 and 2018-2020 (annual aggregates), plus a few 2024-25 temperature or conductivity records. Giofyros reaches: temperature or conductivity only. | HL7 Europe OneAquaHealth sandbox; no licence text found for the sandbox or the IG. Limits: Directive (EU) 2020/2184, Directive 2013/39/EU, national regimes (`docs/limits_verification.md`). | Ready for Almyros |
| 2 | Water parameters | Same 131 Observations: ammonium, nitrate, nitrite, total phosphates (2018-2020 only), sulphate, dissolved oxygen, pH, conductivity, water temperature, dissolved metals; min, max, average, median per record. | As above. | Needs the per-site measurements route |
| 2b | More sites, more years | EEA Waterbase Water Quality ICM 2026 (1900-2025, published 7 Jul 2026): **ingested slice** (2026-10-02, `docs/waterbase_store.md`): rivers and lakes of GR (EL in the file), IT and NO, 21 determinands (nutrients, oxygen, pH, conductivity, temperature, sulphate, chloride, nine metals), matrices W and W-DIS, annual aggregates (n, mean, min, max; no median) for sampling years 2010 to 2024 (GR to 2021); 7,476 sites (GR 454, IT 4,580, NO 2,442). Measurements only, no CCME index; rivers compared with the surface regime, lakes shown without a limit regime; groundwater, coastal and transitional waters, the 2024 edition and years before 2010 are not ingested. Discodata `WISE_SOE` is the 2015 schema (EL and IT, years 2000-2012), not used. | EEA, CC BY 4.0 (EEA legal notice; per-dataset page does not restate it). https://www.eea.europa.eu/data-and-maps/data/waterbase-water-quality-icm-2 ; `SOURCES.yaml` third-party notices | Ingested slice (rebuild with `scripts/build_waterbase_store.py`); the rest optional |
| 2c | Norway | Vannmiljo: physico-chemical, biological. No documented REST data API found; export by web UI, WMS and Geonorge shapefile. | Miljodirektoratet, NLOD 1.0. https://data.norge.no/en/datasets/49214b87-8970-392e-b926-ff603f2cdb76/miljotilstand-i-vann ; codes https://vannmiljokoder.miljodirektoratet.no | Optional |
| 3 | Oxygen saturation | Sub-view of item 1 (deviation from saturation, Italy regime). | Code: `src/oah/indices/oxygen.py`; DM 260/2010 | Ready as a sub-view |
| 4 | Data quality | Computed by `/qc/report`. | n/a | Ready; must exclude demo, simulated and third-party records |
| 2e | Period comparison (how much has X changed between two periods) | Over the data of rows 1, 2b and 2d (not a new dataset): `GET /sites/{id}/change`, `GET /countries/{code}/change`, chat tool `compare_periods`; the Waterbase store is now MONTHLY (schema 3), so any period of months inside 2010-2024 (Greece to 2021) can be compared; the sandbox only as annual aggregates (flag `annual-only`). Deterministic arithmetic (n, mean = sum / n, min, max, below LOQ, absolute and relative change, direction), a country uses only the sites with data in both periods, each period mean is shown against the project limit where one exists (rivers by the country regime, drinking regime, `OAH_LIMITS_FILE` overrides; lakes and the measurement-only groups have none, said plainly), and a period beyond the data is reported with the `data_range`, never shifted. A screening aid, not a compliance assessment. `docs/period_change.md` | Project code over EEA CC BY 4.0 and sandbox data | Built; no new source and no new limit |
| 2d | Solids and turbidity ("colloid-related"), organic matter | EEA Waterbase 2026, ingested with item 2b (package 4, `docs/waterbase_store.md`): group `solids-turbidity` (Turbidity `{NTU}`, Total suspended solids mg/L, Secchi depth m) and group `organic-matter` (Total organic carbon (TOC) and Dissolved organic carbon (DOC) mg{C}/L, BOD5 and CODCr mg{O2}/L, Chlorophyll a ug/L), annual aggregates (n, mean, min, max), rivers and lakes of IT and NO (GR: chlorophyll a in lakes only, by the matrix rules), 2010-2024. **Colloids as such are not measured**: turbidity and suspended solids are proxies for particulate or colloidal matter. **Measurement only**: the project has no limit regime for these parameters (`limit` null, `limit_regime` `no-limit-regime`, `status` `not-scored`); `organic-matter` is a label only. Reachable with `group=solids-turbidity` or `group=organic-matter` on `GET /sites/{id}/measurements`. | EEA, CC BY 4.0 (as 2b) | Ingested (rebuild with `scripts/build_waterbase_store.py`); no limits, no index |
| 5 | Microbiology (E. coli, intestinal enterococci) | **Concentrations ingested for GR and IT, with NO thresholds; plus the per-season classification.** (a) CONCENTRATIONS (package 6, `docs/bathing_samples_store.md`): the EEA Discodata table `[WISE_BWD].[latest].[timeseries_MonitoringResult]` (Bathing Water Directive monitoring results), read through the public read-only SQL endpoint with keyset pages: 754,451 individual samples, Greece (identifier prefix EL, stored GR) 208,176 samples at 2,419 bathing waters, seasons 2008-2024, Italy 546,275 samples at 5,930 bathing waters, seasons 2010-2024, Norway none (it is not in the Directive data). Each sample keeps the bathing water, the sample date, the season, both values (cfu/100ml, verified from the table metadata), both EEA statuses and the sample status; values flagged below the limit of detection, missing or of an unrecognised status are labelled and counted apart, never turned into plain numbers. No limit, threshold or classification rule exists in the project for these bacteria and none is applied: MEASUREMENT ONLY. Routes: `GET /bathing-waters/{bw_id}/samples` (samples and a summary with min, max, mean and exact median), `GET /bathing-waters/{bw_id}/samples/change` and `GET /bathing-waters/samples/change` (period comparison of one bathing water or, over paired bathing waters, of a country), the `samples` link of `GET /bathing-waters/{bw_id}`, the `samples` block of `/countries`, chat tools `get_bathing_samples` and `compare_bathing_concentrations`, chat index `microbiology`. Seasons stop at 2024 in the table (the classification has 2025). (b) CLASSIFICATION (package 4, `docs/bathing_water_store.md`): EEA Bathing Water Directive status of bathing water, 2025 v.1.0, 1990-2025: 8,650 bathing waters (GR 2,426, IT 6,224), 251,550 classification rows (the file's class string such as `1 - Excellent`, monitoring calendar, management status, coordinates where present); a classification, not a concentration; routes `GET /bathing-waters`, `GET /bathing-waters/{bw_id}`, `GET /bathing-waters/change`, tools `list_bathing_waters`, `get_bathing_water_history`, `compare_bathing_seasons`. The two datasets share the bathing-water identifier (8,309 of the 8,349 sampled identifiers are in the classification store). Not in the sandbox (one simulated record only). Reference limits (NOT applied, unverified for bathing water): Directive (EU) 2020/2184 Annex I Part A (E. coli 0 and enterococci 0 per 100 mL) concerns drinking water; WHO recreational water guidelines (2021). | EEA, EEA CC BY 4.0 (EEA legal notice; the dataset pages do not restate it). Concentrations: https://discodata.eea.europa.eu/ (table description: "Bathing water reporting table: Data set with the monitoring results on intestinal Enterococci and Escherichia coli."). Classification: https://www.eea.europa.eu/data-and-maps/data/bathing-water-directive-status-of-bathing-water-12 . Italy mirror (community, not official): https://github.com/dataciviclab/open-ispra | Concentrations ingested as individual samples without thresholds (rebuild with `scripts/build_bathing_samples_store.py`); classification ingested separately (rebuild with `scripts/build_bathing_water_store.py`) |
| 5b | Protozoa (Giardia, Cryptosporidium) | **No open EU occurrence dataset found.** Only journal papers. Directive 2020/2184 has no mandatory protozoa parameter (researcher's background knowledge, unverified). WHO gives qualitative guidance, no numeric value. | n/a | Not available as measured data; if shown at all, label as a model or proxy, never measured |
| 6 | Biodiversity (Shannon, Simpson, Pielou, Chao1) | No real counts in the sandbox. Open taxon records exist for Norway: Vannmiljo species occurrences on GBIF (benthic fauna), v1.137 published 2025-12-01. | GBIF, CC BY 4.0. https://www.gbif.org/dataset/46293000-ddd1-4c32-a1e7-b5e793223ecd | Synthetic only in the demo; GBIF Norway slice is optional |
| 7 | Biotic quality (BMWP, ASPT, EPT) | None. Waterbase Biology holds EQRs and status classes per quality element (not taxa lists), 2012-2024. | EEA (licence not stated on the page; CC BY 4.0 presumed). https://www.eea.europa.eu/en/datahub/datahubitem-view/7bd881f0-59ca-4f0a-a43c-7e0cd0c66d6c . Tolerance tables: UK Environment Agency report R8161 (generic BMWP, licence unverified); IBMWP and HESY-2 tables not openly licensed. Intercalibration: Decision (EU) 2024/721. | Unavailable until a tolerance table with a verified licence is chosen |
| 8 | Air quality (Benevento) | Sandbox: 103 Observations, 12 stations, 2018 annual aggregates: NO2, O3, PM10, PM2.5, benzene. Beyond: EEA Air Quality Download Service (e-Reporting, 2013 to present; NO2, SO2, O3, PM10, PM2.5; REST API, Parquet). | EEA, CC BY 4.0 presumed. https://eeadmz1-downloads-webapp.azurewebsites.net/ . Limits: Directive 2008/50/EC and Directive (EU) 2024/2881 (PM2.5 10, PM10 20, NO2 20 ug/m3 annual, by 2030; verified in search results). Older values from the researcher's memory are unverified. | Possible new item: a plain table of annual means against limit values, not an index |
| 9 | Population health | Sandbox: 141 aggregated percentages, Oslo (Loc-Nordre-Aker) 81 and Benevento 60, all dated 2024-01-01. Context: ECDC Surveillance Atlas (giardiasis, cryptosporidiosis, STEC), national level, manual CSV, annual. | Sandbox: licence not stated. ECDC: reuse allowed with the credit line "Data provided by ECDC based on data reported by EU/EEA Member States." https://atlas.ecdc.europa.eu/public/index.aspx | Optional; group-level, cannot be tied to Almyros |
| 10 | Citizen science, review queue, river risk | Synthetic by design (generated in this project). | Project code; method sources in `SOURCES.yaml` | Ready, labelled synthetic |
| 11 | Weather context (monthly precipitation sum and mean temperature) -- EXTERNAL, not an index | Around any site or bathing water, 1940 to about 5 days ago: `GET /sites/{site_id}/weather`, chat tool `get_weather_context` (backend package 7, `docs/external_context.md`). ERA5 reanalysis for a 0.25 degree grid cell (about 25 km), fetched by the backend only, cached and budgeted; a MODELLED value, never a measurement at the site, never evidence of causation. | Open-Meteo Historical Weather API: CC BY 4.0 for the API data, free for non-commercial use (600 calls per minute, 10,000 per day), required link text "Weather data by Open-Meteo.com"; ERA5 credit as the Open-Meteo page gives it (C3S licence wording unverified). | Context item, labelled external and modelled; origin `external-open-meteo` |
| 12 | River discharge context (monthly mean) -- EXTERNAL | Around water-quality sites: `GET /sites/{site_id}/discharge`, chat tool `get_river_discharge_context`. GloFAS v4 consolidated, 0.05 degrees (about 5 km), daily from 1984; the nearest river cell may be another river than the site's (the distance is given); a MODELLED value, not a gauge reading. The provider documents the history to July 2022; the data end is read from the answer. | Open-Meteo Flood API (CC BY 4.0 for the API data) with GloFAS (Copernicus Emergency Management Service); the credit wording of the CEMS licence could NOT be read (UNVERIFIED, shown as such). | Context item, labelled external and modelled; origin `external-open-meteo` |
| 13 | Species records near a site (freshwater macroinvertebrate groups) -- EXTERNAL | Around water-quality sites: `GET /sites/{site_id}/species`, chat tool `get_species_nearby`. GBIF occurrence records in a 10 km square for seven discovered taxon groups (Ephemeroptera, Plecoptera, Trichoptera, Odonata, Chironomidae, Gammaridae, Unionida), with the licence, dataset and citation of each record and GBIF's own counts per group. OPPORTUNISTIC records, not monitoring; not an index and not an inventory (no BMWP, EPT score or diversity measure is computed from them). | GBIF, per record CC0 1.0, CC BY 4.0 or CC BY-NC 4.0 (non-commercial only); the dataset citation is passed on as GBIF gives it. | Context item, labelled external and opportunistic; origin `external-gbif` |

## 4. What is not available openly (or not verified)

- Measured Giardia and Cryptosporidium in EU surface or drinking water as open data.
- Local (sub-national) waterborne-disease incidence; the ECDC atlas is national.
- A documented REST data API for Vannmiljo or for Greek national river data (Greek data is "on request").
- Open machine-readable HESY-2 or IBMWP score tables; open raw taxon abundances for GR and IT rivers.
- Licence confirmation for the WHO documents (likely CC BY-NC-SA 3.0 IGO), ARPAC Benevento data, and the Greek and Italian portals.
- Per-sample bathing-water results for Norway (it has none in the Bathing Water Directive data) and for the 2025 season (the Discodata table ends at the 2024 season in the build of 2026-10-03).
- Any limit or threshold for E. coli and intestinal enterococci in bathing water: none is in the project, none is applied, and the samples are shown as measurements only.

## 5. Proposed scope for the demo

- **Must (M1):** 1 Water quality, 2 Water parameters, 4 Data quality (sandbox only, filtered to official records).
- **Should:** 5 Microbiology from the EEA bathing-water data (done: the classification on 2026-10-02 for GR and IT, season-to-season counts of class transitions since package 5, and since 2026-10-03 the individual E. coli and
  enterococci concentrations of GR and IT from Discodata, as measurements without thresholds; the data have no Norwegian row), 10 Citizen science (synthetic).
- **Could:** 8 Air quality table, 6 Biodiversity (synthetic), 9 Population health.
- **Shown as unavailable with the reason:** 5b Protozoa, 7 Biotic quality.

## 6. Attributions the app must show

EEA (CC BY 4.0), Miljodirektoratet (NLOD), GBIF dataset citation, ECDC credit line, ISPRA where used, and the sandbox
origin. Synthetic and real data are always labelled separately. External context (items 11 to 13) adds: the link text
"Weather data by Open-Meteo.com" (linking to the Open-Meteo site) next to any weather or discharge value, the ERA5 and
GloFAS credits (`attribution` of each response; the GloFAS wording is unverified), and for every GBIF record its own
licence, dataset and citation. External context is labelled external and modelled or opportunistic, never as the site's
own data.

## 7. Decisions needed

1. Approve the list and the M1 scope.
2. Add Microbiology (EEA bathing water) as a real item? Done as a classification-only item (`docs/bathing_water_store.md`); no
   FHIR codes were invented for it, since it does not come from the sandbox.
3. Ingest a country-bounded Waterbase slice for more water sites, or keep Almyros only for the demo.
4. First backend task: per-site measurements route (confirm).

## 8. Availability per country (the route behind the sidebar)

`GET /catalog?country=XX` (2026-10-03) is the authoritative list of the sidebar families and indices for a country: Water (water quality, water parameters, solids
and turbidity, organic matter), Microbiology (bathing classes, E. coli and enterococci), Context (weather, river discharge, species nearby), Data (data quality)
and Synthetic labs (citizen science, review queue, river risk). Every index carries `applies` and, when it does not, a reason, derived from the data the service really
holds (never from a country list), so the web app hides only what the backend marks as not applicable. Biotic quality (row 7), protozoa (5b), air quality (8) and
population health (9) are never returned. The rules, the reason codes and the decisions are in `docs/api_routes.md` (section `GET /catalog`).
