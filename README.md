# AquaLedger

**Ask the water. Get the data, not a verdict.**

AquaLedger answers plain questions about river, lake and bathing-water data of Greece, Italy and Norway, in 26 languages,
using only real European data. Every number in an answer is checked against the data the assistant retrieved; an answer
that fails the check is withheld, not guessed. Each answer carries its sources, licence, method and the reference values
used.

Built for the IEEE OneAquaHealth Global Hackathon 2026. The Python package is called `oneaquahealth` (module `oah`).

- Live demo: <https://one-aqua-health-candelero.vercel.app/> (Next.js web app in front of this backend).
- Backend: FastAPI service in `src/oah/`, deployable to Cloud Run (`docs/deployment.md`).
- Web app: `web/` (Next.js 16, TypeScript, Tailwind; `docs/web_app.md`).

## What it does and what it refuses

- Reads water measurements and classifications from real sources, always labelled with their origin: **real**,
  **externally modelled** (weather, river discharge, species records) or **synthetic**. The three are never mixed silently.
- A read-only AI agent (Claude, Anthropic Messages API) picks the data tools; the answer is then checked: numbers and units
  must match the tool results, the text must not contain links, markup or leaked instructions.
- Values are compared with **reference values (screening)**, never called legal compliance. No health, potability or safety
  verdicts: the app points to the competent authority instead.
- Figures in answers are shown as observed ranges or with presentation rounding, never as invented precision.
- Every request leaves a hash-chained audit record (digests only, no question text).

## Data sources

| Source | Content | Licence |
| --- | --- | --- |
| EEA Waterbase - Water Quality ICM 2026 | Annual and monthly aggregates of river and lake measurements (GR, IT, NO) | CC BY 4.0 |
| EEA Bathing Water Directive status 2025 | Per-season classification of each bathing water (GR, IT) | CC BY 4.0 |
| EEA bathing-water monitoring results (Discodata) | Individual E. coli and intestinal enterococci samples (GR, IT) | CC BY 4.0 |
| HL7 Europe OneAquaHealth sandbox | Public sandbox observations and the implementation guide | see `SOURCES.yaml` |
| Open-Meteo (ERA5, GloFAS), GBIF | Modelled weather and river discharge, species records (context only) | see `docs/external_context.md` |

Provenance of every item is in `SOURCES.yaml`; formulas, provisional mappings and unvalidated values are in `docs/`
(`unvalidated_values_register.md`, `limits_verification.md`).

## Run the backend yourself

You need Python 3.11 or 3.12 (not 3.13) and Git. Nothing else is required to start the API.

```bash
git clone https://github.com/jacandelerocervantes-cmd/OneAquaHealth-Candelero.git
cd OneAquaHealth-Candelero

# Create the virtual environment OUTSIDE the clone (this project forbids a .venv inside the repository).
python -m venv ../oah-venv
../oah-venv/bin/python -m pip install --require-hashes -r requirements-lock.txt   # Windows: ..\oah-venv\Scripts\python.exe
../oah-venv/bin/python -m pip install --no-deps -e .

../oah-venv/bin/python scripts/run_api.py
```

Then open <http://127.0.0.1:8000/health>: it returns `{"status": "ok"}`. `requirements-lock.txt` pins every dependency
with hashes; `docs/environment_setup.md` has the Windows commands and the rules for paths (all paths go through
`oah.paths`, data and caches live outside the repository, in `OAH_DATA_DIR` or the user cache).

What works at this point, with no key and no downloaded data: the public-sandbox routes, indices, the quality-control
report and the synthetic labs. Three optional steps add the rest.

### 1. Real data stores (Waterbase, bathing waters, bathing samples)

The three SQLite stores are built once from public downloads and live outside the repository:

| Store | Command | Cost |
| --- | --- | --- |
| Bathing-water classification | `python scripts/build_bathing_water_store.py` | 1 to 2 minutes (`docs/bathing_water_store.md`) |
| Bathing-water samples | `python scripts/build_bathing_samples_store.py` | about 2.5 minutes, online (`docs/bathing_samples_store.md`) |
| EEA Waterbase | `python scripts/build_waterbase_store.py` | needs the 4.5 GB EEA archive and 7-Zip, tens of minutes (`docs/waterbase_store.md`) |

Each script accepts `--dry-run` to show what it would use. Store locations can be overridden with `OAH_WATERBASE_STORE`,
`OAH_BATHING_WATER_STORE` and `OAH_BATHING_SAMPLES_STORE` (absolute paths). A missing store is reported by the API
(`/catalog`, `/countries`) and the matching index is simply not offered.

To only check that everything starts, `python scripts/make_synthetic_stores.py --output <empty absolute dir>` builds three
tiny stores of **invented** data (for tests and image builds; they must never be shown as real).

### 2. The chat agent

Set `ANTHROPIC_API_KEY` and `OAH_API_KEY` (copy `.env.example` to `.env`; `.env` is never versioned). Once `OAH_API_KEY` is
set, every route except `/health` needs the header `X-API-Key`. The chat is spend-controlled (per-client rate limit and a
daily cap of model calls, `OAH_CHAT_DAILY_CAP`); see `docs/chat_agent.md` and `docs/environment_variables.md`. Without
the Anthropic key the chat answers `503` and the rest of the API works normally.

### 3. Deploy

`docs/deployment.md` is the runbook (Docker image with the stores baked in, Cloud Run, Secret Manager).
`docs/predeploy_checklist.md` is the checklist.

## Run the web app

```bash
cd web
npm ci
npm run dev          # http://localhost:3000, simulated data (a banner says so)
```

The web app never talks to Anthropic and never holds a secret in the browser. To use the real backend set, on the
server side only, `OAH_DATA_MODE=real`, `OAH_BACKEND_URL` (the backend origin) and `OAH_API_KEY` (see `web/env.example`
and `docs/web_app.md`).

## Tests and quality checks

```bash
../oah-venv/bin/python -m pip install -e ".[dev]"
../oah-venv/bin/python -m pytest                          # unit, contract, property, integration, portability
../oah-venv/bin/python -m ruff check src scripts tests
../oah-venv/bin/python -m mypy
(cd web && npm run check)                                 # typecheck, lint, tests
```

`tests/portability/test_static_checks.py` runs ruff and mypy inside the suite. Continuous integration (`.github/workflows`)
runs the backend suite, the web checks and a build check of the container image.

## Repository map

| Path | Content |
| --- | --- |
| `src/oah/` | the backend: `api/`, `chat/`, `waterbase/`, `bathing/`, `bathing_samples/`, `indices/`, `external/`, `i18n/`, `explain/` |
| `web/` | the Next.js web app |
| `docs/` | design, route reference (`api_routes.md`, `openapi.json`), data stores, security review, handoffs |
| `scripts/` | store builders, evaluation scripts, deployment helpers |
| `deploy/`, `Dockerfile` | Cloud Run service file and image |
| `reference/` | read-only official inputs (see `SOURCES.yaml`) |
| `tests/`, `fixtures/` | tests and labelled fixtures |

## Known limits

- This is a demo. Reference values are screening aids, not legal limits; no health or safety statement is made.
- Machine translations of the interface and of the model's answers are checked automatically but have not been reviewed by
  native speakers.
- Real, modelled and synthetic data are labelled and kept apart; results on synthetic data measure the simulator, not
  real-world performance (`oah.synthetic`).
- Rate limits, spend caps and caches are in process memory: the service is meant to run as ONE instance.

## License and attribution

OneAquaHealth's own original code is MIT-licensed; see `LICENSE`.

This project builds on official material from the IEEE OneAquaHealth Global Hackathon 2026,
which is not covered by that license:

- The [hl7-eu/oah](https://github.com/hl7-eu/oah) HL7 FHIR Implementation Guide and public
  sandbox (read-only under `reference/`, not redistributed in this repository) is the official hackathon
  reference IG. Its upstream repository does not declare a license; it is used unmodified, read-only, for the
  hackathon's stated purpose.
- **"OneAquaHealth Key Indicators of Ecosystem and Biological Health — Factsheets Collection"**,
  OneAquaHealth Consortium (2026), Horizon Europe Grant Agreement 101086521.
  [doi.org/10.5281/zenodo.20345207](https://doi.org/10.5281/zenodo.20345207) — CC BY 4.0.
- **"OneAquaHealth Field Sampling Protocols for Urban Stream Ecosystems"**,
  OneAquaHealth Consortium (2026), Horizon Europe Grant Agreement 101086521.
  [doi.org/10.5281/zenodo.20344421](https://doi.org/10.5281/zenodo.20344421) — CC BY 4.0.
- EEA data are published under CC BY 4.0 (EEA legal notice); map tiles and data © OpenStreetMap contributors (ODbL).

See `SOURCES.yaml` (`policy.third_party_notices`) for the full detail behind each entry above.
