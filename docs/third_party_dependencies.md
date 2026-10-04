# Third-party dependencies and why they are cited

This project uses other people's specifications, data, formulas and numbers. Each one is named in
`SOURCES.yaml` (`third_party_notices`) or in the register (`docs/unvalidated_values_register.md`) with what is
taken from it. The rule is simple: **using something requires citing it; citing it does not require keeping or
redistributing a copy, and deleting a copy does not end the use.**

## Why a use must be cited

1. **Licence conditions.** Under CC-BY 4.0 (the Zenodo factsheets, the EEA Waterbase) attribution is a condition of
   the licence itself: without it the use is not licensed.
2. **No licence is not a free pass.** The `hl7-eu/oah` guide declares no licence (the upstream repository reports
   none). By default that means all rights remain with its authors. The project therefore reads and references
   it, does not redistribute it (it is gitignored, deleted from disk and kept out of any published history), and
   still names it, because presenting definitions derived from it as the project's own would misattribute
   authorship.
3. **Traceability of every number and constant.** `AGENTS.md` requires every formula, provisional code and derived
   transformation to be documented with its source. A limit or constraint whose origin is unstated cannot be
   checked or signed (`docs/limits_verification.md`).
4. **Honest scope.** Legal texts, national classifications and the published water-quality index are cited with
   their provision, so a reader can tell a binding value from a proxy or a convention.

## What depends on what

| Dependency | Used for | Where it is cited | Licence status | Local copy |
|---|---|---|---|---|
| `hl7-eu/oah` implementation guide (HL7 Europe) | profile URLs, hand-derived offline profile checks, temporary codes, build and validator scripts | `SOURCES.yaml`, `docs/fhir_mapping.md`, `src/oah/fhir/validate.py` header | not declared: read-only reference, not redistributed | deleted 2026-09-29; restore steps in `docs/environment_setup.md` |
| OneAquaHealth public FHIR sandbox | all real Observations and Locations | `docs/architecture.md`, `docs/unvalidated_values_register.md` | public test server, no stability guarantee | snapshots outside the repository |
| OAH factsheets and field-sampling protocols (Zenodo) | indicator and protocol context | `SOURCES.yaml` | CC-BY 4.0 | gitignored, outside git |
| EEA Waterbase 2024 and 2026 | threshold-registry research, not read by code yet | `SOURCES.yaml` | CC-BY 4.0 | private cloud bucket |
| EU directives (2020/2184, 2013/39/EU, 2008/105/EC, 2006/118/EC, 2006/44/EC, 2000/60/EC) | numeric limits | `SOURCES.yaml`, register sections 10-11 | reuse authorised with acknowledgement of the source (Commission legal notice, CC BY 4.0, Decision 2011/833/EU), checked 2026-09-29 | not stored |
| Italian DM 260/2010 and D.Lgs. 172/2015 | LIMeco boundaries for Italian rivers | `SOURCES.yaml`, register sections 13-15 | not protected by copyright (Law 633/1941 art. 5); Gazzetta allows reproduction citing the source, checked 2026-09-29 | not stored |
| Hellenic Water Quality Index (Water 2022, 14, 2738) | Greek river class boundaries | `SOURCES.yaml`, register section 17 | CC BY 4.0, checked on the article page 2026-09-29 | not stored |
| CCME Water Quality Index 1.0 | the F1, F2 and F3 formulas | `SOURCES.yaml`, `docs/math_registry.md` | method cited, no text reproduced | not stored |
| Python packages | runtime and tests | `pyproject.toml`, hash-pinned `requirements-lock.txt` | each package's own licence | installed in the external environment |

## What deleting a local copy changes and what it does not

It removes the file, so the scripts that need the guide (`scripts/build_ig.py`, `scripts/validate_official.py`,
the archive sample reader) cannot run until it is restored. It does not remove the dependency: the code still
names the guide's profile URLs, `docs/fhir_mapping.md` still lists constraints derived from its sources, and the
citation in `SOURCES.yaml` stays for as long as either does.
