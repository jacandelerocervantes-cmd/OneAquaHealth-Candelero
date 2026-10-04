# Security review

Manual review conducted by Claude (auditor/temporary implementer) while Antigravity and Codex
were at zero quota. No `/security-review` skill run was used: this repository has no git
commits (per `AGENTS.md`, agents do not commit), so a diff-based review skill has nothing to
diff against. Findings below were produced by reading the code that handles external input
(the API layer, the sandbox client, the official-validator subprocess wrapper) and by checking
the exact pinned dependency versions against public vulnerability databases.

Scope: everything added or changed while both coding agents were unavailable (privacy, risk,
api, the pipeline integration) plus the dependencies those blocks newly exposed to network
traffic (fastapi, starlette, uvicorn, httpx are now serving real requests via `scripts/run_api.py`,
not just used internally).

## Findings

### 1. [FIXED] `SandboxClient.get_resource` accepted any non-empty `resource_id`

`resource_id` was interpolated directly into a URL path segment with only a truthiness check,
no character validation. Not currently reachable from untrusted input (only
`scripts/capture_fixtures.py` calls it, always with hardcoded literal ids), but a latent
weakness: a future caller wiring user input into this method (an API endpoint, for example)
would have had no protection against path-traversal-shaped ids (`"../../x"`) or other
FHIR-id-illegal characters reaching an outbound HTTP request. Fixed by restricting
`resource_id` to the FHIR id charset (`[A-Za-z0-9\-.]`), matching the validation `pages()`
already applies to `resource_type`. Tests added in `tests/unit/test_sandbox_client.py`.

### 2. [FIXED] `POST /fhir/export` disclosed the absolute local filesystem path

The response included `"written_to": str(target)`, an absolute path that, under the default
data directory, contains the local Windows username. On a local-only demo API this is low
severity, but there is no reason to expose it. Fixed to return just the file name
(`target.name`), relative to the already-documented data directory. Test added in
`tests/unit/test_api.py`.

### 3. [FIXED] Pinned Starlette 0.46.2 (transitive via fastapi==0.115.12) was affected by CVE-2026-48710 ("BadHost")

**Source**: [GitHub Security Advisory GHSA-86qp-5c8j-p5mr](https://github.com/advisories/GHSA-86qp-5c8j-p5mr) /
[CVE-2026-48710](https://www.miggo.io/vulnerability-database/cve/CVE-2026-48710). Verified the
exact installed version in the project's own pinned environment: `pip show starlette` reports
`0.46.2`. The advisory states the fix ships in Starlette **1.0.1**.

**What it is**: Starlette reconstructs `request.url` from the `Host` header without validating
it. A malformed Host header (containing `/`, `?`, or `#`) can make `request.url.path` differ
from the path Starlette actually routed to. Code that makes security decisions based on
`request.url` rather than the raw ASGI scope path can be bypassed.

**Exploitability against this specific application, assessed by reading our own code, not
assumed**: `src/oah/api/app.py` contains zero logic that inspects `request.url`, the `Host`
header, or any path-based access-control check anywhere -- no `TrustedHostMiddleware`, no
route guards keyed on the reconstructed URL. Every endpoint is already open to any caller
regardless of Host header, which is the pre-existing, already-documented "no authentication"
gap in `docs/architecture.md`. This CVE's specific bypass mechanism (defeating a URL-based
security check) therefore does not add a *new* exploitable path for this application as it
stands today, because there is no such check here to defeat. It remains a real vulnerability
in a directly network-facing dependency and should still be fixed; the assessment above
explains why it was not treated as an emergency block-everything finding, not why it should be
ignored.

**Fix applied and verified**, at the user's explicit request. `fastapi==0.141.1` (latest
available at the time) only requires `starlette>=0.46.0` with no upper bound, so bumping
FastAPI alone would NOT have picked up the fix -- Starlette had to be pinned explicitly.
Verification steps, in order, all with real evidence (no step skipped or assumed):
1. Dry-run resolution (`pip install --dry-run --only-binary=:all:`) of
   `fastapi==0.141.1` + `starlette==1.6.0` (the latest, well above the 1.0.1 fix) against the
   full existing pin set (`httpx`, `fhir.resources`, `pydantic`, `pyyaml`, `numpy`, `networkx`,
   `uvicorn`) -- resolved cleanly, no conflicts reported.
2. Installed both for real in the isolated audit environment, updated `pyproject.toml`'s
   pins to match, reinstalled the project itself in editable mode, and ran `pip check` --
   reported "No broken requirements found."
3. Full test suite: 221 passed, 1 skipped (unchanged from before the upgrade).
   `ruff check --select F`: clean.
4. Live smoke test against the real sandbox with the upgraded dependencies: `/qc/report`,
   `/indices/Loc-Almyros`, `/risk/Loc-Almyros-Coast`, and `POST /fhir/export` all returned
   values identical to the pre-upgrade run (CCME WQI 19.93, risk 0.4382, 163 DetectedIssue),
   confirming the upgrade changed nothing behaviorally.
5. Started a *real* `uvicorn` server process (not just `TestClient`, which bypasses the ASGI
   server layer) and sent it a real HTTP request over a socket: `GET /health` returned
   `200 {"status": "ok"}`.
6. Confirmed the installed version directly: `starlette.__version__ == "1.6.0"`,
   `fastapi.__version__ == "0.141.1"`.

**New, low-severity follow-up noted, not yet acted on**: the upgrade surfaced a
`StarletteDeprecationWarning` that `httpx` support in `starlette.testclient` (used only by
`fastapi.testclient.TestClient` in our test suite, never in production code) is deprecated in
favor of a package named `httpx2`. Tests still pass; this is a future maintenance item, not a
security finding, and is recorded here so it is not forgotten.

### 4. [CONFIRMED, LOW PRACTICAL RISK TODAY] Multipart-form-related Starlette/python-multipart CVEs

**Sources**: [CVE-2025-54121](https://github.com/advisories/GHSA-2c2j-9gv5-cj73) (Starlette,
fixed in 0.47.2 -- blocks the event loop parsing large multipart files to disk),
[CVE-2024-47874](https://security.snyk.io/vuln/SNYK-PYTHON-STARLETTE-8186175) (Starlette,
unbounded buffering of multipart text fields, fixed in 0.40.0),
[CVE-2023-30798](https://security.snyk.io/vuln/SNYK-PYTHON-STARLETTE-3319937) (Starlette,
unbounded multipart field/file count, fixed in 0.25.0).

**Assessment**: none of these are reachable through this application today. No route in
`src/oah/api/app.py` declares a `File`, `UploadFile`, or `Form` parameter, and none of our own
code calls `request.form()`. Starlette only invokes its multipart parser for a request when
something in the stack actually reads the form body, which nothing here does. Our own
`python-multipart` dependency is not even installed (checked: it is not in `pyproject.toml`
and `pip show python-multipart` finds nothing in the audit environment). These findings are
recorded for completeness and because the vulnerable *code* is present transitively via
Starlette regardless of whether our routes exercise it -- if a future block adds a file-upload
endpoint, this section must be re-read before doing so.

### 5. Reviewed and found no issue

- **SQL injection**: `src/oah/store/review_store.py` uses parameterized queries (`?`
  placeholders) exclusively; no string-formatted SQL anywhere in the file.
- **Shell injection**: every `subprocess.run` call in the project (`oah/fhir/official_validator.py`,
  `scripts/build_ig.py`) passes a list of arguments, never `shell=True`, and never builds a
  command string via concatenation.
- **Secrets**: grepped `src/`, `scripts/`, `tests/`, and `docs/*.md` for password/secret/API-key/
  bearer-token patterns; found none. The sandbox is public and unauthenticated by design, so
  no credential is needed anywhere in this codebase. `.env` is git-ignored and does not
  currently exist in the repository.
- **CORS**: no `CORSMiddleware` is registered; FastAPI therefore never sets
  `Access-Control-Allow-Origin`, so a browser cannot read cross-origin responses from this API.
  This is not a substitute for real access control and is already listed as a known gap in
  `docs/architecture.md`.

## 6. Prompt injection, LLM spend and abuse controls (2026-09-26)

This section supersedes the "Known gaps" paragraph below and the CORS sentence in finding 5: a CORS policy, optional
shared-secret authentication and a rate limiter now exist. What existed before this date, and what was added:

| Risk | Before | Now | Residual risk |
| --- | --- | --- | --- |
| Instructions hidden in data that reaches the model (indirect prompt injection via a sandbox id, reference, note or code display) | Nothing: strings went to the prompt unchanged | `oah.explain.safety.sanitize_evidence` (Unicode normalisation, control and invisible characters removed, instruction-like text and URLs replaced, string/key/depth/size caps); the system prompts declare EVIDENCE untrusted; the block is delimited and `<`/`>` are escaped so it cannot be closed from inside | A pattern list cannot see new wording. Measured on 36 authored payloads (English, Spanish, French, Italian, German, invisible characters, markup): all neutralised; on 29 benign strings: no false alarms; 6 authored evasions pass (leetspeak, base64, paraphrase, Norwegian, Dutch, Greek). This measures the patterns against the authors' imagination, not against attackers |
| The model obeys an injection anyway, or writes something unsafe to render | Only the number check | `guard_output` flags URLs, HTML, markdown links, code blocks, leaked instructions, an `assess` answer without the required `Concern level:` line, and over-long text; flags are returned in `output_flags`, the text is never altered | Flags are advice: **the frontend must render explanations as plain text, never as HTML** (requirement for the frontend phase). No real model has been tested against injected evidence |
| A caller or a loop burns paid LLM calls | One shared limit of 60 requests a minute for everything | `/explain/*` has its own per-host budget (5 a minute), a rolling 24-hour cap on real model calls (default 100), a response cache for identical requests (600 s; cache hits are free), 30 s timeout and one retry on the Anthropic client, and an oversized-evidence refusal (422) before any call | The counters live in process memory: a restart resets them, and several workers or hosts do not share them. The real hard cap is a spend limit in the Anthropic console; set one |
| Abuse of the general API | Sliding-window limiter, no `Retry-After`, no defensive headers | `Retry-After` on both 429s; `X-Content-Type-Options`, `X-Frame-Options`, `Referrer-Policy`, `Cache-Control: no-store` and a strict `Content-Security-Policy` on every response (not on the interactive docs) | The limiter keys on the connecting host: behind a reverse proxy all clients share one bucket, and `X-Forwarded-For` is not trusted. There is no server-side request body size limit beyond the server defaults; the only JSON body (`/review/{id}/decide`) is bounded |
| Hostile text stored in the audit trail | `reviewer_id` and `final_label` accepted any non-empty string | Both limited to 128 characters and to word characters, spaces and a few separators (no control characters, markup or newlines) | Free text elsewhere is not accepted by the API |
| Unauthenticated access | `X-API-Key` check exists but is **off unless `OAH_API_KEY` is set** | Unchanged | Set `OAH_API_KEY` before exposing the API beyond localhost: with the Anthropic key configured and no API key, anyone who can reach the port can spend against the daily cap |

Not addressed: TLS termination, per-user identity and scoped permissions, a distributed rate limiter, and a real-model
injection test (about four calls; needs approval because it spends the API budget). Cost guidance from the two real runs:
roughly 1,300 tokens per call, so a few cents per call at most; with a small budget set `OAH_EXPLAIN_DAILY_CAP` low
(for example 20).

## Known gaps (older text, kept for the record; see section 6 for the current state)

No authentication, no CORS policy, no real rate limiting beyond bounded query parameters on
one endpoint. This is a local/demo API for a hackathon submission, not a hardened public
deployment. If it is ever exposed beyond `127.0.0.1`, all three must be addressed first, in
addition to finding #3 above.
