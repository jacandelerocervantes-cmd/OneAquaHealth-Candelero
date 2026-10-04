# Official-record filter

Code: `src/oah/ingest/official.py` (`classify_official_record`, `split_official`). Tests: `tests/unit/test_official_filter.py`,
and the route tests in `tests/unit/test_api.py`.

## Why

The public sandbox is shared. Besides the consortium's records it holds demo records, simulated records and records written
under third-party profiles (a forecast application, citizen-science tools). On 2026-10-02 the maintainer's inventory counted
about 619 Observations of which roughly 59 carried a `meta.tag` of `simulated` or `demo`, 161 had no profile and 51 used
third-party profiles (`docs/indices_catalog.md`, section 2). None of these may reach a count, an index or a QC finding.

## The rule

One decision per Observation, in priority order; the first rule that applies gives the exclusion reason.

| Order | Condition | Reason |
|---|---|---|
| 1 | `meta.tag` has a coding with `code` equal to `simulated` | `tag-simulated` |
| 1 | ... equal to `demo` | `tag-demo` |
| 1 | ... equal to `synthetic` (this project's own label for generated data; AGENTS.md requires synthetic data to stay separate) | `tag-synthetic` |
| 2 | a profile URL, a coding `system` or a coding `code` (of the Observation or of a component) contains `streampulse` or `streamsense`, or starts with `sl-` (the code itself, or the last segment of a URL) | `third-party` |
| 3 | `meta.profile` is empty or absent | `no-profile` |
| 4 | no profile is an OAH profile: a URL under `http://hl7.eu/fhir/ig/oah/StructureDefinition/`, or one of the bare names already used by `oah.indices.water_parameter_limits` | `non-oah-profile` |
| - | otherwise | official |

Matching is case-insensitive. A malformed `meta` is treated as having no tag and no profile (so it is excluded as `no-profile`).

## Where it is applied

`oah.api.app._official_observations()` (the sandbox Observations with the filter applied) feeds `/sites`, `/countries`,
`/indices/{location_id}`, `/explain/indices/{location_id}` (through the index payload), `/sites/{location_id}/measurements`
and both FHIR exports. `/qc/report` applies it before `build_report` and adds two additive fields:

- `excluded_observations`: a count for every reason (zeros included), for example `{"tag-demo": 3, "third-party": 51, ...}`;
- `excluded_observations_total`: their sum.

`total_observations` and every other QC count now cover official records only. The library functions
(`build_report`, `apply_ccme_wqi_to_sandbox`) are unchanged and do not filter by themselves, so scripts that call them
directly must call `split_official` first if they read the public sandbox.

## Provisional

- The third-party markers (`streampulse`, `streamsense`, `sl-`) come from the maintainer's inventory, not from a published
  list; they could not be checked against every sandbox record. Extend `THIRD_PARTY_SUBSTRINGS` or `THIRD_PARTY_PREFIXES`
  when a new application appears. A third-party record that matches none of the markers and has no OAH profile is still
  excluded by rule 3 or 4; one that carries an OAH profile and no marker would pass (the residual risk).
- The `tag-synthetic` reason is an addition to the requested `simulated` and `demo` tags, kept so that generated data can never
  enter a real-sandbox answer.
- `oah.ingest.classification.classify_observation` (id-prefix based `observation_origin_counts` in the QC report) is a
  different, older, report-only label and is left as it was.
