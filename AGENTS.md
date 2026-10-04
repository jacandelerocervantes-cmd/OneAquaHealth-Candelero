# Agent Contribution Rules

## Scope

- The repository root is this directory, identified by `pyproject.toml`.
- `stack-ia-dev/` is out of scope: do not read, edit, execute, or use it as a dependency.
- `reference/` is read-only. Do not modify, regenerate, or replace its files; run `oah-verify-reference` before relying on them.
- Modules under `src/oah/` must not import code from other repositories. Adaptations are copied and attributed in `SOURCES.yaml`; external origins are expressed relative to `OAH_SOURCES_ROOT`.
- All source code, tests, configuration, and documentation must be written in English.

## Paths and data

- Only `src/oah/paths.py` constructs project paths. All other code uses its functions.
- Do not introduce absolute paths or paths relative to the process working directory.
- Sandbox data and caches belong in `OAH_DATA_DIR` (outside the project by default). Never create `.venv`, `node_modules`, or large caches in this synchronized directory.
- Credentials belong in `.env`, which is not versioned. Update `.env.example` whenever adding a non-secret variable.
- Real and synthetic data must be explicitly labeled and stored separately. Both modes share one interface; synthetic records carry `meta.tag` and a Provenance statement. Never present synthetic results as real-world performance.

## Quality

- Keep Python 3.11 or later (below Python 3.13) and pin dependencies in `pyproject.toml`.
- Add unit and, where applicable, contract, property, and portability tests with every change.
- Document every formula, provisional FHIR code, or derived transformation in `docs/`, including its source traceability.
- Never invent FHIR codes. Use only codes from the extracted implementation guide or the sandbox, and explicitly mark provisional mappings.

## Handoff and Git

- Read `docs/handoff/LEDGER.md` at the beginning of every turn and append a complete handoff entry at the end.
- Do not run `git commit` or change Git configuration.
