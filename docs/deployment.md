# Deployment runbook (Cloud Run)

This is the runbook that `Dockerfile` and `deploy/cloudrun.service.yaml` point to. It deploys the backend as ONE
container on Google Cloud Run, with the three prebuilt SQLite stores baked into the image and two Secret Manager
secrets. The web app (Vercel) calls the service server-side. The service also makes outbound https calls to three
public hosts for the optional external context (section 12).

Placeholders, used everywhere in this file and in the service file (replace them yourself; never commit the values):
`<PROJECT_ID>`, `<REGION>`, `<REPOSITORY>`, `<TAG>`, `<VERCEL_ORIGIN>`, `<CONTACT_URL>`. Two more appear only in commands:
`<STAGE_DIR>` (the staged stores) and `<IMAGE>` (`<REGION>-docker.pkg.dev/<PROJECT_ID>/<REPOSITORY>/oah-backend:<TAG>`).

IMPORTANT: no command in this file has been executed. No image was built and nothing was deployed (see
"What was NOT verified" at the end). Read every command before you run it. Commands use PowerShell (the maintainer's
shell) unless marked `bash`.

## 1. Prerequisites

- A Google Cloud project with billing, and these services enabled: Cloud Run, Artifact Registry, Secret Manager and,
  for the recommended build path, Cloud Build.
- `gcloud` signed in to the account that owns the project (`gcloud auth list`); do the work in a shell where
  `gcloud config get-value project` is the intended project.
- Python 3.12 with the project installed in the development virtual environment (the staging script imports `oah`).
- All three real stores built and valid (see `docs/waterbase_store.md`, `docs/bathing_water_store.md` and
  `docs/bathing_samples_store.md`). Their default names are `waterbase_icm_2026.sqlite`, `bathing_water_2025.sqlite`
  and `bathing_samples_discodata.sqlite`; the image expects exactly these names. The samples store is built by a
  download of about two minutes (`python scripts/build_bathing_samples_store.py`, about 223 MB received, resumable),
  needs the EEA Discodata service to be up, and gives a file of about 84 MB (83,603,456 bytes on 2026-10-03); the two
  Eurostat-archive stores are the slow ones (7-Zip and a 4.5 GB archive).
- Optional: Docker with `buildx` (only for the local build; the engine may be off, then use Cloud Build).

Variables used by the commands below (PowerShell; set them once per session):

```powershell
$ProjectId = "<PROJECT_ID>"
$Region    = "<REGION>"
$Repo      = "<REPOSITORY>"
$Tag       = "<TAG>"            # for example a date or a short commit id; never "latest"
$Image     = "$Region-docker.pkg.dev/$ProjectId/$Repo/oah-backend:$Tag"
$Stage     = "<STAGE_DIR>"      # absolute, OUTSIDE the repository
```

## 2. Stage the stores

The image build needs the three stores plus a manifest in one folder outside the repository.

```powershell
python scripts/stage_deploy_stores.py --dry-run                 # checks the three stores, copies nothing
python scripts/stage_deploy_stores.py --output $Stage           # copies them and writes manifest.json
```

The script refuses to continue when a store is missing, unreadable, damaged (SQLite `quick_check`) or at another
schema version than the code reads (Waterbase 3, bathing water 1, bathing samples 1); it refuses an output folder
inside the repository or equal to a source folder. `manifest.json` lists, per store, the file name, the container
path, the size, the SHA-256, the schema version, the build date and the edition. No host path is written. A re-run is
idempotent: the stores are copied through a temporary name and renamed, so the folder never holds a half-written
store.

Expected output of the dry run (shape only; sizes and dates are those of YOUR stores, the samples line below is the
size observed on 2026-10-03):

```text
waterbase: waterbase_icm_2026.sqlite schema 3 built <date> <bytes> bytes
bathing_water: bathing_water_2025.sqlite schema 1 built <date> <bytes> bytes
bathing_samples: bathing_samples_discodata.sqlite schema 2 built <date> 137486336 bytes
dry run: all stores are valid; nothing was copied (staging directory would be <STAGE_DIR>)
```

A real run prints the same three lines, then `staged in <STAGE_DIR>`. The staged folder must hold exactly four files:
the three `.sqlite` stores and `manifest.json`.

Keep the manifest: it is what ties an image tag to the data it contains. Record the tag and the three SHA-256 values in
the handoff ledger.

Image size to expect (an estimate, NOT measured, since no image was built): about 260 MiB of stores (160 MiB, 19 MiB and
84 MiB on disk), plus the slim Python base image and the runtime packages (numpy, pydantic, fastapi, anthropic and their
dependencies), so very roughly 0.5 GiB uncompressed; Artifact Registry stores it compressed (SQLite compresses
moderately). Build time is dominated by the dependency installation and the push of the stores layer; the stores layer
is the last `COPY` and is only rebuilt when a store changes, so a code-only rebuild reuses it from the build cache when
the cache is available (it is not kept between Cloud Build runs unless you configure it).

## 3. Google Cloud resources (once)

### 3.1 Artifact Registry repository

```powershell
gcloud artifacts repositories create $Repo --repository-format=docker --location=$Region --project=$ProjectId `
  --description="OneAquaHealth backend images"
```

### 3.2 Dedicated service account with no project roles

```powershell
gcloud iam service-accounts create oah-backend-run --project=$ProjectId `
  --display-name="OneAquaHealth backend (Cloud Run runtime)"
$Sa = "oah-backend-run@$ProjectId.iam.gserviceaccount.com"
```

Do NOT grant it any project-level role. Its only permission is `roles/secretmanager.secretAccessor` on each of the two
secrets (section 3.3). The account that deploys the service needs `roles/iam.serviceAccountUser` on this service
account (a project owner already has it); do not widen anything else "just in case".

### 3.3 The two secrets

The names are fixed by the service file: `oah-anthropic-api-key` and `oah-api-key`. The commands read each value from a
file you control, never from the command line, so nothing is printed and no value reaches the shell history. The file
is written WITHOUT a trailing newline (a newline would become part of the key) and deleted afterwards.

```powershell
gcloud secrets create oah-anthropic-api-key --replication-policy=automatic --project=$ProjectId
gcloud secrets create oah-api-key           --replication-policy=automatic --project=$ProjectId

$File = Join-Path $env:TEMP "oah-secret.txt"        # a temporary file outside the repository

# Anthropic key: type or paste it at the hidden prompt.
$secure = Read-Host "Anthropic API key" -AsSecureString
$plain  = [Runtime.InteropServices.Marshal]::PtrToStringBSTR([Runtime.InteropServices.Marshal]::SecureStringToBSTR($secure))
[IO.File]::WriteAllText($File, $plain)
gcloud secrets versions add oah-anthropic-api-key --data-file=$File --project=$ProjectId
Remove-Item $File; $plain = $null

# Shared access key: 32 random bytes as hex. Keep a copy only in your password manager and in the Vercel setting.
$bytes = New-Object byte[] 32
[Security.Cryptography.RandomNumberGenerator]::Create().GetBytes($bytes)
[IO.File]::WriteAllText($File, (($bytes | ForEach-Object { $_.ToString("x2") }) -join ""))
gcloud secrets versions add oah-api-key --data-file=$File --project=$ProjectId
Remove-Item $File
```

Allow only the runtime account to read them:

```powershell
foreach ($name in "oah-anthropic-api-key", "oah-api-key") {
  gcloud secrets add-iam-policy-binding $name --project=$ProjectId `
    --member="serviceAccount:$Sa" --role="roles/secretmanager.secretAccessor"
}
```

The service file references the secrets with `key: latest`. Rotating a secret means adding a new version and
creating a new revision (section 6), because the value is read when the instance starts.

## 4. Build the image

Cloud Run needs `linux/amd64`. The Dockerfile expects the stores as an ADDITIONAL, NAMED build context called
`stores` (`COPY --from=stores ...`); without it the build stops, on purpose.

Both routes below depend on BuildKit (the Dockerfile uses a `# syntax=` line and `COPY --chmod`).

### 4.1 Route A: local, `docker buildx` (needs the local engine running)

```powershell
gcloud auth configure-docker "$Region-docker.pkg.dev"
docker buildx build --platform linux/amd64 --build-context stores=$Stage -t $Image .
docker push $Image
```

Equivalent literal form: `docker buildx build --platform linux/amd64 --build-context stores=<STAGE_DIR> -t <IMAGE> .`
Add `--push` instead of the separate `docker push` if you prefer.

### 4.2 Route B: Cloud Build (recommended while the local engine is off)

`gcloud builds submit` cannot pass `--build-context`; a named additional context is a `docker buildx` option, and
whether the Docker CLI inside Cloud Build's `docker` builder accepts it was NOT verified. So this runbook does not rely
on it. Instead it assembles a temporary build directory OUTSIDE the repository holding the files the image needs, the
staged stores at its root, and a copy of the Dockerfile in which `--from=stores ` is removed (the stores are then
plain files of the single build context). The repository files are not modified.

```powershell
$Repo_Root = (Get-Location).Path                       # run from the repository root
$Build = Join-Path $env:TEMP "oah-build-context"       # must not exist yet
New-Item -ItemType Directory -Path $Build | Out-Null
New-Item -ItemType Directory -Path "$Build/scripts" | Out-Null
Copy-Item pyproject.toml, requirements-lock.txt $Build
Copy-Item src $Build -Recurse
Copy-Item scripts/runtime_requirements.py, scripts/container_healthcheck.py "$Build/scripts"
Copy-Item "$Stage/*" $Build                            # the three stores and manifest.json, at the root

# Dockerfile copy: stores come from the build context itself.
(Get-Content Dockerfile -Raw) -replace '--from=stores ', '' | Set-Content "$Build/Dockerfile" -NoNewline -Encoding ascii

# .dockerignore copy: the same allow-list plus the four staged files.
(Get-Content .dockerignore -Raw) + "`n!waterbase_icm_2026.sqlite`n!bathing_water_2025.sqlite`n!bathing_samples_discodata.sqlite`n!manifest.json`n" |
  Set-Content "$Build/.dockerignore" -NoNewline -Encoding ascii

# Cloud Build configuration: BuildKit on, linux/amd64 (Cloud Build workers are amd64), push to the repository.
@"
steps:
  - name: gcr.io/cloud-builders/docker
    env: ["DOCKER_BUILDKIT=1"]
    args: ["build", "-t", "$Image", "."]
images: ["$Image"]
"@ | Set-Content "$Build/cloudbuild.yaml" -Encoding ascii

gcloud builds submit $Build --config "$Build/cloudbuild.yaml" --project=$ProjectId --region=$Region
```

Check before submitting: `Get-ChildItem $Build` shows `Dockerfile`, `.dockerignore`, `pyproject.toml`,
`requirements-lock.txt`, `src`, `scripts`, `cloudbuild.yaml` and the four staged files; `Select-String "COPY"
"$Build/Dockerfile"` shows no `--from=stores`. Delete `$Build` afterwards.

If the `docker` builder turns out to be too old for BuildKit, build with Route A, or add a first step that installs
`docker buildx`; do not weaken the Dockerfile.

Verification status of the two routes: neither was executed. The CI job `deploy-checks` exercises Route A's
`--build-context` form on a Linux runner with tiny synthetic stores (see section 10), so that form is exercised in CI
once the workflow runs; Route B is untested.

The build installs only the runtime packages: `scripts/runtime_requirements.py` derives them from the hash-pinned
`requirements-lock.txt`, and `pip install --require-hashes --no-deps` refuses anything unlisted or altered.

## 5. Render the service file and deploy

Never edit the committed file. Render a COPY, outside the repository, and check no angle bracket is left.

```powershell
$Origin = "http://localhost:3000"   # first deploy: the Vercel URL is not known yet (section 7)
$Contact = "<CONTACT_URL>"          # replace with the https URL of YOUR contact page (section 12); never an e-mail address
$Rendered = Join-Path $env:TEMP "oah.service.rendered.yaml"
(Get-Content deploy/cloudrun.service.yaml -Raw) `
  -replace '<PROJECT_ID>', $ProjectId -replace '<REGION>', $Region -replace '<REPOSITORY>', $Repo `
  -replace '<TAG>', $Tag -replace '<VERCEL_ORIGIN>', $Origin -replace '<CONTACT_URL>', $Contact | Set-Content $Rendered -NoNewline
Select-String -Path $Rendered -Pattern '<[A-Z_]+>'     # must print nothing apart from comment lines
```

The same in `bash`:

```bash
sed -e "s|<PROJECT_ID>|$PROJECT_ID|g" -e "s|<REGION>|$REGION|g" -e "s|<REPOSITORY>|$REPOSITORY|g" \
    -e "s|<TAG>|$TAG|g" -e "s|<VERCEL_ORIGIN>|$ORIGIN|g" -e "s|<CONTACT_URL>|$CONTACT_URL|g" deploy/cloudrun.service.yaml > "$TMPDIR/oah.service.rendered.yaml"
```

The file also mentions the placeholders in its header comments; those comment lines are harmless (the substitution
replaces them too). Deploy:

```powershell
gcloud run services replace $Rendered --region=$Region --project=$ProjectId
```

The service allows unauthenticated invocation only if you grant it (section 11 explains why this is needed):

```powershell
gcloud run services add-iam-policy-binding oah-backend --region=$Region --project=$ProjectId `
  --member="allUsers" --role="roles/run.invoker"
$Url = gcloud run services describe oah-backend --region=$Region --project=$ProjectId --format="value(status.url)"
```

`services replace` creates the service when it does not exist and a new revision when it does. The service sets
`minScale = maxScale = 1`, `timeoutSeconds: 150`, `containerConcurrency: 20`, 1 vCPU and 2 GiB (section 10, "Memory").

## 6. Rollback and rotation

Every deploy is a revision; the image tag is part of it.

```powershell
gcloud run revisions list --service=oah-backend --region=$Region --project=$ProjectId
gcloud run services update-traffic oah-backend --region=$Region --project=$ProjectId --to-revisions=<REVISION_NAME>=100
```

Rolling back by traffic keeps the previous image and its baked-in stores. Do not delete old image tags until the new one
is accepted. A secret rotation (new version in Secret Manager) takes effect on the next revision: redeploy the same
rendered file (or `gcloud run services update oah-backend --region=$Region --project=$ProjectId` with no change forces
one) and run the smoke tests again.

## 7. Allowed origin after the Vercel URL is known

`OAH_CORS_ORIGINS` accepts explicit origins only (no wildcard) and the first deploy used a placeholder. Once the Vercel
production URL exists, render again with `$Origin = "<VERCEL_ORIGIN>"` (the origin only: scheme and host, no path, no
trailing slash) and run `gcloud run services replace` again. Prefer this over `gcloud run services update
--update-env-vars`: the committed file stays the single description of the service. The browser never calls this
service (it calls Vercel's same-origin route handlers), so CORS is defence in depth, not the access control.

## 8. Smoke tests

Set the key from the clipboard or your password manager into a variable without echoing it, and never paste it in a
command line that is kept:

```powershell
$secure = Read-Host "OAH_API_KEY" -AsSecureString
$Key = [Runtime.InteropServices.Marshal]::PtrToStringBSTR([Runtime.InteropServices.Marshal]::SecureStringToBSTR($secure))
```

Then (`curl.exe`, not the PowerShell alias; the header is read from the variable and never printed):

```powershell
curl.exe -sS "$Url/health"                                                    # {"status":"ok"}, no key needed
curl.exe -sS -o NUL -w "%{http_code}`n" "$Url/countries"                       # 401: the key is required
curl.exe -sS -H "X-API-Key: $Key" "$Url/countries"                            # both sources; Waterbase data_range present
curl.exe -sS -H "X-API-Key: $Key" "$Url/sites?country=GR&limit=3"             # a bounded site list
curl.exe -sS -H "X-API-Key: $Key" "$Url/languages"                            # the supported answer languages
curl.exe -sS -o NUL -w "%{http_code}`n" "$Url/docs"                           # 404: interactive docs are off
```

Only after the Anthropic secret holds a real key, and only once (each chat counts against the daily cap):

```powershell
curl.exe -sS -X POST -H "X-API-Key: $Key" -H "Content-Type: application/json" `
  -d '{"message":"Which sites have data in Greece?","country":"GR","language":"en"}' "$Url/chat"
```

Clear the variable when done: `$Key = $null`. Check `gcloud run services logs read oah-backend --region=$Region
--project=$ProjectId --limit=50` for start-up errors (a wrong `OAH_CORS_ORIGINS` or limits value stops the server
with a clear message).

## 9. How the web app passes the key (Vercel)

- Store the shared key as a Vercel environment variable WITHOUT the `NEXT_PUBLIC_` prefix (server-only), for example
  `OAH_API_KEY`, next to the backend URL (a server-only `BACKEND_URL`). Never use it in client components and never
  bundle it (`frontend/src/api.ts` already states why).
- The browser calls the web app's own route handlers (or server components); those run on Vercel's servers, read the
  server-only variable and call the backend with the header `X-API-Key: <value>`.
- Give the Vercel function a maximum duration of at least 150 s (the service timeout) for the chat route; the chat loop
  stops starting model calls after 45 s and the translation is limited to 30 s, and the backend answers with its own
  errors before that in every realistic case. Check what your Vercel plan allows; if it allows less, lower nothing here
  blindly: the worst stacked case (a provider hanging on every call) is rare, but then Vercel ends the request first.
- The web app must display the attribution duties of section 12 next to external data.
- A browser-to-Cloud-Run call with the key would expose it; that is why the same-origin proxy is required.
- Vercel's own per-visitor limiting (its firewall or a limit in the route handler) is the right place for per-person
  limits, for the reason in the security checklist below.

## 10. Operating notes

### Single instance

`minScale = maxScale = 1` on purpose. The general rate limiter, the daily model caps, the response caches and the audit
hash chain are in process memory. Two instances would each have their own counters (the daily caps and per-minute limits
would double, and the audit chain would fork); scale-to-zero would lose the counters on every idle period and pay the
cold start (the stores are read on demand, the largest is 160 MiB). One uvicorn worker, for the same reason. If more
capacity is ever needed, the counters must move to a shared store first (a code change). The external-context caches
and budgets (section 12) are in process memory too, so they are per instance as well: with N instances the effective
Open-Meteo and GBIF budgets would be N times the configured ones, and the providers see the sum.

### Sandbox cache and start-up warm-up

The sandbox data is cached in memory with stale-while-revalidate (`docs/architecture.md`, "Sandbox cache"). The application
warms the cache in background threads at start-up (it does not delay the health check; `OAH_SANDBOX_WARMUP=0` disables it).
Optional settings, none needed in the service file: `OAH_SANDBOX_CACHE_TTL_SECONDS` (default 300) and
`OAH_SANDBOX_MAX_STALE_SECONDS` (default 21600). Because `cpu-throttling` is on, a background refresh only progresses
while a request is processed: the first visitor after an idle period gets the held copy labelled `snapshot` with its age,
and the copy becomes current during the following requests.

### Memory

The service file asks for 2 GiB (it was 1 GiB before the third store and the external context). Reasoning, with what was
and was not established:

- On disk the stores are about 160 MiB (Waterbase), 19 MiB (bathing water) and 84 MiB (bathing samples), 263 MiB
  together. SQLite reads pages on demand through the operating system's page cache; the application does not load a
  store into Python memory. VERIFIED in the code: every store is opened read-only with parameterised queries.
- On Cloud Run the container filesystem is in memory: the platform documents that files written to the filesystem count
  toward the memory limit. What could NOT be verified is whether the read-only image layers (the stores baked into the
  image) are also counted. The safe assumption is that they might be, so the budget is sized as if all 263 MiB were
  resident: 263 MiB plus the Python process (interpreter, FastAPI, pydantic, numpy, the 25 translation files and the
  taxon file, probably 150 to 250 MiB, not measured), plus `/data/runtime` (audit log at most 5 MiB per file before
  rotation, the review database, caches: small), plus request working memory.
- The largest request working memory is the whole-country period comparison. Waterbase reads at most 2,000,000 monthly
  rows into Python objects for one comparison (`MAX_SCOPE_ROWS`); each row costs a few hundred bytes as a tuple plus a
  dataclass, so a pathological comparison could need several hundred MiB for the few seconds it runs. The samples
  comparison reads about 53,000 monthly cells for Italy (a few MiB). Several such requests at once would add up; the
  general limiter (240 per minute shared) and the 20-request concurrency bound them but do not prevent two heavy ones
  overlapping. These are estimates from the code, NOT measurements.
- Conclusion: 1 GiB had little headroom for the worst case even before; 2 GiB leaves about 1.5 GiB over the
  "everything counted" floor of roughly 0.5 GiB. 1 vCPU is kept: the routes are synchronous in one process, a second
  vCPU would help only SQLite reads that release the interpreter lock, and `cpu-throttling` already limits idle cost.
- Measure after the first deploy and adjust (Cloud Monitoring, metric `run.googleapis.com/container/memory/utilizations`,
  the 99th and 50th percentile and the maximum, in the Cloud Run service's Metrics tab): (1) idle after start, to see
  whether the image layers count (idle utilisation near 10 percent of 2 GiB means they do not, near 22 percent or more
  means they do); (2) after one country comparison for Italy and one for Greece on the heaviest determinand; (3) after
  a chat. If the maximum stays below 50 percent, 1 GiB can be restored; if it exceeds 80 percent, raise to 4 GiB (with 1
  vCPU Cloud Run allows it) and consider lowering `containerConcurrency`. An out-of-memory kill shows in the logs as
  "Memory limit exceeded".

### Cost dimensions (no prices are quoted here; check the current Google Cloud and Anthropic price lists)

- Cloud Run: vCPU-seconds and GiB-seconds of the one always-on instance (minimum instance of 1), requests, and network
  egress. CPU is throttled outside requests (`cpu-throttling: true`), which lowers the CPU line; the memory line remains.
- Artifact Registry: storage of the image (about 260 MiB of stores plus the runtime) per kept tag, and egress.
- Network egress from Cloud Run to the three external hosts: the answers are small (a GBIF search of 200 records is
  about 1 MB at most; a weather answer is a few KB), so this line is small, but it is not zero; check the price list.
- The 2 GiB memory setting raises the GiB-seconds line compared with 1 GiB; section 10 "Memory" says how to decide
  whether to lower it again.
- Cloud Build (Route B): build minutes and the temporary source upload to a Cloud Storage bucket that Cloud Build
  manages in the project.
- Secret Manager: active secret versions and access operations (one read per instance start).
- Anthropic: tokens of `/chat`, `/explain` and the translation call. The daily caps (`OAH_CHAT_DAILY_CAP`,
  `OAH_EXPLAIN_DAILY_CAP`) and per-minute limits are the hard control; both are global for the demo.
- Cloud Logging: request and application logs above the free allotment.

### Ephemeral filesystem

Cloud Run's filesystem is in memory and per instance. Everything under `OAH_DATA_DIR` (`/data/runtime`) is lost on every
restart, redeploy or crash: the audit log (and its hash chain restarts), the review database (the human-review
queue starts empty), exports, and the sandbox and response caches (rebuilt on demand). The stores under `/data/stores`
are read-only parts of the image and are not affected. Memory used by the files under `/data/runtime` counts toward
the memory limit (2 GiB), and whether the baked-in stores count is the open question of the "Memory" subsection.
Every audit record is also written to standard output as one JSON line (digests and counts only, no user text and no
keys), so Cloud Logging keeps the trail across restarts; the files on disk are capped to a few rotated files. The
in-memory spend caps and caches still reset on every restart, so the provider-side budget is the real ceiling and an
alert on instance restarts is worthwhile (`docs/predeploy_checklist.md`). Treat the review queue of the deployed
service as demo state, not as records.

### CI

`.github/workflows/deploy-checks.yml` (no secrets, no cloud credentials, nothing pushed) validates the service file and
the other deployment files (`tests/unit/test_deploy_files.py`), checks `docs/openapi.json` is current, builds tiny
SYNTHETIC stores (three: Waterbase, bathing water, bathing samples) with `scripts/make_synthetic_stores.py`, stages
them with the real staging script, checks the staged folder holds exactly the three stores and the manifest, builds the
image with `--build-context stores=...` without pushing, starts it, probes `/health` and checks that the three stores
and `gbif_taxa.json` are inside the image. The synthetic stores are never deployed. `.gitattributes` forces LF line
endings for the Dockerfile, `deploy/`, `.github/`, shell scripts and `scripts/*.py` only.

## 11. Security checklist

- [ ] Both secrets exist in Secret Manager; no value is in the repository, the service file, the shell history, a build
      argument or an image layer (`docker history` shows none; the Dockerfile never copies a dotenv file, and
      `.dockerignore` excludes every dotenv pattern).
- [ ] The runtime service account has no project role; each secret grants it `secretAccessor` only.
- [ ] `OAH_API_KEY` is set (the app answers 503 on every protected route without it, and with
      `OAH_INSECURE_NO_AUTH` unset it never runs open). `OAH_ENABLE_DOCS` is unset (no `/docs`, `/redoc`, `/openapi.json`).
- [ ] Public invoker (`allUsers` with `roles/run.invoker`) is accepted knowingly. It is needed because the caller is
      Vercel's servers on the public internet, with no Google identity the platform could check. It is acceptable
      because: every route except `/health` requires the shared `X-API-Key` (compared in constant time); the rate limiter
      and the model spend caps bound what a key holder, or anyone sending garbage, can cause; the service is read-only
      over prebuilt stores and a sandbox, holds no personal data, and its only outbound targets are the configured
      sandbox URL, the model API and the three allow-listed external-context hosts (section 12; no caller supplies a
      URL, host or coordinate). The residual risk is that a leaked key allows use of the API within those caps:
      rotate it (section 6) if it leaks.
- [ ] `OAH_CORS_ORIGINS` is the Vercel origin only.
- [ ] Ingress is `all` (no private path exists from Vercel); the container runs as an unprivileged user (uid 10001).

### `OAH_TRUSTED_PROXIES` is deliberately unset

What the code does (`src/oah/api/client_ip.py`, `src/oah/api/app.py`, uvicorn started with `--no-proxy-headers`):

- The address a request is limited under is the immediate TCP peer, `request.client.host`. `X-Forwarded-For` is
  honoured only when that peer is in `OAH_TRUSTED_PROXIES`; otherwise the header is ignored (a client can send it
  itself).
- On Cloud Run the TCP peer is Google's front end, not the caller, and its addresses are not published as a fixed list.
  So with the variable unset every request is limited under the front end's peer address, whoever the caller is; the
  number of distinct peers is not known, and may be more than one. The general limit (`OAH_RATE_LIMIT_MAX_REQUESTS` per `OAH_RATE_LIMIT_WINDOW_SECONDS`, 240 per 60 s
  in the service file), the explanation limit and the chat limit therefore act as shared budgets for the whole demo,
  not per person. That is how the service file sizes them.
- Consequences: one abusive caller can use up the shared per-minute budget and make others receive 429 until the
  window ends; it cannot go beyond the daily caps. The access key is checked BEFORE the normal limiter: a missing or
  wrong key is charged only to a separate failed-request limiter (60 per 60 s per client address, then 429), so a flood
  of wrong keys cannot exhaust the budget of authenticated callers. This is still a denial-of-service risk for the
  demo, not a data risk. Per-visitor limiting and bot protection belong on the Vercel side, which can send an opaque
  per-visitor token in the optional `X-OAH-End-User` header (a fairness aid for the chat and explanation per-minute
  limits, not authentication; the shared key stays the access control).
- Hardening on Cloud Run: the service refuses to start when `K_SERVICE` is set and the no-authentication flag is on, when
  there is no `OAH_API_KEY`, or when the key is shorter than 32 characters (the generated key is 43). The three write
  routes (review decision, FHIR exports) answer 404 unless `OAH_ENABLE_WRITE_ROUTES` is set, which it must not be
  here. `OAH_TRUSTED_PROXY_HOPS` (derive the client address from `X-Forwarded-For`, counted from the right) stays unset
  until the real number of proxies in front of the service is verified.
- The app also sees the request as plain `http` behind Google's front end, so it does not add the
  `Strict-Transport-Security` header (it is added only for https or a trusted proxy saying so). Google's front end
  serves the public URL over https only.
- Why not set it: the list would have to be the front end's real peer addresses; a guessed or too-wide list lets a
  client choose its own limit key by sending `X-Forwarded-For`. Fail-safe is to leave it empty. Turning it on is a future
  step that needs the verified peer addresses.

## 12. Outbound network and external context

The external-context package (`src/oah/external`, `docs/external_context.md`) is the only part of the service that calls
the internet at run time besides the model API and the sandbox. It is optional and read-only (GET only).

### Hosts (https, port 443)

| Host | Used for | Provider |
|---|---|---|
| `archive-api.open-meteo.com` | weather (ERA5 reanalysis, modelled) | Open-Meteo |
| `flood-api.open-meteo.com` | river discharge (GloFAS, modelled) | Open-Meteo |
| `api.gbif.org` | species occurrence records (opportunistic) | GBIF |

The hosts are constants in `oah.external.constants` (`ALLOWED_HOSTS`); no route, tool or caller supplies a URL, host or
coordinate, and the client refuses any other host, plain http and a redirect to another host. Cloud Run allows outbound
traffic by default; the service file configures no VPC connector and no egress restriction. The Discodata host is NOT
needed at run time (the samples store is prebuilt; only the store build calls it).

### If egress is restricted

If you later add a VPC with an egress firewall or a Cloud NAT allow-list (not part of this runbook), open https to the
three hosts above, or switch the feature off: set `OAH_EXTERNAL_ENABLED` to `false` in the rendered service file and
deploy a new revision. Every provider then answers `external-unavailable` with the reason `disabled`, the chat tools say
so, nothing is sent, and every other feature (stores, comparisons, chat on store data) keeps working. A single
provider can be switched off with `OAH_EXTERNAL_OPEN_METEO_ENABLED`, `OAH_EXTERNAL_GLOFAS_ENABLED` or
`OAH_EXTERNAL_GBIF_ENABLED`. A provider that is unreachable by accident behaves the same way without any switch: the
call times out (5 s, two retries), three consecutive failures open a 30-second circuit breaker, and the answer is
HTTP 200 with `external-unavailable`, never a 500.

### Budgets and caches are per instance

The Open-Meteo budget (200 estimated call units per minute, 3,000 per day), the GBIF budget (30 and 1,500 requests),
the result cache (256 entries, 1 hour) and the circuit breakers live in the memory of the process. The service runs
exactly one instance, so they are service-wide; they reset on every restart, redeploy or crash (a restart therefore
also resets the daily counters, so the providers' real limits are what finally matter). The values in the service file
are the code defaults, kept explicit and below the published Open-Meteo free tier (600 per minute, 10,000 per day);
they are lowered by editing the service file, never raised without re-reading the provider terms (the code clamps
them at ceilings). Cloud Run's outbound addresses are shared platform addresses: a provider that limits by address
could answer 429 because of other tenants; the code then opens a cool-down and reports `rate-limited`. This was not
observed (nothing was deployed).

### Attribution duties the web app must meet

The API returns the texts; the web app must display them next to the data (they are in each response's `attribution`
and licence fields; see `docs/external_context.md` section 3):

- Open-Meteo (weather and discharge): a visible link next to every place where Open-Meteo data are shown, with the text
  `Weather data by Open-Meteo.com` pointing to `https://open-meteo.com/` (the licence is CC BY 4.0; say that data were
  aggregated to months). The free API is for NON-COMMERCIAL use: a site with advertising or subscriptions would need
  Open-Meteo's commercial plan.
- GBIF: show the licence of each record as returned (`CC0-1.0`, `CC-BY-4.0`, `CC-BY-NC-4.0`, or `other-or-unspecified`
  with the raw text), the dataset and its citation text, and never drop the licence when displaying a record; mark
  `CC-BY-NC-4.0` records as non-commercial only.
- EEA (the three stores, bathing-water classification and samples): the attribution string each response carries
  (EEA CC BY 4.0, per the EEA legal notice; the Discodata pages do not restate the licence, so this is inferred and to
  be confirmed). Show it next to the data.
- The GloFAS credit wording and the GBIF terms were NOT verified (`docs/external_context.md` section 3); confirm them
  before any public use.

### `OAH_CONTACT_URL`

The code puts this URL into the User-Agent so that a provider can reach the operator before blocking. Use the https URL
of a contact page of the maintainer's choosing (for example a contact page of the project or organisation site): no
credentials, no query string, no fragment, at most 200 characters; the code refuses anything else at start-up with a
clear message. Never put a personal e-mail address in the repository, the service file or this runbook; the value is
supplied when rendering (section 5) and exists only in the rendered copy and the deployed service. It is not a secret
(it is sent to the providers), so it is a plain variable, not a Secret Manager entry. If unset, the User-Agent is the
product name only, which is allowed but less polite.

## 13. What was NOT verified

- No Docker image was built, by either route; the Dockerfile, the `COPY --from=stores` line with the three stores and
  the line endings (the working-tree files are LF; `.gitattributes` now forces LF for them on checkout) have not been
  through a real build in this work. The CI workflow is written to do it on a Linux runner but had not run when this
  was written (including its new three-store and `gbif_taxa.json` checks).
- The three stores in the image, the `OAH_BATHING_SAMPLES_STORE` path inside the container, and that
  `src/oah/external/data/gbif_taxa.json` is present in the image were verified only by reading: the file is under
  `src`, the Dockerfile copies `src` whole and `.dockerignore` re-includes `src`; a unit test pins this, but no
  container was started.
- Outbound https from the deployed service to the three hosts, the real egress path and addresses, and how the
  providers treat Cloud Run's shared addresses were not tested; the external calls were only exercised from a
  development machine (the real smoke recorded in `docs/external_context.md`) and with scripted fakes in the tests.
- Whether Cloud Run counts the read-only image layers against the memory limit, the real memory of the process with
  three stores, and the real peak of a whole-country comparison were not measured (section 10, "Memory", gives the
  reasoning and the measurement procedure). The Cloud Monitoring metric name in that procedure is written from
  knowledge, not checked.
- The worst-case request time (a chat whose external calls all hang) is computed from the code (timeouts, retries,
  breaker), not measured; `timeoutSeconds: 150` is a computed margin.
- Nothing was pushed, deployed, or created in Google Cloud; none of the `gcloud` commands (repository, service account,
  secrets, IAM bindings, `services replace`, revisions, traffic) was run, so their flags are written from knowledge of the tool, not checked against its
  help or tested. Whether Cloud Build's `docker` builder supports BuildKit and
  `--build-context` was not checked.
- No Secret Manager secret exists yet; the secret-injection path (`secretKeyRef` with `key: latest`) was not exercised.
- The application was started locally with uvicorn (health 200, `/languages` 401 without and 200 with the key) and the
  health-probe script was tested against it and a stub server; the container itself, its unprivileged user, the
  read-only store files, `PORT` handling under Cloud Run and start-up time with the real stores were not tested.
- The derived runtime requirement set was compared with every third-party import of `src/oah` (all present) and with
  the metadata of each pinned package in the development environment (only two requirements, both for other
  platforms or Python versions, are absent: `exceptiongroup` and `httpx2-jsfetch`); installation from the lockfile on
  `linux/amd64` was not run, so the availability of a wheel with a matching hash for each pin on that platform is
  assumed from the lockfile, not tested.
- The real latency of `/chat` from Cloud Run, the cost, and how the Vercel application is configured (including the
  maximum duration its plan allows) were not measured or reviewed.
