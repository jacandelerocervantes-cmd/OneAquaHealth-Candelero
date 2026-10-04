# Environment setup

The project's Python code carries no hardcoded machine path. `src/oah/paths.py` locates the repository
root by walking up from its own file location until it finds `pyproject.toml`, so a clone at any path, on
any machine, on any drive letter, resolves the same way. Data and caches go outside the repository, under
`LOCALAPPDATA` (Windows) or `~/.cache` (elsewhere), or an explicit `OAH_DATA_DIR` you set (see
`.env.example`). Nothing here depends on a specific username or drive.

## Do not create `.venv` inside this folder

`AGENTS.md` forbids creating a virtual environment inside the repository (the folder that gets
synchronized). It happened once already, ended up empty, and would travel with the project on every sync.
Create your virtual environment in a sibling folder instead, for example:

```powershell
cd <parent-of-your-clone>
py -3.12 -m venv oah-venv
oah-venv\Scripts\python.exe -m pip install -e "OneAquaHealth[dev]"
```

If a `.venv` already exists inside the repo (check with `Test-Path .venv` from the repo root), delete it:

```powershell
Remove-Item -Recurse -Force .venv
```

## Requirements

- Python `>=3.11,<3.13` (see `pyproject.toml`).
- An x64 interpreter is the tested path. `pyyaml==6.0.2`, pinned in `pyproject.toml`, has no published
  wheel for Windows ARM64 as of 2026-09-26 (confirmed with `pip download --platform win_arm64`); on an
  ARM64 machine (for example a Windows-on-Snapdragon laptop) either install Microsoft C++ Build Tools to
  compile it, or use an x64 Python installed through emulation. This is a `pyyaml` packaging gap, not a
  project path issue.

## First run

```powershell
oah-venv\Scripts\python.exe -m pytest --cov=oah
oah-venv\Scripts\python.exe -m ruff check src scripts tests
oah-venv\Scripts\python.exe -m mypy
```

Copy `.env.example` to `.env` and fill in the values you need (see its comments); `.env` is never
versioned. `OAH_DATA_DIR` and `OAH_SOURCES_ROOT`, if set, must be absolute paths — they are validated,
not silently accepted.

The convention for the example file, the list of variables and the pinning rules (Python, lockfile, base image, and the
plan for the web app) are in `docs/environment_variables.md`; the pre-deployment checklist is
`docs/predeploy_checklist.md`.

## `ig/` and `reference/` are not in git

`ig/oah/` and `reference/oah-master.zip` are gitignored and, since 2026-09-29, also deleted from the local
disk (the auditor's decision, so that they cannot reach a published repository): the upstream implementation
guide has no declared licence (see `SOURCES.yaml`), so this project does not redistribute it. The two Zenodo
PDFs under `reference/` (CC-BY 4.0) are gitignored too. A fresh clone has none of them.

`reference/CHECKSUMS.sha256` stays tracked (it is this project's own hash manifest, not third-party
content). It still lists the hash of the archive that was deleted.

### Restoring `ig/` and `reference/`

Only the FHIR build and official-validator scripts (`scripts/build_ig.py`, `scripts/validate_official.py`) and the
archive sample reader need the guide; the test suite and the API do not (their tests use temporary archives).

1. Download the `hl7-eu/oah` repository as a zip from `https://github.com/hl7-eu/oah` and place it at
   `reference/oah-master.zip` (the folder is read-only for agents: do this yourself).
2. The manifest holds the hash of the archive that was used before, and the upstream branch moves, so a new
   download will not match it. Verify the download yourself, then update the line in
   `reference/CHECKSUMS.sha256` deliberately (a human change, recorded in the ledger).
3. Extract and verify:

```powershell
oah-venv\Scripts\python.exe -m oah.extract_ig   # or: oah-extract-ig, once installed
oah-venv\Scripts\python.exe -m oah.verify_checksums   # or: oah-verify-reference
```

## Reproducible install and dependency audit

`requirements-lock.txt` pins every dependency, direct and transitive, with hashes. To install exactly that set into the external virtual environment:

```powershell
oah-venv\Scripts\python.exe -m pip install --require-hashes -r OneAquaHealth\requirements-lock.txt
oah-venv\Scripts\python.exe -m pip install --no-deps -e OneAquaHealth
```

To regenerate it after editing `pyproject.toml` (in a throwaway environment that has `pip-tools`), and to check it for known vulnerabilities (with `pip-audit`):

```powershell
python -m piptools compile --generate-hashes --extra dev --strip-extras -o requirements-lock.txt pyproject.toml
python -m pip_audit -r requirements-lock.txt --disable-pip --no-deps
```

Audit history: on 2026-09-29 `pip-audit` reported advisory PYSEC-2026-1845 for `pytest 8.3.5` (development only, fixed in 9.0.3). The pin was raised to `9.0.3`, the lockfile regenerated, and the audit then reported no known vulnerabilities. The whole suite was run in a clean environment built only from the hash-pinned lockfile (`pip install --require-hashes`): 1092 passed, 1 skipped.
