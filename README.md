# OneAquaHealth

A reproducible foundation for ingesting OneAquaHealth data, running quality control, producing FHIR R4 resources, and calculating environmental indicators.

## Getting started

Use a Python 3.12 virtual environment outside this synchronized directory. Copy `.env.example` to `.env` and set the required variables. `uv` is optional; when it is available, verify the official inputs with:

```powershell
uv run oah-verify-reference
uv run oah-extract-ig
uv run pytest
```

`reference/` contains immutable official inputs. `data/` only documents the local-data boundary: effective cache and sandbox dumps belong in `OAH_DATA_DIR`, or in the user cache when it is unset. All application paths are resolved through `oah.paths`, so commands work from any current directory.

See `SOURCES.yaml` for provenance and `docs/architecture.md` for layer boundaries.

## License and attribution

OneAquaHealth's own original code is MIT-licensed; see `LICENSE`.

This project builds on official material from the IEEE OneAquaHealth Global Hackathon 2026,
which is not covered by that license:

- The [hl7-eu/oah](https://github.com/hl7-eu/oah) HL7 FHIR Implementation Guide and public
  sandbox (stored read-only under `reference/oah-master.zip`) is the official hackathon
  reference IG. Its upstream repository does not declare a license; it is used here
  unmodified, read-only, for the hackathon's stated purpose.
- **"OneAquaHealth Key Indicators of Ecosystem and Biological Health — Factsheets Collection"**,
  OneAquaHealth Consortium (2026), Horizon Europe Grant Agreement 101086521.
  [doi.org/10.5281/zenodo.20345207](https://doi.org/10.5281/zenodo.20345207) — CC BY 4.0.
- **"OneAquaHealth Field Sampling Protocols for Urban Stream Ecosystems"**,
  OneAquaHealth Consortium (2026), Horizon Europe Grant Agreement 101086521.
  [doi.org/10.5281/zenodo.20344421](https://doi.org/10.5281/zenodo.20344421) — CC BY 4.0.

See `SOURCES.yaml` (`policy.third_party_notices`) for the full detail behind each entry above.

## Run

Create and use the external virtual environment, install `.[dev]`, and run `python -m pytest`. No `.env` is required for the public sandbox default. Run `python scripts/capture_fixtures.py` to create labeled `fixtures/real/` resources.

Run `<venv>\Scripts\oah-qc-report.exe` to write JSON and Markdown reports under `<data dir>/reports/`.

## Quality checks

```powershell
<venv>\Scripts\python.exe -m pytest                       # unit, contract, property, integration, portability
<venv>\Scripts\python.exe -m ruff check src scripts tests # lint (E, F, W; rules in pyproject.toml)
<venv>\Scripts\python.exe -m mypy                         # types (config in pyproject.toml; src, scripts, tests)
<venv>\Scripts\python.exe -m pytest --cov --cov-report=term-missing   # coverage gate at 95 %
```

`tests/portability/test_static_checks.py` runs ruff and mypy inside the suite, so a plain `pytest` also fails on lint or type errors.
`docs/unvalidated_values_register.md` lists every synthetic, assumed or unverified value and what real data would validate it.

## Full pipeline

These are the exact commands, in order, to reproduce everything from a clean checkout on
Windows. `<venv>` is your external Python 3.12 x64 virtual environment, created outside this
synchronized directory (see "Getting started" above).

```powershell
# 1. Install
<venv>\Scripts\python.exe -m pip install -e ".[dev]"

# 2. Verify the immutable official reference inputs and extract the Implementation Guide
<venv>\Scripts\oah-verify-reference.exe
<venv>\Scripts\oah-extract-ig.exe

# 3. (Optional, needed only for official HL7 IG-conformance validation) build the IG with
#    SUSHI, and have Java plus the HL7 validator jar available. If any of these is missing,
#    the pipeline still runs; it explicitly reports that one stage as skipped and says why.
<venv>\Scripts\python.exe scripts\build_ig.py

# 4. Run the full test suite
<venv>\Scripts\python.exe -m pytest

# 5. Run the one-command end-to-end pipeline: sandbox snapshot -> QC -> FHIR structural
#    validation -> FHIR export with Provenance -> indices -> synthetic risk demo. Every
#    output is written under the configured data directory, never inside this repository.
<venv>\Scripts\python.exe scripts\run_pipeline.py

# 6. Start the local demo API (serves the same pipeline stages as read/query endpoints)
<venv>\Scripts\python.exe scripts\run_api.py
```

With the API running, `GET http://127.0.0.1:8000/health` should return `{"status": "ok"}`.
See `docs/architecture.md` for the full endpoint table; every response is labeled with its
data origin (`"real-sandbox"` or `"synthetic"`).

### Optional environment variables

None of these are required for `/health` or for the test suite. `.env` (copied from
`.env.example`, not versioned) is the recommended place to set them; see `oah.config.Settings`
for the authoritative list and defaults.

| Variable | Purpose | Default |
| --- | --- | --- |
| `ANTHROPIC_API_KEY` | Required only for the two `/explain/*` endpoints and `scripts/eval_explain.py`. Without it, those endpoints return `503` with a clear message; everything else works normally. | unset |
| `OAH_LLM_MODEL` | Overrides the Claude model used by `/explain/*`. | `claude-sonnet-5-5` |
| `OAH_ENABLE_DOCS` | Set to `1` to serve the interactive API docs and the OpenAPI schema (`/docs`, `/redoc`, `/openapi.json`). Off by default: they are unauthenticated and list every route. Local development only. | unset (off) |
| `OAH_LIMITS_FILE` | Absolute path (outside the repository) of a JSON file that replaces or adds limits, location countries and location regimes without editing code. Validated strictly, re-read when it changes, and labelled `override:` in every output. Format and example: `docs/limits_override.example.json`. | unset (shipped limits) |
| `OAH_TRUSTED_PROXIES` | Comma-separated IP addresses of reverse proxies whose `X-Forwarded-For` and `X-Forwarded-Proto` headers are believed. Needed for per-client rate limits and HSTS behind a proxy; from any other peer those headers are ignored. | unset (none) |
| `OAH_API_KEY` | Once set, every route except `/health` requires a matching `X-API-Key` header. Unset by default for local/dev convenience; set this before exposing the API beyond localhost. | unset (open) |
| `OAH_CORS_ORIGINS` | Comma-separated list of origins allowed to call the API from a browser (e.g. a future frontend's dev server). | `http://localhost:3000, http://127.0.0.1:3000, http://localhost:5173, http://127.0.0.1:5173` |
| `OAH_EXPLAIN_RATE_LIMIT_PER_MINUTE`, `OAH_EXPLAIN_DAILY_CAP`, `OAH_EXPLAIN_CACHE_TTL_SECONDS` | Spend controls for the paid `/explain/*` calls: a per-host requests-per-minute budget, a rolling 24-hour cap on real model calls for the whole process (a restart resets it), and how long an identical answer is reused. Cached answers cost nothing. With a small API budget lower the daily cap. | `5`, `100`, `600` |
| `OAH_RATE_LIMIT_MAX_REQUESTS`, `OAH_RATE_LIMIT_WINDOW_SECONDS` | Per-client-host request budget enforced on every route except `/health`. Single-process only; see `docs/architecture.md`. | `60` requests / `60` seconds |

## Synthetic data

`oah.synthetic` creates explicitly labeled, seeded citizen-science macroinvertebrate campaigns
for developing observer-reliability, conformal-prediction, and human-review components. It uses
real Location identifiers only as labels and never reads or copies real Location data. Synthetic
records cannot be mixed with real sandbox records, and results on them measure the simulator—not
real ecological or operational performance.
