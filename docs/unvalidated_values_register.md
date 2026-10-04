# Register of unvalidated, synthetic, assumed and mock values

Status: 2026-09-26, produced by auditing the code, the tests and the real sandbox snapshot. It lists every
value in this project that is **synthetic, mocked, assumed, chosen by convention, calculated from
non-real inputs, or known to be biased**, and says which real data would validate it. Keep it current: when a
constant, threshold, limit, simulator setting or mapping is added or changed, add or update its row here
(recommended as a rule for agents; it is not yet written into `AGENTS.md`, which is the team's file to change).

**Update 2026-09-29.** Sections 3, 3a and 4 below are the 2026-09-26/27 snapshot. Sections 10 to 17 supersede
their rows for the limits that have since been sourced or changed (pH range, copper, the Italian and Greek
national regimes, phosphate and nitrogen bases, oxygen as percent saturation, temperature as interpretive) and
for the statements marked "no citation". Where a section 3 row disagrees with sections 10 to 17, sections 10 to 17
and `docs/math_registry.md` are current. Each evaluated site now also reports the basis of every limit it used
(`limit_basis`: legal, legal indicator, national, proxy or convention).

Scope note: it is an audit of the repository, not a scientific review. Where a statement below says "not
verified", nobody has checked the number against its primary source; it does not mean the number is wrong.

## How to read it

| Kind | Meaning |
| --- | --- |
| **SYNTHETIC** | Produced by the simulator or a constructed scenario; describes the simulator, never the real world |
| **PROXY** | A real-world number borrowed from another context (for example a drinking-water limit used as a surface-water objective) |
| **CONVENTION** | Chosen by the project, with no source and no calibration |
| **PLACEHOLDER** | A stand-in (fake domain, demo topology, fallback value) |
| **DATA-QUALITY** | The real sandbox data itself is inconsistent, scaled wrongly, tiny or unrepresentative |
| **UNVERIFIED** | Believed correct but not checked against the primary source or a real run |
| **NOT-RUN** | Implemented and tested on synthetic inputs, never executed on real data |
| **DEFECT** | A confirmed error in the current calculation, not yet fixed |

Severity: **High** can change a headline result or mislead a reader; **Medium** changes secondary outputs;
**Low** is cosmetic or easily corrected. "Labelled?" says whether the output already carries a synthetic,
provisional or low-confidence label that a reader would see.

## 1. Headline results that must not be quoted as real

| Result | Where | Why it is not real | Labelled? |
| --- | --- | --- | --- |
| CCME WQI per site (Loc-Almyros 69.46 with veto, Giofyros 100.0 twice) | `/sites`, `/indices`, indicators Bundle | Objective limits are proxies (section 3); Almyros's failure comes from a drinking-water-type conductivity limit applied to a brackish coastal stream (18.4 and 12.2 mS/cm), an artefact of the proxy, not evidence of pollution; most Almyros data excluded as inconsistent (85 of 97 scorable Observations); Giofyros has fewer than 4 parameters | Yes: `low_confidence` on all three |
| Observer reliability, accuracy, ECE, coverage, singleton rates | `/reliability/campaign`, docs tables | Computed only on the simulator | Yes: `origin: synthetic`, `tag: synthetic` |
| Conformal sets and the human-review queue | `/review/queue` | Sets come from simulated posteriors; queue holds simulated specimens | Yes: synthetic tag |
| Propagated river risk | `/risk/{site_id}` | Demo topology and decay are invented | Yes: `origin: synthetic` |
| Indicators exported as FHIR Observations | `scripts/export_indicators.py`, `POST /fhir/export/indicators` | They carry the WQI above; codes are provisional | Partly: provisional CodeSystem and `low_confidence` note; the Observation status is `final` |
| LLM explanations | `/explain/*` | One real run (4 calls, 2026-09-26): all grounded, but a human read found a misread factor (6.4x for an excursion of 6.36), an exceedance called "possibly real" although the limit is a proxy, and one claim not in the evidence; a second run after the fixes removed the misreadings but the check flagged 2 of 4 outputs for harmless enumerators (one now exempt); grounding rates are for authored cases | Grounding flags shown; no "unverified" banner |

## 2. Synthetic data and simulator settings (SYNTHETIC)

| Item | Value / behaviour | Where | Severity | What real data would validate it |
| --- | --- | --- | --- | --- |
| Observer skill, weak observers | uniform 0.30-0.55, `max(1, n // 4)` observers | `synthetic/campaign.py` | High | Real volunteer identification records checked by experts |
| Observer skill, standard | uniform 0.55-0.95 | same | High | same |
| Adversarial observer | one observer, skill uniform 0.70-0.90, systematically swaps families 0 and 1 | same | Medium | Evidence that real annotators are systematically adversarial (likely not) |
| Confusion structure | symmetric: all errors spread uniformly over the other classes | same | High | Real confusion matrices (real errors concentrate on look-alike taxa) |
| Class priors | uniform (each family equally likely) | same | High | Real taxa frequencies per site and season (real ones are highly imbalanced) |
| Taxa families | Baetidae, Heptageniidae, Hydropsychidae, Perlidae | `DEFAULT_TAXA_FAMILIES` | Medium | The taxa list actually used by the OAH protocols |
| Campaign size regimes | 15 or 70 specimens per site, 3 or 5 annotators, 8 observers | `scripts/eval_*.py`, tests | Medium | Real campaign sizes |
| Site ids | reuse real Location ids (`Loc-Almyros`, `Loc-Benevento`, `Loc-OS`) as labels only | `api/routes/synthetic.py` `SITE_LABELS` | Low | n/a (labels) |
| Dawid-Skene vs majority vote figures (0.63 vs 0.78 poor regime, etc.) | seeds 42-61 and 300-339 | `docs/math_registry.md`, `scripts/eval_reliability.py` | High | Real annotations with expert ground truth |
| Threshold 50 annotations per observer for full Dawid-Skene | derived on seeds 100-109 | `recommend_method` | High | The crossover on real annotator data |
| One-coin advantage (calibration, workload, accuracy) | simulator, symmetric errors favour the model | `oah/reliability/one_coin.py`, docs | High | Real data with look-alike-taxa confusions |
| Conformal coverage, set sizes, class-conditional evidence | simulator; "true" labels are simulator ground truth | `oah/uncertainty/conformal.py`, docs | High | Expert-verified calibration labels |
| Conformal targets alpha 0.05 / 0.10 / 0.20; calibration seeds 1000-1029, test 2000-2029 | conventional error levels | `scripts/eval_conformal.py` | Low | A stakeholder decision on acceptable error rates |
| Review queue specimens, reviewer ids, decisions, audit trail content | simulated | `oah/review`, `oah/store` | Medium | Real review sessions (the append-only audit mechanism itself is real) |
| Synthetic FHIR: taxa CodeSystem, observer identifiers, batch Provenance | project-defined, fake domain | `synthetic/fhir.py` | Low | n/a |
| Censored-data simulations | lognormal(0,1) truth, chosen detection limits, n = 300 | `tests/unit/test_censored_stats.py` | Medium | Real left-censored chemistry with known values |
| Grounding harness cases and rates | written by the authors; curated set tuned while inspecting failures | `oah/explain/grounding_cases.py` | High | Real LLM outputs with human-labelled correct and incorrect numbers |
| Analytical risk validation parameters | illustrative u, D and k, not measured | `tests/unit/test_risk_analytical.py` | Low | Measured velocity, dispersion and decay for a real reach |

## 3. Objective limits used by the CCME WQI (PROXY, UNVERIFIED)

Source in code: `CLOSED_PARAM_MAPPING` in `oah/indices/apply_to_sandbox.py`. The module docstring says the limits are
"derived from EU Environmental Quality Standards (Directive 2008/105/EC, 2013/39/EU) and the Drinking Water Directive
((EU) 2020/2184) as documented environmental proxies". **None of the numbers below has an individual citation** in the
code or the docs, and none was checked against the Directive text in this audit. Drinking-water values are not surface-water
ecological objectives, and real objectives differ by site, water-body type and season.

| Parameter | Limit | Direction | Unit assumed | Unit seen in sandbox | Note |
| --- | --- | --- | --- | --- | --- |
| Aluminium dissolved | 200 | max | ug/L | ug/L | no citation |
| Ammonium | 0.5 | max | mg/L | mg/L | no citation |
| Arsenic dissolved | 10 | max | ug/L | ug/L | no citation |
| Cadmium dissolved | 5 | max | ug/L | ug/L | no citation |
| Copper dissolved | 2000 (corrected 2026-09-29 from 20; Directive (EU) 2020/2184 Annex I Part B "Copper 2,0 mg/l") | max | ug/L | ug/L | sourced, auditor-approved |
| Dissolved oxygen | 6 | **min** | mg/L | mg/L | direction now handled; number has no citation |
| Conductivity (`conductivity`) | 2500 | max | uS/cm | mS/cm (converted x1000) | Almyros 18.4 and 12.2 mS/cm exceed it 7.4x and 4.9x; a coastal brackish site is naturally saline, so this limit is not meaningful there |
| Electrical conductivity (`electrical-conductivity`) | 2500 | max | uS/cm | uS/cm | ok |
| Iron dissolved | 200 | max | ug/L | ug/L | no citation |
| Lead dissolved | 10 | max | ug/L | ug/L | no citation |
| Mercury dissolved | 1 | max | ug/L | ug/L | no citation |
| Nickel dissolved | 20 | max | ug/L | ug/L | no citation |
| Nitrate | 50 | max | mg/L | mg/L | no citation |
| Nitrite | 0.5 | max | mg/L | mg/L | no citation |
| Sulphate | 250 | max | mg/L | mg/L | no citation |
| Total phosphates | 0.1 | max | mg/L | mg/L | no citation; not a drinking-water figure as far as this audit knows |
| Water temperature | 25 | max | Cel | Cel | no citation; a fixed number ignores site and season |
| Zinc dissolved | 100 | max | ug/L | ug/L | no citation |
| pH | 8.5 (superseded 2026-09-29 by range 6.5-9.5 in `TWO_SIDED_LIMITS`, auditor-signed) | max only (legacy; scoring now two-sided) | pH | pH / none | legacy 8.5 unsourced and unused for scoring; acidic pH now fails |

**Fixed 2026-09-26 (was a High DEFECT): units.** The code used to compare the raw number against the limit and never check
the unit; the generic `conductivity` code is reported in mS/cm in 4 Observations, so 18.4 mS/cm was compared as 18.4 against
2500 and always passed (Almyros scored 100.0 instead of 69.46). Now every limit has an explicit unit (`PARAMETER_UNITS`), the
observed value is converted (`convert_to_unit`: ng/L, ug/L, mg/L, g/L; uS/cm, mS/cm), and an unknown, missing or incompatible
unit is skipped and counted in `skipped_unit_mismatch_observations` (and lowers the site's confidence). Only pH may lack a unit code.
The conversion factors are standard SI prefixes; they were not checked against a unit library.

Other consequences: every limit is applied to every site regardless of water-body type; the sandbox has no site-specific
objectives; the choice of which parameters count is fixed by the mapping (metals reported as dissolved only).

### 3a. Threshold-registry sourcing progress (2026-09-27, NotebookLM extraction over the primary directive texts, human-supplied)

The user ran a citation-grade extraction (verbatim quote + Annex/Article + Official Journal page for
every value, `NOT FOUND` stated explicitly with a reason where a directive sets no EU-wide number)
over Directive (EU) 2020/2184, Directive 2013/39/EU, Directive 2006/118/EC and Directive 2000/60/EC
for the parameters in the table above plus the limit-of-quantification (LOQ) rule. This is the
threshold-registry design's raw material (see the handoff entries on the registry design); **the
code (`CLOSED_PARAM_MAPPING`) was NOT changed** -- per this project's own rule, the registry is
populated only once the full table is complete and an auditor signs each entry (`verified_by`), not
piecemeal by whichever agent reads a partial extraction. What follows is what the extraction
confirmed or newly revealed about the existing PROXY numbers above:

| Parameter | Code's current value | What the sourced extraction found | Verdict |
| --- | --- | --- | --- |
| Nitrate | 50 mg/L, max | `Directive (EU) 2020/2184` Annex I Part B, L 435/36: "Nitrate 50 mg/l" (drinking water; joint condition with nitrite: `[nitrate]/50 + [nitrite]/3 <= 1`); also `Directive 2006/118/EC` Annex I, L 372/25: "Nitrates 50 mg/l" (groundwater quality standard) | Matches two independent EU sources exactly. Citation now exists; still not a surface-water ecological objective (it is a drinking-water and groundwater standard used as a proxy) |
| Nitrite | 0.5 mg/L, max | `Directive (EU) 2020/2184` Annex I Part B, L 435/36: "Nitrite 0,50 mg/l" (same joint condition as nitrate); a second, stricter value "0,10 mg/l... ex water treatment works" also exists in the same Annex for a different compliance point | Matches. Note the extraction surfaced a second, lower value (0.10 mg/L) for a different measurement point in the same directive -- not yet reconciled with which point the sandbox's own measurements correspond to |
| Sulphate | 250 mg/L, max | `Directive (EU) 2020/2184` Annex I Part C, L 435/40: "Sulphate 250 mg/l" (indicator parameter, "the water should not be corrosive"); `Directive 2006/118/EC` Annex II Part B: NOT FOUND (Member States "have to consider" a threshold, no EU-wide number) | Matches the drinking-water figure exactly. Still a drinking-water indicator parameter used as an ecological proxy, same caveat as every other PROXY row |
| **pH** | **8.5, max only, no lower bound (`is_lower=False`)** | `Directive (EU) 2020/2184` Annex I Part C, L 435/40: **"Hydrogen ion concentration >= 6,5 and <= 9,5 pH units"** (indicator parameter; a two-sided range, not a single upper bound). `Directive 2000/60/EC` Annex V point 2.4.2: NOT FOUND (no EU-wide numeric value). No document checked supports "8.5" as either bound | **New finding, not a mere confirmation: the code's number (8.5) does not match the one EU value that was actually found (9.5 upper / 6.5 lower), and the code enforces only an upper bound while the source is a two-sided range.** This was already flagged above as a gap ("no lower bound is used; acidic water can never fail"); the sourced extraction now shows the upper bound itself is also not the cited EU value. Do not silently "fix" this by pasting 6.5/9.5 into the code -- `classify_quantity`/`is_physically_possible`'s single-limit, single-direction model does not currently support a two-sided range at all, so this needs a design decision (two limits per parameter, or a different check), not a one-line constant change, and still needs the auditor sign-off the registry design requires |
| Total phosphates | 0.10 mg/L, max | `Directive 2000/60/EC` Annex VIII point 11, L 327/67: NOT FOUND ("phosphates" listed as an Annex VIII eutrophication-contributing substance; "no EU-wide numeric threshold value set in any of the directives" checked) | Confirmed still unsourced at EU level across all four directives checked. Remains an unattributed project convention; the register's existing "no citation; not a drinking-water figure as far as this audit knows" note stands, now with four directives actually checked rather than assumed |
| Water temperature | 25 Cel, max | `Directive 2000/60/EC` Annex V point 1.1.1, L 327/33: NOT FOUND ("Thermal conditions" is a physico-chemical quality element supporting the biological elements; "no EU-wide numeric parametric value set in any of the directives") | Confirmed still unsourced at EU level. A fixed number ignoring site and season remains an open problem regardless of sourcing |
| Zinc | 100 ug/L, max | `Directive 2000/60/EC` Annex VIII point 7, L 327/67: NOT FOUND (falls under "metals and their compounds"; zinc is not an EU priority substance under 2013/39/EU, so its EQS is left to Member States) | Confirmed still unsourced at EU level |
| Benthic macroinvertebrates (BMWP/ASPT, section 7) | not implemented on real data | `Directive 2000/60/EC` Annex V point 1.1.1, L 327/33: NOT FOUND ("Composition and abundance of benthic invertebrate fauna" is a biological quality element; numeric class boundaries and EQR values are set by Member States via intercalibration, not fixed in the directives) | Confirms the existing plan (docs/handoff notes) to use non-binding CCME guideline candidates instead of an EU directive number, since no EU-wide number exists to find |
| Limit of quantification (LOQ) rule | not implemented (registry design item) | Three distinct, real, sourced rules, none yet implemented: (1) drinking water, `Directive (EU) 2020/2184` Annex III Part B point 1, L 435/50: analytical method's LOQ (per Directive 2009/90/EC Art. 2(2)) must be <= 30% of the parametric value; (2) groundwater trend analysis, `Directive 2006/118/EC` Annex IV Part A point 2(d), L 372/29: values below LOQ are set to half the highest LOQ occurring in the time series, except for total pesticides; (3) surface-water chemical-status reporting, `Directive 2013/39/EU` Art. 2(2) (inserting Art. 3(3b) into Directive 2008/105/EC), L 226/6: if the best-available-technique LOQ exceeds the EQS, that substance's result is excluded from the overall chemical-status assessment | Real, citable material now exists for whichever of these three contexts the registry design ultimately needs (they are NOT interchangeable -- each applies to a different monitoring context: drinking water, groundwater trends, surface-water status) |

Still missing from the extraction (per the original registry-design blocker, unchanged): aluminium
through nickel were extracted in an earlier pass (see the handoff entries); arsenic, cadmium,
copper, iron, lead, mercury, nickel now have citations pending transcription into this register in
the same format; ammonium's second (groundwater) citation is `NOT FOUND` per Directive 2006/118/EC
Annex II Part B (Member States decide, no EU number) -- consistent with the pattern seen for
sulphate and phosphates. The auditor sign-off (`verified_by`) required by the registry design has
not happened for any parameter yet.

## 4. Conventions chosen by the project (CONVENTION, no source, no calibration)

| Item | Value | Where | Effect if wrong | Severity | What would validate it |
| --- | --- | --- | --- | --- | --- |
| Non-compensatory veto threshold | excursion >= 1.0 (twice a maximum, half a minimum) | `VETO_EXCURSION` | Changes which sites are flagged and `eclipsed` | High | Ecotoxicological effect thresholds per parameter, agreed with domain experts |
| Eclipsing classes | composite class Excellent, Good or Fair | `ECLIPSABLE_CCME_CLASSES` | Changes `eclipsed` | Medium | same |
| Low-confidence rule (excluded share) | >= 50 % of scorable Observations excluded | `MAX_EXCLUDED_SHARE` | Changes `low_confidence` | Medium | Sensitivity of the WQI to data loss on real, complete data |
| Representative statistic per summary Observation | median, average as fallback; std-dev and extremes never scored | `REPRESENTATIVE_STATISTICS` | Changes every score built from summary Observations | High | Individual test results (the CCME 2001 unit of analysis) instead of period summaries |
| Physical plausibility gate | pH must be within 0-14, no negative concentrations | `is_physically_possible` | Excludes data; definitional, low risk | Low | n/a (definitional) |
| Snapshot freshness | 24 hours | `SNAPSHOT_MAX_AGE_SECONDS` | Stale data used offline | Low | Operational decision |
| Censored quantities | comparator-bearing values excluded unless the bound proves compliance | `classify_quantity` | Drops information; no censored value exists today | Low | Real left-censored chemistry |
| High-censoring warning / small-sample warning | 50 % / n < 20 | `censored.py` | Warnings only | Low | Simulations on real-like distributions |
| ROS plotting positions | Helsel-Cohn construction written from memory, validated by simulation only | `censored.py` | Biased mean if the construction is wrong | Medium | A published worked example or reference software |
| Traffic-light map buckets | Excellent/Good -> good, Fair/Marginal -> moderate, Poor -> poor | `UI_STATUS_BY_CCME_CLASS` | Display only | Low | UX review |
| EQR class bounds | 0.8 / 0.6 / 0.4 / 0.2 for High/Good/Moderate/Poor/Bad | `oah/indices/water_quality.py` `eqr` | Wrong classes if used | Medium | The intercalibrated national class boundaries per water-body type (not run on real data) |
| CCME bands and the 4-variable minimum | published bands; "minimum of 4 variables" quoted from CCME 2001 in code | `water_quality.py`, `apply_to_sandbox.py` | Wrong labels | Low | Re-check against the CCME 2001 technical report |
| Grounding tolerance and always-allowed numbers | half a unit of the last digit; 0, 1, 100; list lengths | `oah/explain/grounding.py` | False alarms or misses | Medium | Real model outputs with human labels |
| Unit alias table for grounding | mg/L, ug/L, ng/L, g/L, uS/cm, mS/cm, ug/m3, mg/m3, Cel, degF, %, NTU | `grounding.py` | Missed unit swaps | Low | A curated list from the real evidence |
| API rate limit, cache TTL, CORS defaults | 60 requests / 60 s per host, 300 s, localhost dev ports | `config.py`, `api/cache.py` | Demo hardening only | Low | Deployment decision |
| LLM spend controls | 5 explain requests a minute per host, 100 real model calls per rolling day, 600 s answer cache, 30 s client timeout, 1 retry | `config.py`, `api/llm_guard.py`, `explain/client.py` | Too loose for a small budget, or too tight for a demo | Medium | The real budget and traffic; the console spend limit is the true cap |
| Sanitiser limits and patterns | strings 200, keys 64, depth 8, items 200, evidence 20,000 characters, output 3,000; instruction patterns in 5 languages | `explain/safety.py` | Legitimate long evidence refused, or new wording passes | Medium | Real hostile and real benign sandbox strings; a real-model injection test |
| Bounds on reviewer fields | `reviewer_id`: 64 characters of `[A-Za-z0-9._-]` (no `@`, no spaces); `final_label`: 128 characters, and since 2026-09-29 it must be one of the item's predicted labels or `other` | `api/schemas/synthetic.py`, `review/queue.py` | A legitimate reviewer id or label is rejected | Low | The identifiers the reviewers actually use |
| Default LLM model id | `claude-sonnet-5-5` (changed 2026-09-29 from `claude-opus-5`, the model of the 2026-09-26 real runs) | `DEFAULT_LLM_MODEL` | The identifier comes from the session environment and has not been exercised against the API; `OAH_LLM_MODEL` overrides it | Low | One real call with the new default |
| k-anonymity default k | 5 | `privacy/k_anonymity.py` | Weaker or stronger anonymity | Medium | A privacy threat model for the real release |
| Generalisation grid | caller-supplied `precision_km`, no default; 111.32 km per degree of latitude | `privacy/geo_generalization.py` | Coarse or leaky masking | Medium | Population density and re-identification testing on real locations |

## 5. Real data with quality problems or bias (DATA-QUALITY)

| Observation | Evidence | Impact | Severity |
| --- | --- | --- | --- |
| Scale errors in period statistics | Averages and extremes often about 10^4 times the median (for example pH 76 800 beside a median of 7.68); 82 statistic Observations inconsistent, 3 pH values impossible | Data excluded; Almyros keeps 12 of 97 scorable Observations | High |
| Tiny and uneven coverage | 4 real places (Crete, Benevento, Oslo, Coimbra); 414 Observations, of which 141 are population-health measures and 146 are unmapped parameters | Nothing generalises beyond these sites | High |
| Identical coordinates | The 12 Benevento reaches share one coordinate pair | Map shows one point; spatial analysis impossible | Medium |
| Non-official Locations | Locations `454`, `455`, `456`, `590` do not follow the official naming; two lie in California and Portugal | Unknown provenance, possibly test data | Medium |
| Provenance not asserted | "Official-looking" is inferred from id prefixes; the consortium does not publish that rule | A record classified `official` may not be | Medium |
| Sandbox growth | 390 Observations at first snapshot, 414 live | Older figures in the ledger and docs are stale | Low |
| No macroinvertebrate counts, no censored values, no annotator data | 0 taxa Observations; 0 comparator-bearing quantities in 1,256 | Most of the biological and statistical machinery cannot be run on real data | High |
| `pH` unit code | Data use `pH`; whether `pH` or `[pH]` is the correct UCUM code is unverified | QC lists it as review-only | Low |
| Period summaries, not individual tests | Almost every value is an average/median/min/max of a period | CCME 2001 assumes individual tests | High |

## 6. Placeholders and provisional identifiers (PLACEHOLDER)

| Item | Value | Where | Note |
| --- | --- | --- | --- |
| Fake namespace | `https://oneaquahealth-hackathon.example/...` (data-origin, derived-indicator, synthetic taxa, observer id, pipeline id) | several `fhir` modules | A reserved example domain, not a registered code system |
| Derived-indicator codes | `ccme-wqi`, `evaluable-measurements`, `distinct-parameters`, `failed-measurements`, `worst-parameter-excursion`, `veto-status` | `fhir/builders/observation.py` | Provisional; the IG has no code for derived indices; the validator cannot resolve the Bundle-contained CodeSystem |
| Performer | `Organization` logical reference `pipeline-id#oneaquahealth-derived-indicators` | same | No Organization resource exists |
| Observation status | `final` for a derived, low-confidence value | same | Profile fixes `#final`; the low confidence is only in a note |
| Device name and version | `oneaquahealth-qc`, `oneaquahealth-indicators`, `0.1.0`; rule versions `qc-1.0`, `ccme-wqi-1.0` | `fhir/output/export.py` | Not tied to real releases |
| `interpretation` | text only, no code | same | No standard code exists for CCME bands |
| Demo river topology | `Loc-Almyros -> Loc-Almyros-Estuary (3.5 km) -> Loc-Almyros-Coast (2.0 km) <- Loc-Nordre-Aker (12.0 km)` | `risk/demo_topology.py` | Two of the four sites do not exist; distances invented; Nordre Aker is in Norway |
| Demo decay and start risk | `DECAY_PER_KM = 0.15`, `INITIAL_RISK = 1.0` | same | At an assumed 0.3 m/s this implies about 3.9 decays per day; not compared with any measured rate |
| "Risk" as normalised concentration | interpretation, not a physical identity | `risk/analytical.py` | Not a probability of illness |
| Frontend fallback map view | centre (20, 0), zoom 2 when no sites; zoom 5 otherwise | `frontend/src/pages/Home.tsx` | Cosmetic |
| Frontend status colours | four fixed colours | same | Cosmetic; not colour-blind-tested |
| FHIR validation level | R4B structural (`fhir.resources`), not R4 4.0.1; OAH profile rules hand-derived from the FSH text, not from the built StructureDefinitions | `fhir/validate.py` | The official HL7 validator run is the conformance evidence; the hand-derived rules have never been compared rule by rule with the StructureDefinitions |
| Sandbox URL | `https://sandbox.hl7europe.eu/oneaquahealth/fhir` | `config.py` | Public, mutable, no stability guarantee; on 2026-09-26 its host did not resolve (DNS failure) while other hosts worked. When it is down the API serves the newest local snapshot (up to days old, still labelled `real-sandbox`) and logs a warning; every real-data response carries `data_freshness` (`live`, `snapshot`, `snapshot-stale`, `unknown`, with `as_of` and `age_seconds`), so a stale snapshot is reported as such |

## 7. Implemented but never run on real data (NOT-RUN)

| Capability | Why not run | What it needs |
| --- | --- | --- |
| BMWP, ASPT, EPT, Shannon, Simpson, Pielou, Chao1 | No taxa counts in the sandbox; BMWP tolerance scores must be supplied by the caller (only a 1-10 range check is hardcoded) | Real counts and the official regional scoring tables (with redistribution rights checked) |
| EQR | No reference values | Type-specific reference conditions and national class boundaries |
| Kaplan-Meier and ROS | No censored values | Real left-censored chemistry |
| Dawid-Skene, one-coin, conformal, class-conditional conformal, review queue | No annotators, no expert labels | Real annotation logs plus expert-verified labels |
| Risk propagation on a real network | No real topology, velocity or decay data | River network, discharge/velocity, dispersion and decay per contaminant |
| Density-adaptive geomasking | No density data; sandbox points are reaches, not residences | An open density dataset and a threat model |
| Cost-based deferral rule | No review-time or error-cost data | Measured expert review time and consequence costs |
| Population-health Observations (141) | The WQI skips them; no health analysis exists | A defined health-outcome question and exposure linkage |
| Grounded explanations on real output | One run of 4 calls reviewed by a human; not repeated after the prompt and evidence fixes | A larger, human-labelled sample of real outputs |
| Frontend beyond the map | Only the home screen exists | n/a |

## 8. Real data that would close these gaps

1. Volunteer taxa identifications with expert-verified truth (validates sections 2 and 7 for reliability and conformal).
2. Individual chemistry test results (not period summaries) with detection limits, per site and date (validates the CCME inputs and censoring).
3. Site-specific or water-body-type objectives and their legal basis (replaces the proxies in section 3).
4. Official macroinvertebrate scoring tables and reference conditions, with their reuse terms.
5. A real river network with discharge, velocity, dispersion and pathogen decay rates (validates the risk proxy).
6. Population density or building data plus a stated threat model (validates privacy parameters).
7. Measured expert review times and error costs (validates the deferral rule).
8. Real LLM outputs on real evidence, labelled by a human (validates the grounding rates).
9. A clarification from the sandbox maintainers about the scale-corrupted statistics, the non-official Locations and the provenance of records.

## 9. Open items in this register

- None open as a confirmed DEFECT. Every UNVERIFIED and CONVENTION row above remains open until validated with the real data listed in section 8.
- The unit table in section 3 and the unit alias table for grounding (section 4) are two separate lists; they are not shared.

## 10. Threshold extraction from the official PDFs (2026-09-29)

Method: the text of four official EUR-Lex PDFs was extracted page by page with `pypdf` (in a throwaway environment outside the repository) and read directly; values below are transcribed from the source text, not from a summary. The PDFs are kept outside the repository (they are third-party EUR-Lex documents). Source files and SHA-256:

| File | SHA-256 |
|---|---|
| `CELEX_32020L2184_EN_TXT.pdf` (Directive (EU) 2020/2184) | `0cf2735a302105350040d6983fb933c9e5cdf1da34f29876dd820b536ae773da` |
| `CELEX_32013L0039_EN_TXT.pdf` (Directive 2013/39/EU) | `1b4478aed35ef792db25311824f5acc8d9a98077ce2a4439e2615614775b0f09` |
| `CELEX_32008L0105_EN_TXT.pdf` (Directive 2008/105/EC, original text) | `6dc4064fb9f9f29647b3ad74221d6cceb25d3c7e5b94c9f5cde5d49cdd7b6e47` |
| `CELEX_32006L0118_EN_TXT.pdf` (Directive 2006/118/EC) | `b6107a11d353713a8fddcc2c71d91938f7286595d276ba3a5a75d224873f54d0` |

Not available and therefore not checked: Directive 2000/60/EC (text) and Directive 2006/44/EC (freshwater fish). Status of every row: extracted, pending the auditor's per-row signature; `CLOSED_PARAM_MAPPING` is not changed by this section.

### 10a. Drinking water, Directive (EU) 2020/2184, Annex I (Official Journal L 435, 23.12.2020)

Quoted rows are "Parameter / Parametric value / Unit" as printed. `Part B` = chemical parameters, `Part C` = indicator parameters.

| Parameter | Verbatim row | Location | Code value | Result |
|---|---|---|---|---|
| Arsenic | "Arsenic 10 ug/l" | Part B, L 435/35 | 10 ug/L | MATCH |
| Cadmium | "Cadmium 5,0 ug/l" | Part B, L 435/35 | 5.0 ug/L | MATCH |
| Copper | "Copper 2,0 mg/l" | Part B, L 435/36 | 20 ug/L | **MISMATCH: source is 2.0 mg/L = 2000 ug/L, 100x the code value** |
| Lead | "Lead 5 ug/l" with note "The parametric value of 5 ug/l shall be met, at the latest, by 12 January 2036. The parametric value for lead until that date shall be 10 ug/l." | Part B, L 435/36 | 10 ug/L | MATCH until 2036-01-12; 5 ug/L afterwards (date-dependent) |
| Mercury | "Mercury 1,0 ug/l" | Part B, L 435/36 | 1.0 ug/L | MATCH |
| Nickel | "Nickel 20 ug/l" | Part B, L 435/36 | 20 ug/L | MATCH |
| Nitrate | "Nitrate 50 mg/l" | Part B, L 435/37 | 50 mg/L | MATCH |
| Nitrite | "Nitrite 0,50 mg/l" | Part B, L 435/37 | 0.50 mg/L | MATCH |
| Aluminium | "Aluminium 200 ug/l" | Part C, L 435/40 | 200 ug/L | MATCH (indicator) |
| Ammonium | "Ammonium 0,50 mg/l" | Part C, L 435/40 | 0.50 mg/L | MATCH (indicator) |
| Conductivity | "Conductivity 2 500 uS cm-1 at 20 C" | Part C, L 435/40 | 2500 uS/cm | MATCH (indicator; value is at 20 C) |
| Hydrogen ion concentration | ">= 6,5 and <= 9,5 pH units" | Part C, L 435/40 | (6.5, 9.5) | MATCH; now enforced through `TWO_SIDED_LIMITS` |
| Iron | "Iron 200 ug/l" | Part C, L 435/40 | 200 ug/L | MATCH (indicator) |
| Sulphate | "Sulphate 250 mg/l" | Part C, L 435/40 | 250 mg/L | MATCH (indicator) |

Not set in this directive: total phosphates, water temperature, zinc, dissolved oxygen (NOT FOUND in the text).

### 10b. Surface water, Directive 2013/39/EU Annex II (replacing Annex I Part A of 2008/105/EC), L 226, 24.8.2013

Columns: AA-EQS = annual average, MAC-EQS = maximum allowable concentration, in ug/l; "inland surface waters" = rivers and lakes.

| Parameter | Printed row (inland AA / other AA / inland MAC / other MAC) | Location | Note | Code value |
|---|---|---|---|---|
| Lead and its compounds | "1,2 (13) 1,3 14 14" | Table row (20), L 226/15 | Footnote 13: "These EQS refer to bioavailable concentrations of the substances." | 10 ug/L: not this standard (this is 1.2 bioavailable) |
| Mercury and its compounds | "0,07 0,07 20" | Row (21), L 226/15 | Column (8) is biota; MAC columns as printed | 1.0 ug/L |
| Nickel and its compounds | "4 (13) 8,6 34 34" | Row (23), L 226/15 | Bioavailable (footnote 13) | 20 ug/L |
| Cadmium and its compounds | AA inland: "<= 0,08 (Class 1) 0,08 (Class 2) 0,09 (Class 3) 0,15 (Class 4) 0,25 (Class 5)"; MAC inland: "<= 0,45 (Class 1) 0,45 (Class 2) 0,6 (Class 3) 0,9 (Class 4) 1,5 (Class 5)" | Row (6), L 226/14 | Footnote 6: hardness classes (Class 1: < 40 mg CaCO3/l ... Class 5: >= 200 mg CaCO3/l) | 5.0 ug/L (drinking-water value) |

Metal EQS refer to the dissolved fraction (0.45 um filtration) except where footnote 13 says bioavailable (Article 2(6)(b), point 3 of Part B, L 226/11). Consequence: the code applies drinking-water values to surface-water data. The surface-water EQS are one to two orders of magnitude stricter (cadmium 0.08-0.25 vs 5.0, lead 1.2 vs 10, nickel 4 vs 20, mercury 0.07 vs 1.0); which regime the index should use is a design decision for the auditor, not settled here. Bioavailable EQS also need hardness/pH/DOC modelling that the sandbox data cannot provide.

### 10c. Groundwater, Directive 2006/118/EC, Annex II Part B, L 372/27

"Minimum list of pollutants and their indicators for which Member States have to consider establishing threshold values": arsenic, cadmium, lead, mercury, ammonium, chloride, sulphate; and "Conductivity" among parameters indicative of saline or other intrusions. The directive sets NO numeric value for these: the values are national. Nothing to transcribe.

### 10d. Still NOT FOUND (in the four documents available)

Total phosphates, water temperature, zinc, dissolved oxygen (minimum 6.0 mg/L in the code). The likely EU source for dissolved oxygen, temperature, zinc and total ammonium in fish waters is Directive 2006/44/EC, and for the WFD status classes Directive 2000/60/EC Annex V; neither PDF was available. Until sourced, these stay CONVENTION/proxy rows.

### 10e. Findings for the auditor

1. **Copper was 100x too strict (20 ug/L vs 2000 ug/L): FIXED 2026-09-29** on the auditor's approval.
2. **Lead changes on 2036-01-12** (10 -> 5 ug/L): IMPLEMENTED 2026-09-29 (dated limit, drinking regime).
3. **Regime question** (drinking-water numbers applied to surface-water data, see 10b): RESOLVED 2026-09-29 as "both, decided per location": river locations use the surface EQS, others the drinking-water values. See `docs/math_registry.md`, "Limit regimes per location and dated limits". Open consequences: cadmium at surface sites needs hardness data; lead and nickel surface EQS are bioavailable while the data are dissolved.
4. Everything else in 10a matches the code exactly.

## 11. Fish-waters directive and Water Framework Directive (added 2026-09-29)

Two more official PDFs were supplied as `1.pdf` and `2.pdf`; both are the SPANISH language versions, so verbatim quotes below are in Spanish with an English rendering (the rendering is the agent's translation, not official text). Text extracted with `pypdf` as in section 10.

| File | Document | SHA-256 |
|---|---|---|
| `1.pdf` | Directive 2006/44/EC (freshwater fish, codified; consolidated version dated 11.12.2008, DO L 264, 25.9.2006, p. 20) | `0d7f340d80bea08f6ab7f31146c7f41be80ae83e96329e824c883b9c8f3e8dbc` |
| `2.pdf` | Directive 2000/60/EC (Water Framework Directive, OJ L 327, 22.12.2000) | `53e6280120a35e763fe861f5553888a43f547a9372aa885d470d614cf8d9d460` |

### 11a. Directive 2000/60/EC: no numeric values

Annex V (tables of physico-chemical elements: "Condiciones térmicas", "Condiciones de oxigenación", "Condiciones relativas a los nutrientes") gives only normative descriptions per status class, e.g. "La temperatura, el balance de oxígeno, el pH ... no muestran signos de perturbaciones antropogénicas" (high status; "temperature, oxygen balance, pH ... show no signs of anthropogenic disturbance"). Result: NOT FOUND (no EU-wide number) for dissolved oxygen, temperature, phosphates and zinc. Article 22(2) also repeals Directive 78/659/EEC (fish waters, of which 2006/44/EC is the codification) thirteen years after the WFD entered into force; the fish-waters values below are therefore historical/reference values and their current legal force must be confirmed by the auditor.

### 11b. Directive 2006/44/EC Annex I, "aguas salmonicolas" (salmonid) / "aguas ciprinicolas" (cyprinid); G = guide, I = mandatory

| Parameter | Verbatim (Spanish) | English rendering | Location | Code value | Result |
|---|---|---|---|---|---|
| Dissolved oxygen (mg/l O2) | Salmonid: "50 % >= 9 / 100 % >= 7"; cyprinid: "50 % >= 8 / 100 % >= 5 / 50 % >= 7" (column text extracted out of order; G/I split per the printed table) | Percentile-based: for salmonid waters half the samples >= 9 and all >= 7; cyprinid, half >= 7 and all >= 5 (mandatory) | Annex I row 2, p. 9 of the consolidated file | minimum 6.0 mg/L | NO MATCH; structure is percentile-based, not a single minimum. Note: "Cuando el contenido en oxigeno descienda por debajo de 6 mg/l" (salmonid) / "4 mg/l" (cyprinid) triggers Article 7(3) |
| Temperature (C) | "el vertido termico no debera tener como consecuencia que la temperatura ... supere los valores siguientes: 21,5 (0) 28 (0)" | thermal discharge must not push downstream temperature above 21.5 (salmonid) / 28 (cyprinid); may be exceeded 2 % of the time | Annex I row 1, p. 8 | 25 C | NO MATCH; applies only downstream of a thermal discharge, not to ambient water in general |
| Total phosphorus | "los valores limites de 0,2 mg/l para las aguas salmonicolas y de 0,4 mg/l para las aguas ciprinicolas, expresados en PO4, podran ser considerados como valores indicativos" | 0.2 (salmonid) / 0.4 (cyprinid) mg/l as PO4, indicative only | Annex I row 6, p. 10 | 0.10 mg/L | NO MATCH; indicative, different chemical basis (PO4 vs P) |
| Total ammonium (mg/l NH4) | "<= 0,04 <= 1(4) <= 0,2 <= 1(4)" | G: 0.04 salmonid / 0.2 cyprinid; I: 1 (footnote 4 allows higher in special conditions) | Annex I row 11, p. 11 | 0.50 mg/L (drinking indicator) | Differs; the code value is the drinking-water one |
| Total zinc (mg/l Zn) | "<= 0,3 <= 1,0"; "Los valores I corresponden a una dureza del agua de 100 mg/l de CaCO3" | 0.3 (salmonid) / 1.0 (cyprinid) mg/l at hardness 100 mg/l CaCO3; Annex II gives 0.03-0.5 (salmonid) and 0.3-2.0 (cyprinid) for hardness 10-500 | Annex I row 13, p. 11; Annex II, p. 13 | 100 ug/L | NO MATCH; hardness-dependent |
| Soluble copper (mg/l Cu) | "<= 0,04"; "Los valores G corresponden a una dureza ... de 100 mg/l de CaCO3" | 0.04 mg/l (guide) at hardness 100; Annex II 0.005-0.112 for hardness 10-300 | Annex I row 14, p. 12; Annex II, p. 13 | 2000 ug/L (drinking) | Differs (hardness-dependent, guide value) |
| pH | "6 a 9 (0)" | 6 to 9 | Annex I row 3, p. 9 | (6.5, 9.5) drinking | Differs (fish-waters range is 6-9) |

### 11c. Consequence for the registry

None of the four still-unsourced parameters gains a general EU ambient value from these documents. Dissolved oxygen, temperature, total phosphorus and zinc exist only as fish-waters values (designated waters, percentile- or hardness-based, possibly no longer in force), so they cannot replace the current proxies without an auditor decision. They stay CONVENTION/proxy rows. Nothing in `CLOSED_PARAM_MAPPING` or the regimes was changed by this section.

## 12. Where the missing thresholds legally live (leads, 2026-09-29; NOT yet primary-verified)

Decision (auditor, 2026-09-29): fish-waters values (section 11) are NOT used as a third regime. Web research found that for dissolved oxygen, phosphorus and zinc the Water Framework Directive delegates the numbers to the Member States (Annex V 1.2.6 and Annex VIII: river-basin-specific pollutants and national class boundaries), so the applicable legislation is national and follows the pilot countries:

| Country (pilot) | Instrument | What it is expected to hold | Status |
|---|---|---|---|
| Italy (Benevento) | DM 8 November 2010, n. 260, Annex 1, table 4.1.2/a (LIMeco), Gazzetta Ufficiale n. 30, 7.2.2011, Suppl. Ordinario n. 31 | Thresholds for dissolved oxygen (100 - % saturation), N-NH4, N-NO3 and total phosphorus | Total phosphorus levels reported by a regional agency (ARPAE, secondary source) as < 50, <= 100, <= 200, <= 400, > 400 ug/l, with "good" at 0.10 mg/l, which equals the code's 0.10 mg/L. Oxygen and nitrogen thresholds and the primary text NOT yet read |
| Italy | D.Lgs. 172/2015, table 1/B (non-priority substances) | AA-EQS for specific pollutants (search snippets mention arsenic 10 and chromium 7 ug/l for inland waters) | Zinc row NOT yet seen; primary text NOT yet read |
| Greece (Almyros) | JMD 140384/2011 and the HCMR physico-chemical classification (HWQI) used in the river basin management plans | National class boundaries for oxygen and nutrients | Not yet located as text |
| Norway (Oslo) | Vannforskriften and Miljodirektoratet classification guide 02:2018 | Class limits for oxygen, total phosphorus and specific pollutants such as zinc | Not yet located as text; Norway is an EEA member, not an EU one |

Nothing in this section is a validated value; no code changed. To close it the primary texts (at least DM 260/2010 Annex 1 and D.Lgs. 172/2015 table 1/B) must be read. Note the regime consequence: national values would be per-country, so the limit regime would also depend on the location's country, not only on its type.

## 13. Italy: DM 260/2010 read from the text (2026-09-29)

Sources (downloaded to a temporary folder outside the repository, at the auditor's explicit go-ahead; text extracted with `pypdf`):

| Copy | Origin | Size (bytes) | SHA-256 | Usable text |
|---|---|---|---|---|
| A | FAOLEX (FAO legal database), `ita102483.pdf` | 702055 | `a1c33fa05be047fe0fa1cfda61ff829732a676aad3eb419aaef48fcba2326889` | Body text only; the LIMeco table is an image ("Parte di provvedimento in formato grafico") |
| B | ARPA Campania publication of the decree, `DM 260_2010.pdf` | 2703694 | `a85ab0307db6284b4d62d5212354f2c74b20180c0ff5ac1eee5dff2feba3fce5` | Reproduces the Gazzetta Ufficiale supplement pagination ("Supplemento ordinario n. 31/L alla GAZZETTA UFFICIALE Serie generale - n. 30, 7-2-2011"); tables readable |

Both are third-party republications of the decree "DECRETO 8 novembre 2010, n. 260"; the auditor should compare the table with the Gazzetta Ufficiale original before signing.

### 13a. Tab. 4.1.2/a, "Soglie per l'assegnazione dei punteggi ai singoli parametri per ottenere il punteggio LIMeco" (Annex 1, section A.4.1.2; copy B, PDF page 66)

Verbatim table (Italian):

| Parameter | Livello 1 | Livello 2 | Livello 3 | Livello 4 | Livello 5 |
|---|---|---|---|---|---|
| Punteggio | 1 | 0,5 | 0,25 | 0,125 | 0 |
| 100-O2% sat. | abs. value <= 10 | <= 20 | <= 40 | <= 80 | > 80 |
| N-NH4 (mg/l) | < 0,03 | 0,06 | 0,12 | 0,24 | > 0,24 |
| N-NO3 (mg/l) | < 0,6 | 1,2 | 2,4 | 4,8 | > 4,8 |
| Fosforo totale (ug/l) | < 50 | 100 | 200 | 400 | > 400 |

The extracted text prints only the numbers, without the "<=" signs for levels 2-4; the "<=" reading matches the regional-agency reproduction quoted in section 12 ("<= 0,10 mg/l" = "buono"). Tab. 4.1.2/b: LIMeco >= 0,66 Elevato; >= 0,50 Buono; >= 0,33 Sufficiente; >= 0,17 Scarso; < 0,17 Cattivo. Level 1 thresholds are the 75th percentile (N-NH4, N-NO3, oxygen) or 90th (total phosphorus) of reference sites (footnote **). Regions may set river-type-specific thresholds for natural reasons.

Also verbatim: "Gli altri parametri, temperatura, pH, alcalinita' e conducibilita', sono utilizzati esclusivamente per una migliore interpretazione del dato biologico e non per la classificazione." (temperature, pH, alkalinity and conductivity are for interpretation only, not classification). So Italy sets NO numeric limit for water temperature.

### 13b. Tab. 1/B (specific pollutants, SQA-MA in ug/l, inland surface waters / other waters)

Copy B lists arsenic 10 / 5 and total chromium 7 / 4 among 51 rows; **zinc does not appear** in this original table (the later D.Lgs. 172/2015 replaced table 1/B and has not been read).

### 13c. Comparison with the code

| Parameter | Italian text | Code | Result |
|---|---|---|---|
| Total phosphorus | 100 ug/l (level 2 = "buono" boundary), expressed as total phosphorus (P) | 0.10 mg/L "Total phosphates" | Numerically equal; basis differs (P vs phosphate: PO4 = 3.07 x P) and the sandbox code says phosphates. Needs the auditor's decision |
| Dissolved oxygen | |100 - % saturation| <= 10 / 20 / 40 / 80 (percent saturation, not mg/L) | minimum 6.0 mg/L | NO MATCH; converting mg/L to % saturation needs water temperature (and pressure/salinity), so the code cannot apply this without a design change |
| Ammonium (N-NH4) | 0,03 / 0,06 / 0,12 / 0,24 mg/l | 0.50 mg/L (drinking) | Differs (river ecological-status regime) |
| Nitrate (N-NO3) | 0,6 / 1,2 / 2,4 / 4,8 mg/l | 50 mg/L (drinking) | Differs; note N basis (NO3 as N) vs NO3 |
| Water temperature | no numeric limit | 25 C | No legal source in Italy; stays a proxy |
| Zinc | not in Tab. 1/B (original) | 100 ug/L | NOT FOUND in DM 260/2010 |

## 14. Auditor decisions and D.Lgs. 172/2015 (2026-09-29)

Decisions on section 13: (1) the regime depends on the country: implemented for Italy; (2) phosphorus is compared as phosphate (PO4 = 3.066 x P), so the Italian 100 ug/l P becomes about 0.3066 mg/L PO4; (3) oxygen is converted to percent saturation using temperature; (4) temperature is interpretive, not scored, in Italy. Details and formulas: `docs/math_registry.md`, section "Country-dependent surface limits, phosphate basis and oxygen saturation". The old proxies 0.10 mg/L phosphates, 6.0 mg/L oxygen and 25 C remain for countries without an implemented national text.

D.Lgs. 13 October 2015, n. 172 (copy from ARPA Campania, 126755 bytes, SHA-256 `c78c15bb2bf1909bd27532e92a8cacac268bfa8af65f43c712481144502953a1`, third-party republication): its item (i) replaces Tab. 1/B of section A.2.7, but the table is an image ("Parte di provvedimento in formato grafico") in every copy that could be read, so the substance rows, including whether zinc appears, could NOT be read. Its note (8) confirms rows 50 to 54 are perfluorinated substances added with effect from 22 December 2018, and the original table (section 13b) has no zinc. Zinc therefore stays NOT FOUND, unresolved: it needs an OCR or the Gazzetta original.

## 15. Official Gazzetta Ufficiale check and nitrogen basis (2026-09-29)

Both texts were downloaded from the official Gazzetta Ufficiale site to a temporary folder outside the repository (at the auditor's instruction) and read with `pypdf`; unlike the third-party copies, tables are text.

| Document | Official URL (ELI) | Size (bytes) | SHA-256 |
|---|---|---|---|
| GU Serie generale n. 30, 7-2-2011, Suppl. ordinario n. 31/L (DM 8 November 2010, n. 260) | `https://www.gazzettaufficiale.it/eli/gu/2011/02/07/30/so/31/sg/pdf` | 5074682 | `93462d01291213abd6a72c9ba4fcb9e795433eb3635ad185db323196ca49736c` |
| GU Serie generale n. 250, 27-10-2015 (D.Lgs. 13 October 2015, n. 172) | `https://www.gazzettaufficiale.it/eli/gu/2015/10/27/250/sg/pdf` | 3355843 | `f5577be12e9f794f1954e993a9447e593e455fb040f00f4887f8cce975ed1eea` |

Results:
- **LIMeco, Tab. 4.1.2/a: CONFIRMED against the official text** (Annex 1, supplement page after the LIMeco procedure; PDF page 69 of the supplement file). Identical to section 13: |100-O2% sat| 10 / 20 / 40 / 80; N-NH4 0,03 / 0,06 / 0,12 / 0,24 mg/l; N-NO3 0,6 / 1,2 / 2,4 / 4,8 mg/l; total phosphorus 50 / 100 / 200 / 400 ug/l. The official PDF text also prints levels 2-4 without the comparison sign; the reading "<=" remains the regional-agency and methodological convention and should be confirmed against the printed page image by the auditor.
- **D.Lgs. 172/2015, replaced Tab. 1/B: read as text** (PDF page 15-16): rows 1-54 of specific pollutants (arsenic 10 / 5, total chromium 7 / 4 ug/l, ... perfluorinated substances from row 50). **Zinc and copper do NOT appear**; Tab. 3/B (sediment) lists arsenic, chromium, PCB. Result: Italy sets no national EQS for zinc in Tab. 1/B, so zinc stays NOT FOUND for Italy (resolved as absent, not unread).

Nitrogen basis (auditor decision): nitrate is the usual nitrogen form for contamination, so LIMeco nitrogen is compared as the ion the sandbox reports. N-NO3 1,2 mg/l (as N) -> NO3 by x 4.427 = 5.31 mg/L NO3; N-NH4 0,06 mg/l (as N) -> NH4 by x 1.288 = 0.0773 mg/L NH4 (`NO3_PER_N`, `NH4_PER_N` in `oah.indices.regimes`, standard atomic weights N 14.0067, O 15.999, H 1.008). Applied to Italian river locations only (level 2 = good status boundary). The comparison assumes the sandbox nitrate and ammonium values are in mg/L as the ion (as the EU drinking-water texts express them); a value measured "as N" would be understated by these factors and must be labeled as such before use.

## 16. The four review points, settled against documentation (2026-09-29)

Evidence: a read-only GET of the public sandbox through the project's own client (23 Locations, 415 Observations; nothing written to the repository), plus the official Gazzetta texts of section 15.

1. **Units of nitrate and ammonium in the sandbox: RESOLVED.** Every mapped Nitrate (6), Ammonium (6), Nitrite (6), Total phosphates (3) and Dissolved Oxygen (6) Observation reports `valueQuantity` in `milligram per liter` with UCUM code `mg/L`, coded by the ion (`nitrate`, `ammonium`, display "Nitrate", "Ammonium"), never "as N". The N-to-ion conversion of section 15 is therefore the right basis. Not stated in the data: whether the source lab reported N or the ion; the code names and display say the ion, and that is the documented reading. Scale caveat (existing, unrelated): Almyros nitrate averages of 145000 mg/L show the known corrupted-scale statistics; the representative-median rule and QC handle them.
2. **The "<=" sign: RESOLVED by the table's structure.** Level 1 is printed "<" and level 5 is printed ">" only. With level 5 strictly ">" (for example ">400"), a value equal to a printed boundary can belong only to the level whose bound it is, so levels 2-4 are "<=". This matches the regional-agency reproduction quoted in section 12 ("<= 0,10 mg/l" = "buono", 100 ug/l). The official PDF prints the intermediate levels as bare numbers; a printed-page image was not inspected.
3. **Benevento's "City environment" type: RESOLVED, and it exposes a bigger fact.** The sandbox describes the 12 Benevento sites as "Benevento ARPAC air-quality station (site NN)" and Loc-Benevento as "City of Benevento (Campania, IT)": they are AIR stations, not water bodies, so no river limit should apply to them and the drinking-water default is meaningless for them (their water-parameter Observations do not exist: every mapped water Observation is at Loc-Almyros or the Giofyros reaches). Consequence: **no Italian river exists in the current sandbox**, so the Italian regime affects no real data today. The river-typed Locations (SNOMED 420531007) are 8: Almyros, Giofyros and their reaches (Crete, Greece), Strawberry Creek and two reaches (not EU: no EU regime is legally meaningful there), and Mina Hospital in Coimbra (no type; Portugal, no instrument read). All mapped water data belong to Almyros (Greece); only water temperature also appears at the Giofyros reaches.
4. **Greek and Norwegian instruments: NOT resolved, and Greece is now the priority.** Greece holds all real water data. Documented so far: JMD 140384/2011 and the HCMR Hellenic Water Quality Index (HWQI: five nutrient species plus dissolved oxygen, five classes bad/poor/moderate/good/high, intercalibrated with MedGIG) are cited by Water 2022, 14, 2738 ("Implementing the CCME Water Quality Index for the Evaluation of the Physicochemical Quality of Greek Rivers", https://www.mdpi.com/2073-4441/14/17/2738), which holds the class-boundary tables. The publisher returned HTTP 403 to automated access, so the tables could not be read; the Government Gazette text of the JMD was not found. Needed: the Greek Government Gazette issue B 3272/2011 or the MDPI PDF supplied by the auditor. Norway (no sandbox water data) stays unread.

Code follow-up made in this section: country detection now also reads a trailing ", Greece", ", Italy" or ", Norway" in a description (the real Almyros and Giofyros parents use it), so Giofyros resolves to GR through its partOf parent.

## 17. Greece: national river classification found and implemented (2026-09-29)

Legal basis found: JMD 140384/2011 (Government Gazette 2017/B, 9.9.2011) only establishes the national monitoring network; its text (read through the ELINYAE legislation portal) contains NO numeric boundaries and defers parameters and methods to the Special Secretariat for Waters. The numeric national classification is the Hellenic Water Quality Index (HWQI) of the Hellenic Centre for Marine Research, described as "officially used for almost a decade" and "extensively tested and officially used on a national basis" in Skoulikidis et al., "Implementing the CCME Water Quality Index for the Evaluation of the Physicochemical Quality of Greek Rivers", Water 2022, 14, 2738, published 2 September 2022, https://doi.org/10.3390/w14172738. Its nutrient boundaries are the Greek Nutrient-quality Classification System (NCS), derived from macroinvertebrate boundaries (AQEM data); oxygen has its own boundaries. The article was read directly in the built-in browser (the publisher blocks automated fetches), not through a summary.

Table 1 of that article, "Water quality classes of the HWQI based on nutrient species (according to NCS) and dissolved oxygen", verbatim numbers:

| Parameter | Unit | High | Good | Moderate | Poor | Bad |
|---|---|---|---|---|---|---|
| N-NO3 | mg/L | < 0.22 | 0.22-0.60 | 0.60-1.30 | 1.30-1.80 | > 1.80 |
| N-NH4 | mg/L | < 0.024 | 0.024-0.06 | 0.06-0.20 | 0.20-0.50 | > 0.50 |
| N-NO2 | ug/L | < 3 | 3-8 | 8-30 | 30-70 | > 70 |
| P-PO4 | ug/L | < 70 | 70-105 | 105-165 | 165-340 | > 340 |
| TP | ug/L | < 125 | 125-165 | 165-220 | 220-405 | > 405 |
| DO | mg/L | > 9 | 6.4-9 | 4-6.4 | 2-4 | < 2 |

Applied (good/moderate boundary, the same "good status" convention as Italy's LIMeco level 2) to river locations resolved to country GR, with the nitrogen and phosphorus conversions of `docs/math_registry.md`: nitrate 0.60 mg/L N -> 2.656 mg/L NO3; ammonium 0.06 mg/L N -> 0.0773 mg/L NH4; nitrite 8 ug/L N -> 0.02628 mg/L NO2; total phosphates 165 ug/L TP as P -> 0.506 mg/L PO4; dissolved oxygen minimum 6.4 mg/L (mg/L, no saturation conversion in Greece). Water temperature is not scored for Greek rivers: the HWQI uses five nutrient species and oxygen only; the article's extra parameters (temperature, BOD, conductivity, pH) belong to its CCME comparison, not to the HWQI. Choices made by the agent, for the auditor to confirm: (a) total phosphorus (TP) rather than orthophosphate P-PO4 (105 ug/L) because the sandbox parameter is "Total phosphates"; (b) the good/moderate boundary as the objective; (c) the HWQI is an official method described in a peer-reviewed article, not a statute, so the citation is the article and its stated official use. Effect: this is the first national regime that reaches real data (all mapped water Observations are Almyros, Greece).

## 18. Chat presentation rounding and evidence constants (2026-10-04)

All CONVENTION, chosen with the maintainer's request for fewer false-precision figures, no source, no calibration (`docs/chat_agent.md` sections 10 and 11). They change how many figures a number is SHOWN with, never the data and never a statistical uncertainty.

| Constant | Value | Where |
| --- | --- | --- |
| `LARGE_SAMPLE_COUNT`, `MEDIUM_SAMPLE_COUNT` | 20, 5 | `src/oah/chat/precision.py` |
| `FIGURES_LARGE`, `FIGURES_SMALL` | 3, 2 | `src/oah/chat/precision.py` |
| `BELOW_DETECTION_SHARE_THRESHOLD` | 0.25 | `src/oah/chat/precision.py` |
| `MAX_EXACT_VALUES`, `MAX_EVIDENCE_ITEMS`, `MAX_EVIDENCE_CHARS` | 10, 20, 12000 | `src/oah/chat/evidence.py` |


## Waterbase pH plausibility bound (2026-10-04)

- Value: 0 to 14, applied by the store build to pH only (`oah.waterbase.mapping.PLAUSIBLE_RANGES`).
- Basis: the definition of the pH scale; not taken from a regulation or a dataset.
- Status: unvalidated as a data-quality rule; it removes impossible values only and says nothing about plausible-looking
  errors. See `docs/waterbase_store.md`.
