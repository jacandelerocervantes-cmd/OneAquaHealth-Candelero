# FHIR mapping

Resources conform to the real OAH profiles (FHIR R4, 4.0.1) extracted into `ig/oah`. That conformance is established by the official HL7 validator against a SUSHI-built copy of the IG (FHIR 4.0.1; see "Official validation evidence" for the resource counts and run date) — not by the Python structural layer described below, which models `fhir.resources`' `R4B` (FHIR 4.3.0) subpackage and only checks structural shape, not IG-profile conformance. Codes that the IG does not define are project-defined and marked provisional; no IG or sandbox code is ever reused with a different meaning.

## Derived constraints (FSH source)

`observation-with-component-oah` derives from `ObservationIndicatorsOah`: `value[x]` is prohibited, `component` has minimum cardinality 1, and the observation code is extensibly bound to the macrophytes, riparian vegetation, or nutrients types. Its named component slices are optional; their coded bindings are required where a slice is present. The source does not state the inherited cardinalities in this file, so they remain ambiguous until all parent profiles are evaluated.

`location-oah` requires at least one `identifier`, a `name`, and `mode = instance`. `position` is optional; when supplied, longitude and latitude are both required. `referenceForm` is an optional repeating related-artifact extension.

Codes from `temporarySystem-oah-eu` are provisional because the IG describes it as temporary. No codes are invented by this project.

Structural checks use `fhir.resources` 8.2.0 and its `R4B` (FHIR 4.3.0) subpackage. R4B is not the sandbox's R4 (4.0.1); passing structural checks does not establish full IG-profile conformance. Full validation with the official HL7 validator is a later step.

The sandbox has no StructureDefinitions, so its `$validate` cannot check IG conformance. Validation returns error findings and applied profiles separately.
R4B structural validation enforces paired `position.latitude` and `position.longitude`.

Official HL7 validation built the extracted IG and ran on real fixtures with zero errors. Warnings identify provisional Observation and Location terminology bindings; they are observed provisional-code warnings, not project defects. The Python R4B layer remains structural only.

Generated Provenance reasons retain QC-rule text without a PurposeOfUse coding when no applicable published code exists.

## QC findings export

`scripts/export_findings.py` writes a real-sandbox-derived collection Bundle under
`OAH_DATA_DIR/exports/findings-bundle.json`. It computes each Observation's findings with
`component_statistics`, creates one `DetectedIssue` for each finding, and sets its
`implicated` reference to the absolute sandbox Observation URL. The Bundle contains one
deterministic software `Device`, all sorted `DetectedIssue` resources, and one `Provenance`.
The Provenance targets the Bundle's `DetectedIssue` entries by `urn:uuid` and identifies the
Device agent by its `urn:uuid`. Input Observations and findings are canonicalized and sorted,
so the serialized result is byte-identical when the retrieval date and input set are unchanged.

Only DomainResources receive generated XHTML narrative text (`text`). `Bundle` is not a
DomainResource and must not contain `text`.

The shared QC allowlist contains `ug/L`, `mg/L`, `Cel`, `mS/cm`, `%`, `ug/m3`, `uS/cm`, and `pH`, observed in the sandbox on 2026-09-21. `pH` is reported for review rather than as a unit error; `pH` versus `[pH]` is unverified. Python profile checks cover four profiles, derived by hand from the FSH sources: `location-oah`, `observation-with-component-oah`, `observation-indicators-oah` (status `final`, code, subject `Location`, `effective[x]`, `performer`, `value[x]` limited to CodeableConcept or Quantity, `specimen` `Specimen`, component `value[x]` required and limited to CodeableConcept, string or Quantity) and `observation-health-measure-oah` (status `final`, code, subject `Location`, `effective[x]`, `value[x]` limited to CodeableConcept or Quantity, `focus` `Group`). References are checked by resource type only. Structural R4B models now also cover Group, Library, Organization and Specimen. On the 390-Observation snapshot and the six real fixtures (2026-09-26) all four checks report zero findings and apply to 157 Observations that previously had no profile check; the official HL7 validator run remains the conformance evidence, and these checks are a fast offline subset (the code binding rules and profile slicing are not checked).

Public-sandbox Observation reports classify identifiers with the observed `Obs-Almyros-`,
`Obs-Benevento`, `Obs-BN-`, `Obs-OS-`, `Obs-WaterTemp-`, and `Obs-EC-` prefixes as
official-looking. This is a read-only operational classification based on observed identifiers,
not a consortium-published provenance assertion; all other identifiers are reported as `other`.

Synthetic citizen-science Observations use the project-defined
`https://oneaquahealth-hackathon.example/CodeSystem/synthetic-taxa-family` CodeSystem for reported
taxa families. Observers are identified via pseudonymous `performer` references with system
`https://oneaquahealth-hackathon.example/observer-id` and values such as `observer-1`.
Specimens are referenced via the standard FHIR R4 `specimen` element (`Reference(Specimen/{specimen_id})`).
Every generated DomainResource (`Observation`, `CodeSystem`, `Provenance`) includes a minimal XHTML `text` narrative.
Ground truth ($specimen\_id \to true\_family$) is kept strictly outside FHIR resources.
Every synthetic batch has `meta.tag` code `synthetic` under the project data-origin system and batch Provenance that declares the generator seed and version.

## Derived indicators export (`ObservationIndicatorsOah`)

`build_indicators_bundle` (`src/oah/fhir/output/export.py`, builder in
`src/oah/fhir/builders/observation.py`, script `scripts/export_indicators.py`, API
`POST /fhir/export/indicators`) emits one Observation per real Location whose CCME WQI is
evaluable. Locations without evaluable measurements produce no Observation (never an invented value).
Source of the formula: CCME (2001), see `docs/math_registry.md`.

| Element | Value | Traceability |
| --- | --- | --- |
| `meta.profile` | `.../StructureDefinition/observation-indicators-oah` | IG `observation-indicators-oah.fsh` |
| `status` | `final` | profile fixes `#final` |
| `code` | `derived-indicator#ccme-wqi` | **Provisional**, project-defined (below); profile binding is *preferred* only |
| `subject` | absolute sandbox `Location/<id>` URL | profile: `Reference(LocationOah)` |
| `effectiveDateTime` | retrieval timestamp | profile: `effective[x] 1..` |
| `performer` | Organization logical reference, identifier `pipeline-id#oneaquahealth-derived-indicators` | profile: `performer 1..`; no Organization resource is invented |
| `valueQuantity` | score, UCUM `1` (unitless) | profile: `Quantity` allowed |
| `component` | evaluable-measurements, distinct-parameters, failed-measurements (UCUM `1`); worst-parameter-excursion (UCUM `1`); veto-status (`valueString`: `none`, `veto: <parameters>` or `eclipsed: <parameters>`) | counts and veto from `apply_ccme_wqi_to_sandbox`; veto rule in `docs/math_registry.md` |
| `interpretation.text` | CCME band (Excellent/Good/Fair/Marginal/Poor) | `classify_ccme_wqi`; text only, no standard code exists for CCME bands |

Provisional CodeSystem `https://oneaquahealth-hackathon.example/CodeSystem/derived-indicator`
(`ccme-wqi`, `evaluable-measurements`, `distinct-parameters`, `failed-measurements`, `worst-parameter-excursion`, `veto-status`) is shipped inside
the Bundle as a `CodeSystem` resource. EQR, BMWP and ASPT are implemented as functions but are **not**
exported: the public sandbox has no macroinvertebrate data, so no honest value exists to emit.
Provenance targets every emitted Observation and identifies a software Device agent.

## Official validation evidence

Run `scripts/build_ig.py` then `scripts/validate_all_real.py` (official HL7 validator, FHIR 4.0.1,
against the SUSHI-built IG). Result on 2026-09-23: 485 real sandbox resources (414 Observation, 23
Location, 27 Group, 18 Library, 3 Organization) produced **0 errors**; the warnings are provisional
IG terminology bindings and UCUM annotation notes in the sandbox data itself. The indicators Bundle
(`scripts/export_indicators.py` + official validator) produced **0 errors** and 16 warnings: text-only
`interpretation`, `PurposeOfUse` reason text, and the validator not resolving the Bundle-contained
provisional CodeSystem.

## Ecological & Physicochemical Indices Mapping

- **CCME WQI 1.0**: Evaluated per real sandbox `Location` from actual physicochemical `Observation` resources (`Ammonium`, `Nitrate`, `pH`, `Temperature`, `Electrical Conductivity`, etc.). Sites lacking evaluable physicochemical observations are skipped with a documented reason.
- **Biotic & Diversity Indices**: BMWP, ASPT, EPT Ratio, Shannon, Simpson, Pielou, and Chao1 are implemented as pure, regional-score-parametrized functions in `src/oah/indices/`. They are **NOT computed on public sandbox data** because no macroinvertebrate count records exist in the public sandbox.

