# Pitch notes: market landscape and digital twins

Internal notes for the (later) pitch. They are **not** project documentation of the code and
must not be cited externally as fact. Everything below comes from a secondary research report
supplied by the team; items marked (unverified) must be checked against the primary source
before use. Status: draft, 2026-09-23.

## 1. Where OneAquaHealth sits

| Layer | What exists in the market/research | What this project adds |
| --- | --- | --- |
| Continental digital twins | Destination Earth (DestinE, EU/ECMWF/ESA/EUMETSAT): twins for weather extremes and climate adaptation, phased 2022-2030. | Reach-scale, health-linked view of urban streams. The report found no evidence that DestinE ingests street-level freshwater bioindicators (unverified). |
| Commercial water suites | Xylem Vue, Bentley OpenFlows WaterGEMS: network hydraulics, CSO mitigation, treatment optimisation, proprietary data models. | Open, standards-based (FHIR R4) output that a public-health group can reuse. |
| Citizen-science programmes | FreshWater Watch (Earthwatch), Anglers' Riverfly Monitoring Initiative: volunteer sampling at scale. | Quantified observer reliability (Dawid-Skene) and abstention with human review, instead of simple vote rules or unvalidated publication. |
| Open government data | Hub'Eau (France), EEA WISE Waterbase, England Water Quality Archive, Copernicus Sentinel-2. | A validated FHIR layer over this kind of data; not a replacement for it. |
| Standards | HL7 Europe OAH IG (early CI build), OGC SensorThings, OMOP/OHDSI GIS work. | Conformance evidence against the OAH IG (see `docs/fhir_mapping.md`). |

## 2. Gaps the report identifies (candidate talking points)

1. Almost no citizen-science platform exposes standards-based FHIR endpoints or automated statistical QC.
2. Dashboards commonly average sub-indices, so one severe exceedance can be hidden (sub-index eclipsing). This also affects distance-based indices such as the CCME WQI.
3. No deployed system was found that deterministically verifies numbers in LLM-generated health text (unverified as a universal claim; our `oah.explain.grounding` implements exactly this check).
4. Lightweight network-propagation proxies are rarely integrated with public-health views.
5. Software from Horizon Europe consortia is often abandoned after the grant ends.

## 3. Claims we can make honestly today

- Real sandbox resources validate with the official HL7 validator with 0 errors (485 resources, 2026-09-23; see `docs/fhir_mapping.md`).
- Derived indicators are exported as OAH-profile Observations with Provenance.
- Real and synthetic data are labelled and never mixed; synthetic results measure the simulator, not ecology.
- Model outputs carry an explicit origin field.

## 4. Claims to avoid

- "First" or "only" system of any kind: absence of evidence in one report is not proof.
- Any performance number for citizen-science or ML components measured on synthetic data, presented as real.
- Regulatory conclusions (AI Act risk class, EHDS obligations): not assessed; the report itself says to confirm timelines.
- Prize pool, dates and CI-build error counts for the hackathon or the IG: volatile.

## 5. Items to verify before any external use (all unverified)

- OneAquaHealth budget, partner and country counts; sentinel-city list; SIRENE grant details.
- Zenodo record and DOI numbers other than the two already recorded in `SOURCES.yaml`.
- Company product claims (Xylem Vue, Bentley WaterGEMS) and FreshWater Watch dataset sizes.
- DestinE scope for inland-water bioindicators.
- Any model metric or dataset size marked with a warning sign in the source report.
