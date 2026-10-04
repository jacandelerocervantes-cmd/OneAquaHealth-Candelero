# Pre-deploy go/no-go checklist

The maintainer runs this list before EVERY deployment of the backend (Cloud Run, runbook `docs/deployment.md`) and of the
web app (Vercel, design `docs/web_app_design.md`). One unchecked box, or a box without its evidence, is a no-go: stop,
fix, and start the list again. The list is written for THIS project: one Cloud Run instance, a service that stays
private until the maintainer decides otherwise, one shared access key, Secret Manager, three SQLite stores baked into the
image, and a Next.js app on Vercel whose server-side route handlers are the only callers of the backend.

Conventions: `<PLACEHOLDER>` values are yours to fill in (never commit them); commands are PowerShell, written down here
and NOT executed by the authors of this document. "Evidence" is what you write in the ledger entry of the deployment (a
pasted line of output, a screenshot reference, a revision name), never a secret value.

## 1. Ingress and authentication decision

Who may invoke the backend? Decide it explicitly each time; the default answer is "only the maintainer".

- [ ] The current invoker policy is known and matches the decision. Evidence: output of
      `gcloud run services get-iam-policy oah-backend --region=<REGION> --project=<PROJECT_ID>` (private: no `allUsers`
      member; public: `allUsers` with `roles/run.invoker`, accepted knowingly).
- [ ] If the service is to be public (needed once the Vercel servers call it, because they have no Google identity), the
      grant is a deliberate MANUAL step done by the maintainer in their own shell, never by an agent. The exact command
      (placeholder values, not executed here; it is the one in `docs/deployment.md` section 5):
      `gcloud run services add-iam-policy-binding oah-backend --region=<REGION> --project=<PROJECT_ID> --member=allUsers --role=roles/run.invoker`.
      The repository's hook `hooks/block-network-exposure.sh` blocks it for agents BY DESIGN, together with every other
      route to public access: `--allow-unauthenticated`, an `add-iam-policy-binding` naming `allUsers` or
      `allAuthenticatedUsers` (also the `beta` and `alpha` forms), `set-iam-policy` on a service, `--no-invoker-iam-check`
      and `--ingress all` / `--ingress=all`. The block is not a bug to work around: run the command yourself.
      Evidence: the date and the maintainer's note in the ledger.
- [ ] Limits of the hooks, so nobody relies on them too much: they read the TEXT of a command, not its effect. Shell
      aliases and functions, a command assembled in a variable, `eval` or encoded commands, a client library call and
      the cloud console are not seen. The hooks fail CLOSED: without `jq` (or with an unreadable payload) every guarded
      tool call is blocked with a message naming what to install (Windows: `winget install jqlang.jq`; Debian or
      Ubuntu: `sudo apt-get install jq`; macOS: `brew install jq`). They run for the Bash and PowerShell tools; the
      secrets hook also runs for Read, Edit, Write, NotebookEdit, Grep and Glob. A Grep over a directory is only as safe
      as ripgrep's ignore rules. The IAM policy output above is the real control; the hooks are a first barrier against
      an agent. Not covered by the hooks and worth a `permissions.deny` rule: edits to `hooks/` and `.claude/settings.json`
      (the maintainer's decision; see the recommendation in the ledger entry of the hook hardening).
- [ ] What the application enforces on its own, whatever the invoker policy says (the reason public invocation is
      acceptable): every route except `/health` requires the shared `X-API-Key` (constant-time comparison); with
      `OAH_API_KEY` unset the protected routes answer 503 and the service never runs open unless
      `OAH_INSECURE_NO_AUTH` is set; the general, explanation and chat rate limits; the daily model caps; `/docs`,
      `/redoc` and `/openapi.json` are off unless `OAH_ENABLE_DOCS` is set. Evidence: `OAH_INSECURE_NO_AUTH` and
      `OAH_ENABLE_DOCS` are absent from the rendered service file (`Select-String` on the rendered copy prints nothing),
      and the smoke tests of section 10 (401 without a key, 404 on `/docs`).
- [ ] Ingress is `all` knowingly (no private path exists from Vercel) and the container runs unprivileged. Evidence:
      `gcloud run services describe oah-backend --region=<REGION> --project=<PROJECT_ID>` shows the ingress annotation
      and the service account `oah-backend-run`.
- [ ] The Vercel project itself is protected as decided (the shared "Judge account" access in front of the app). A
      deployment without that protection exposes the route handlers, and through them the backend key's reach.
      Evidence: opening the production URL in a private window asks for the access step.

## 2. CORS

- [ ] `OAH_CORS_ORIGINS` in the rendered service file lists explicit origins only: the Vercel production origin (scheme
      and host, no path, no trailing slash) and nothing else in production. Never `*` (the code refuses it at
      start-up), never a preview-URL pattern. Evidence: the rendered line.
- [ ] The localhost origins of the first deploy are gone before the service is made public. Evidence: same line.
- [ ] Reminder of what CORS is here: the browser never calls the backend (it calls Vercel's same-origin route
      handlers), so CORS is defence in depth, not access control. A browser console error about CORS on a backend URL
      means the web app is calling the backend from the browser, which is a bug to fix, not a setting to loosen.

## 3. HTTP security headers

What the BACKEND sets on every response (`src/oah/api/middleware.py`; pinned by unit tests):

| Header | Value |
|---|---|
| `X-Content-Type-Options` | `nosniff` |
| `X-Frame-Options` | `DENY` |
| `Referrer-Policy` | `no-referrer` |
| `Cache-Control` | `no-store` |
| `Content-Security-Policy` | `default-src 'none'; frame-ancestors 'none'` (not on the docs paths) |
| `Strict-Transport-Security` | `max-age=31536000`, only when the request is https or a trusted proxy says so (Cloud Run's front end serves https only; the app sees plain http behind it, so check the public URL, not the container) |

What the WEB APP (Next.js on Vercel) must set itself, because Vercel does not add them for you; configure them in the
`headers()` of `next.config` (or in middleware) for every route:

| Header | Required value or rule |
|---|---|
| `Content-Security-Policy` | a policy that lists only what the app uses: `default-src 'self'`, scripts from `'self'` (a nonce for any inline script), `connect-src 'self'`, `img-src` limited to `'self'`, `data:` and the OpenStreetMap tile host while the map exists, `frame-ancestors 'none'`, `base-uri 'self'`, `form-action 'self'`, `object-src 'none'`. No `'unsafe-eval'`. Answers are rendered as plain text, so no HTML is ever injected. |
| `Referrer-Policy` | `strict-origin-when-cross-origin` or stricter (map tile requests will carry the origin only) |
| `X-Content-Type-Options` | `nosniff` |
| `frame-ancestors` (inside the CSP above) | `'none'`; also send `X-Frame-Options: DENY` for old browsers |
| `Strict-Transport-Security` | Vercel serves https only; add `max-age=31536000` explicitly |
| `Permissions-Policy` | switch off what the app does not use (camera, microphone, geolocation, payment) |

- [ ] Backend headers present on the deployed service. Evidence: `curl.exe -sS -D - -o NUL <SERVICE_URL>/health` shows
      the five always-on headers above (the service URL needs the identity token while it is private).
- [ ] Web app headers present on the deployed app. Evidence: `curl.exe -sS -D - -o NUL <WEB_URL>/` shows the CSP,
      Referrer-Policy, nosniff and `frame-ancestors`; a CSP report (or the browser console) shows no violation on the
      main screen, the map pane and a chat answer.

## 4. Secrets

Where each secret lives, and nowhere else:

| Secret | Backend | Web app | Local development |
|---|---|---|---|
| Shared access key (`OAH_API_KEY`) | Secret Manager `oah-api-key`, injected into the Cloud Run revision | Vercel environment variable, server-only (no `NEXT_PUBLIC_` prefix) | the local settings file (not versioned) |
| Model provider key (`ANTHROPIC_API_KEY`) | Secret Manager `oah-anthropic-api-key` | never (the web app does not call the model) | the local settings file (not versioned) |
| Backend URL | plain service setting | Vercel server-only variable | local settings file |

- [ ] No secret value is in the image. Evidence: the Dockerfile never copies a settings file, `.dockerignore` excludes the
      dotenv patterns, and the CI job `deploy-checks` ran green on the commit being deployed.
- [ ] No secret value is in browser code: no `NEXT_PUBLIC_` variable holds a key or the backend URL with a credential,
      and the built client bundle does not contain the key. Evidence: a search of the build output for the first
      characters of the key prints nothing (do not paste the characters into the ledger), and the list of
      `NEXT_PUBLIC_` names in the Vercel project is reviewed and contains only values public by design.
- [ ] No secret value is in the repository or its history. Evidence: `tests/portability/test_no_forbidden_tracked_files.py`
      and `tests/unit/test_env_example_contract.py` pass; the example environment file holds no real value.
- [ ] The runtime service account `oah-backend-run` has no project role and only `secretAccessor` on the two secrets.
      Evidence: `gcloud projects get-iam-policy <PROJECT_ID>` does not list it; each secret's policy lists only it.
- [ ] If a key was shown anywhere it should not have been (chat, log, screenshot), it was rotated before this deploy
      (new Secret Manager version, new Vercel variable value, new revision and deployment).

## 5. Image and dependency scan

Commands only; they have not been executed in the preparation of this document.

- [ ] Python dependencies: `python -m pip_audit -r requirements-lock.txt --disable-pip --no-deps` reports no known
      vulnerabilities (the CI job `dependency-audit` runs the same command, adds `--strict`, and is blocking). Known
      exceptions live only in `security/pip-audit-ignore.txt`: one advisory per line with a reason and a review-by date
      (a line without them fails the job and a unit test); the list is empty today. Evidence: its last green run on the
      commit being deployed.
- [ ] Python install is exactly the lockfile (hash-pinned; see "Dependencies and runtime pinning" in
      `docs/environment_variables.md`). Evidence: the image build log shows the `--require-hashes` install.
- [ ] Web dependencies (once `web/` exists): `npm audit --omit=dev` in `web/` reports no high or critical finding that
      applies to the shipped code, and `npm ci` (not `npm install`) was used for the build. Evidence: the command output
      and the Vercel build log.
- [ ] Image scan of the pushed tag with the cloud provider's scanner (Artifact Registry vulnerability scanning), and the
      deploy is GATED on it: do not deploy a tag whose scan is missing or shows a critical finding with a fix available.
      One-time setup (placeholders, not executed here; check the current commands in the provider's documentation):
      `gcloud services enable containerscanning.googleapis.com --project=<PROJECT_ID>` (images pushed after the API is
      enabled are scanned automatically; earlier ones are not). Per deploy, after the push and before the deploy:
      `gcloud artifacts docker images describe <IMAGE>@<IMAGE_DIGEST> --show-package-vulnerability --project=<PROJECT_ID>`
      (or `gcloud artifacts docker images list-vulnerabilities <IMAGE>@<IMAGE_DIGEST>`). The scan is asynchronous: an empty
      result right after the push means "not scanned yet", not "clean". The gate is manual until a pipeline exists: read the
      output and write the verdict down. Evidence: no critical finding with a fix available, or each one accepted in writing.
- [ ] The image tag deployed is an explicit tag (a date or short commit id), never `latest`, and the digest was
      recorded. The base image is pinned by digest in the Dockerfile (`ARG PYTHON_IMAGE`; the tag stays in a comment).
- [ ] Refreshing the base image digest, on purpose (monthly, and whenever a scan or advisory names the base image):
      resolve what the tag points to now (for example `docker buildx imagetools inspect python:3.12-slim-bookworm`, or the
      line of a Cloud Build log that names the `sha256:` of the base), read what changed (Python and Debian patch levels),
      put the new `@sha256:<digest>` into the `ARG PYTHON_IMAGE` default of the Dockerfile, run
      `python -m pytest -q tests/unit/test_deploy_files.py`, build and smoke-test (section 10), and record the old and new
      digest in the ledger so a rollback can restore the old one. Commands are placeholders, not executed by the authors.
      Trade-off: pinning stops silent base-image changes but also stops automatic security patches, so an unrefreshed
      digest slowly accumulates known vulnerabilities (the image scan above shows them).
- [ ] Secret versions in the service file are `latest` today (`oah-api-key`, `oah-anthropic-api-key`). Trade-off: `latest`
      makes a rotation a new revision with no file edit, but a revision then depends on whatever is newest when an
      instance starts (a restart can pick up a version nobody tested, and a rollback to an older revision still reads the
      newest secret). Pinning a numeric version (for example `key: "3"`) makes each revision reproducible and a rollback
      restores the old key too, at the cost of editing the service file and deploying a new revision for every rotation,
      and of keeping old versions enabled while any revision references them. Decision for the maintainer; `latest` stays
      for now (the unit test pins it).
- [ ] Restart alerting (idea, not set up): the daily model caps, the rate limits, the response caches and the audit hash
      chain live in process memory, so every instance restart resets the spend caps. Create a Cloud Monitoring alert on
      instance restarts of `oah-backend` (for example a log-based metric on the start-up log line, or the instance count
      metric of Cloud Run changing while `minScale` = 1) that notifies the maintainer, so an unexpected restart (out of
      memory, a crash loop, a deploy nobody made) is noticed while the provider-side spend limit is still only a backstop.
      Evidence: the alert policy's name, once it exists. Metric names must be checked against the current provider
      documentation.

## 6. Model spend controls

- [ ] Daily caps and per-minute limits are set explicitly in the rendered service file, not left to defaults:
      `OAH_CHAT_DAILY_CAP`, `OAH_EXPLAIN_DAILY_CAP`, `OAH_CHAT_RATE_LIMIT_PER_MINUTE`,
      `OAH_EXPLAIN_RATE_LIMIT_PER_MINUTE`, `OAH_CHAT_MAX_STEPS` (model calls per conversation; the code lowers values
      above its ceiling), `OAH_CHAT_TIMEOUT_SECONDS`, `OAH_TRANSLATION_TIMEOUT_SECONDS`. Evidence: the rendered lines.
- [ ] The service is still ONE instance (`minScale` = `maxScale` = 1, one uvicorn worker). The caps and limits live in
      process memory, so a second instance would double them. Evidence: `gcloud run services describe` shows both
      scale annotations at 1.
- [ ] The caps are global for the demo, and a restart resets them (they are in memory). A provider-side spend limit on
      the model account is set as the real ceiling. Evidence: the maintainer confirms the limit in the provider console.
- [ ] A budget alert exists on the Google Cloud billing account for the project. Evidence: its name.
- [ ] Vercel side: the per-visitor limit (firewall rule or a limit in the route handler) is on, because the backend
      limits are shared between all visitors (it sees Google's front end as the caller).

## 7. External-provider duties

- [ ] Open-Meteo: wherever weather or discharge data are shown, a visible link `Weather data by Open-Meteo.com` to
      `https://open-meteo.com/`, and the note that data were aggregated to months. Non-commercial use only: no advertising
      or subscriptions on the site. Evidence: screenshot of the weather answer and of the About and attributions page.
- [ ] GBIF: each record shows its licence as returned, the dataset and the citation text; non-commercial records are
      marked. Evidence: screenshot of a species answer.
- [ ] EEA data (the three stores): the attribution string of the response is shown next to the data. OpenStreetMap tiles
      carry their required attribution on the map pane. The HL7 Europe sandbox is credited in About and attributions.
- [ ] `OAH_CONTACT_URL` is a valid https contact page (no credentials, no query, at most 200 characters; never an
      e-mail address), set only in the rendered copy. The code puts it in the User-Agent of every outbound call.
      Evidence: the rendered line, and the start-up log shows no error.
- [ ] The wording of the GloFAS credit and the GBIF terms is confirmed (still open in `docs/external_context.md`).

## 8. Data honesty gates

- [ ] Every answer and every index shows its origin label: real, external (modelled or opportunistic) or synthetic.
      Synthetic labs are labelled as synthetic and never presented as real-world performance. Evidence: screenshots of
      one index of each kind.
- [ ] No health or safety verdict anywhere: results are screening against limits, not compliance, and the fixed
      disclaimer closes every answer. No numbers on sidebar entries. An `unsafe`-marked answer is never rendered.
- [ ] A period outside the data range is reported as such, never shifted; indices that do not apply to the selected
      country are hidden (the catalogue route decides), not shown empty. Evidence: ask for a period outside the range and
      for a country without an index.
- [ ] The "Sources and method" block is filled from route metadata, never written by the model. Evidence: one answer
      inspected.

## 9. Rollback plan

Decide the rollback target BEFORE deploying: write down the previous revision and the previous deployment now.

- [ ] Backend (Cloud Run): route traffic back to the previous revision. Previous revision recorded:
      `<PREVIOUS_REVISION>`. Command (placeholder, not executed here):
      `gcloud run services update-traffic oah-backend --region=<REGION> --project=<PROJECT_ID> --to-revisions=<PREVIOUS_REVISION>=100`.
      Old image tags are kept until the new one is accepted.
- [ ] Web app (Vercel): promote the previous deployment. Previous deployment recorded: `<PREVIOUS_DEPLOYMENT_URL>`.
      Command (placeholder, not executed here): `vercel promote <PREVIOUS_DEPLOYMENT_URL>`, or the Promote action on
      that deployment in the Vercel dashboard.
- [ ] Order: if a backend change and a web change go together, deploy the backend first (additive changes only), then the
      web app; roll back in the reverse order. A secret rotation is not rolled back by a revision: restore the old secret
      version and redeploy.

## 10. Smoke tests

Run against the deployed URLs, with the key read from a hidden prompt (`docs/deployment.md` section 8), never pasted.

- [ ] `GET /health` answers 200 `{"status":"ok"}` without a key.
- [ ] `GET /countries` answers 401 without the key and with a wrong key; 200 with the right one.
- [ ] `GET /docs` and `GET /openapi.json` answer 404.
- [ ] `GET /catalog?country=GR` (key) lists the families; a country outside Greece, Italy and Norway answers 422.
- [ ] `GET /sites?country=GR&limit=3` (key) returns at most three sites; `GET /languages` returns the 26 languages.
- [ ] One chat question through the WEB app (not by calling the backend directly): answer with origin tags, Sources and
      method block, disclaimer. Counted against the daily cap, so do it once.
- [ ] From the browser's network tab, every request goes to the web app's own origin; none goes to the backend URL and
      no request carries an `X-API-Key` header.
- [ ] Cloud Run logs show a clean start and no error for the first requests (`gcloud run services logs read oah-backend
      --region=<REGION> --project=<PROJECT_ID> --limit=50`).
- [ ] Memory utilisation after the first requests is within the budget of `docs/deployment.md` section 10.

## What is NOT verified by this checklist

- It is a list of checks, not their results: nothing in it has been run for a specific release, and every command is
  written from knowledge of the tools, not tested against their help output.
- The Next.js app does not exist yet; the header values for it are a requirement to implement, not an observed state.
- The Artifact Registry scanning command, the `vercel promote` form and the Cloud Monitoring names must be checked
  against the current provider documentation before they are relied on.
- The shield provided by the guard hooks is partial (section 1 and `tests/unit/test_guard_hooks.py`): they stop an AGENT,
  not the maintainer, and not every spelling of a dangerous command. Their wiring for the PowerShell tool and the
  Grep, Glob and NotebookEdit tools, and the `${CLAUDE_PROJECT_DIR:-.}` command form, were checked by unit tests that
  imitate Claude Code's payload, not in a live Claude Code session; the Linux run is observed only in CI.
- Real behaviour of Cloud Run's front end (peer addresses, memory accounting of image layers) and Vercel's limits for your
  plan was not measured.
- Legal and licence wording for datasets and providers is not reviewed by this checklist (it only requires the
  attributions the code and the provider documents already name).
