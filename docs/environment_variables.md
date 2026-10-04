# Environment variables: convention and contract

## The convention

1. **The example file is the contract.** The example environment file at the repository root lists EVERY variable the
   code reads (`OAH_*` and `ANTHROPIC_API_KEY`). A variable that the code reads and the example does not mention is a
   defect. `tests/unit/test_env_example_contract.py` enforces it by scanning the string literals of `src/oah` and
   failing with the exact missing names.
2. **Commented unless it is a secret.** Every non-secret variable appears as a commented line (`# NAME=value`) that
   shows the default or an example, so that copying the file changes nothing by accident. Secret variables appear as
   an uncommented or commented line that is EMPTY. A variable is uncommented with a value only when the value is a public,
   documented default (the test keeps a short allow-list for that).
3. **No empty values for numeric, URL, path and language settings.** A line such as `OAH_CHAT_DAILY_CAP=` (empty,
   uncommented) is forbidden. Several parsers refuse an empty number or URL and stop the server at start-up (a number
   or the sandbox URL: `invalid literal`, `must use https`), and the ones that tolerate it today may change. To use the
   default, comment the line out or delete it. The test fails on any uncommented empty numeric, URL, path or language
   variable, judged by the name suffix (`_SECONDS`, `_CAP`, `_PER_MINUTE`, `_DAILY`, `_SIZE`, `_REQUESTS`, `_STEPS`,
   `_URL`, `_STORE`, `_DIR`, `_ROOT`, `_PATH`, `_FILE`, `_LANGUAGE`).
4. **Real values live in exactly one place per environment.**

   | Environment | Where real values live |
   |---|---|
   | Local development | the local settings file (the real, unversioned counterpart of the example file) |
   | Backend on Cloud Run | secrets in Secret Manager (referenced by the service file); non-secret settings in the rendered copy of `deploy/cloudrun.service.yaml`, kept outside the repository |
   | Web app on Vercel | Vercel environment variables, SERVER-ONLY (no `NEXT_PUBLIC_` prefix) unless the value is public by design |

   Never in the repository, an image layer, a build argument, the shell history, or client-side code.
5. **Fail fast.** `oah.config.load_settings` validates at start-up: a wrong value (wildcard CORS origin, non-https
   sandbox URL, malformed number, unknown language, relative path where an absolute one is required) raises a clear
   error and the server does not start, instead of running with a silently wrong setting. Out-of-range values that are
   safe to bound (chat steps, timeouts) are lowered to a documented ceiling. The web app must follow the same rule:
   validate its server-only variables when the module loads and throw when one is missing or malformed.
6. **Adding a variable.** Add it to the code, to the example file (commented, with the default and one line of meaning),
   to `docs/` where the behaviour is described, and to the service file when it is a deployment setting. The contract
   test then passes; it fails otherwise.

Secrets today: `OAH_API_KEY` (shared access key) and `ANTHROPIC_API_KEY` (model provider). Anything whose name ends in
`_KEY`, `_TOKEN`, `_SECRET` or `_PASSWORD` is treated as a secret by the test.

## Reference of the variables the code reads

Defaults are those of the code (`src/oah/config.py`, `src/oah/external/settings.py`, `src/oah/paths.py`). "Empty" means
what an empty value does today; the convention above still forbids writing it for the kinds listed in rule 3.

| Group | Variables |
|---|---|
| Secrets | `OAH_API_KEY` (unset: protected routes answer 503), `ANTHROPIC_API_KEY` (unset: chat and explanations answer 503) |
| Access and exposure | `OAH_CORS_ORIGINS` (explicit origins, comma separated, never `*`), `OAH_INSECURE_NO_AUTH` (local testing only; never in a deployed service), `OAH_ENABLE_DOCS`, `OAH_ENABLE_WRITE_ROUTES` (off by default: review decisions and FHIR exports answer 404), `OAH_TRUSTED_PROXIES` (deliberately unset on Cloud Run, see `docs/deployment.md` section 11), `OAH_TRUSTED_PROXY_HOPS` (0 to 5, default 0 = off: trusted proxies counted from the right of `X-Forwarded-For`). `K_SERVICE` is set by Cloud Run, not by you: with it set the service refuses to start unless `OAH_API_KEY` has at least 32 characters (elsewhere a shorter key only logs a warning) |
| Limits and caps | `OAH_RATE_LIMIT_MAX_REQUESTS`, `OAH_RATE_LIMIT_WINDOW_SECONDS`, `OAH_EXPLAIN_RATE_LIMIT_PER_MINUTE`, `OAH_EXPLAIN_DAILY_CAP`, `OAH_EXPLAIN_CACHE_TTL_SECONDS`, `OAH_CHAT_DAILY_CAP`, `OAH_CHAT_RATE_LIMIT_PER_MINUTE`, `OAH_CHAT_MAX_STEPS`, `OAH_CHAT_TIMEOUT_SECONDS` |
| Models and language | `OAH_LLM_MODEL`, `OAH_TRANSLATION_MODEL`, `OAH_TRANSLATION_TIMEOUT_SECONDS`, `OAH_DEFAULT_LANGUAGE` |
| Sandbox | `OAH_SANDBOX_URL` (https; http only for localhost), `OAH_SANDBOX_CACHE_TTL_SECONDS`, `OAH_SANDBOX_MAX_STALE_SECONDS`, `OAH_SANDBOX_WARMUP` |
| Paths (absolute, outside the repository) | `OAH_DATA_DIR`, `OAH_SOURCES_ROOT`, `OAH_TOOLS_DIR`, `OAH_LIMITS_FILE`, `OAH_WATERBASE_STORE`, `OAH_BATHING_WATER_STORE`, `OAH_BATHING_SAMPLES_STORE`, `OAH_SEVENZIP_PATH` |
| External context | `OAH_EXTERNAL_ENABLED`, `OAH_EXTERNAL_OPEN_METEO_ENABLED`, `OAH_EXTERNAL_GLOFAS_ENABLED`, `OAH_EXTERNAL_GBIF_ENABLED`, `OAH_EXTERNAL_TIMEOUT_SECONDS`, `OAH_EXTERNAL_CACHE_TTL_SECONDS`, `OAH_EXTERNAL_CACHE_SIZE`, `OAH_EXTERNAL_OPEN_METEO_PER_MINUTE`, `OAH_EXTERNAL_OPEN_METEO_DAILY`, `OAH_EXTERNAL_GBIF_PER_MINUTE`, `OAH_EXTERNAL_GBIF_DAILY`, `OAH_CONTACT_URL` (https contact page, no e-mail address) |

Precedence in code: real process environment values win over the local settings file.

## Dependencies and runtime pinning

- **Python** is pinned to `>=3.11,<3.13` in `pyproject.toml`; CI and the image use 3.12.
- **Installs come from the hash-pinned lockfile** (`requirements-lock.txt`: every direct and transitive dependency, with
  hashes): CI and the image use `pip install --require-hashes` (the image installs only the runtime subset, with
  `--no-deps`). Procedure and audit: `docs/environment_setup.md`, "Reproducible install and dependency audit".
- **No `latest` tags.** Image tags are explicit (a date or short commit id); the deployment runbook forbids `latest`.
  The base image is pinned by digest: the `PYTHON_IMAGE` argument of the Dockerfile is
  `python:3.12-slim-bookworm@sha256:<digest>` (the digest the last Cloud Build resolved for that tag), so a rebuild gets
  the same base bytes. The trade-off: security patches of the base image are NOT picked up automatically; the digest is
  refreshed on purpose (procedure in `docs/predeploy_checklist.md`, section 5). A static test checks that the default
  keeps a digest.
- **Web app (plan for `web/`).** The same rule applies: commit `package-lock.json`; install with `npm ci` (never
  `npm install`) in CI and on Vercel; pin the Node major version in `package.json` under `engines` (for example
  `"node": "22.x"`, the version chosen when `web/` is created) and select the same major in the Vercel project settings; use
  exact or lockfile-resolved versions and run `npm audit --omit=dev` before each deployment (see
  `docs/predeploy_checklist.md`). This paragraph is a plan: `web/` does not exist yet, so none of it is verified.
