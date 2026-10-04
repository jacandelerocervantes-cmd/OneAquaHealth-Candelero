# Frontend: analysis and conceptual design

Status: 2026-09-29, revised after the user's decisions (section 12). Analysis only: no frontend code is written
or changed by this document.

**Direction taken (2026-09-29):** the site is hosted on **Vercel** with **Supabase**; the existing `frontend/` is
discarded and the frontend is rebuilt from scratch; backend endpoint additions are approved; every other question of
the first version of this document is left to the design defaults below. Sections 1 to 11 describe the analysis of
the existing frontend and the product design, and stay valid except where section 13 says otherwise.

## 1. What exists today

**Frontend** (`frontend/`, Vite 8, React 19, TypeScript, react-router, react-i18next with EN and ES, react-leaflet):
one route (`/`) with one page (`Home`): a Leaflet map of the sites returned by `/sites`, each a coloured circle
(good, moderate, poor, unavailable) with a popup (name, class, WQI, "low confidence"). Loading, error and retry
states exist. `api.ts` has one call (`getSites`) and no authentication.

**Gaps in what exists**
- The types are stale against the backend: no `data_freshness`, `interpretation_notice`, `limit_regime`,
  `limit_country`, `veto_triggered` or `eclipsed`, so none of the trust information the backend now sends is shown.
- Status is conveyed by colour only (not accessible), there is no legend, and the popup hides the veto.
- The map opens on the first site at zoom 5, but the sites are spread over several countries (Crete, Italy, Norway,
  Portugal, the United States), so the opening view is wrong.
- The Vite template leftovers (`hero.png`, `react.svg`, `vite.svg`, the template README) are still there;
  `hero.png` has an unverified origin.
- It only works against a backend started with `OAH_INSECURE_NO_AUTH=1` (documented, deliberate: see
  `docs/architecture.md`, "UI authentication is undecided").

**Backend contract available** (all routes except `/health` are protected; CORS allows the local dev origins)

| Route | Returns | Real or synthetic |
|---|---|---|
| `GET /sites` | every Location with a map position, its CCME WQI, class, confidence, veto, regime and country, plus `data_freshness` and `interpretation_notice` | real |
| `GET /indices/{id}` | one site: score, per-site counters, `limit_basis` per parameter, veto detail, data-quality counters, notice | real |
| `GET /explain/indices/{id}` | LLM explanation (`describe` or `assess`) with grounding flags, `unsafe`, disclaimer; paid, rate-limited, capped | real evidence, model text |
| `GET /qc/report` | quality-control findings over all Observations | real |
| `POST /fhir/export`, `POST /fhir/export/indicators` | write a FHIR Bundle on the server, return its file name | real |
| `GET /reliability/campaign` | synthetic citizen-science campaign, majority vote versus Dawid-Skene | synthetic |
| `GET /review/queue`, `POST /review/{id}/decide` | human-review queue and decision (409 if decided, 422 if the label is not allowed) | synthetic |
| `GET /risk/{site}` | propagated risk on a demo river topology | synthetic |

**What the real data can actually show** (probe of the public sandbox, 2026-09-29): 23 Locations. Twelve of them
are Benevento AIR-quality stations, not water bodies. Every mapped water Observation belongs to one site
(Almyros, Crete); the Giofyros reaches only have water temperature, which is not scored for Greek rivers. So at
most one or two sites are evaluated and the rest are grey. The design must make that look intentional, not broken.

## 2. Purpose and audience

A hackathon deliverable (not a regulatory tool). It has to make one story clear in a few minutes, to judges and the
consortium: *where is urban stream water healthy, why, and how far can that be trusted.* Secondary audiences: a
citizen or municipal reader (plain language), and a technical reader (method, sources, FHIR outputs).

## 3. Design principles

1. **Honesty first.** Every number carries its origin, its freshness and its limits. Reference values are never
   presented as legal compliance.
2. **Real and synthetic never mix.** Synthetic modules live in their own section with a permanent label.
3. **Explain, do not decorate.** The interface exists to answer "why this score" and "can I trust it".
4. **Accessible by default.** Colour is never the only channel; everything reachable by keyboard.
5. **Small and boring technology.** Keep the current stack; add only what a screen needs.

## 4. Information architecture

```
/                 Map: sites, status, filters, legend, freshness and notice banners
/site/:id         Site detail: score, confidence, why (parameters and limits), data quality, explanation
/method           How it works: the index, the limit regimes, sources and citations, what it is not
/lab              Synthetic lab (clearly labelled): reliability campaign, review queue, risk propagation
/exports          FHIR exports (write actions), only when the backend allows them
```

**Map.** Fit the view to the sites (not the first site). Marker status uses colour plus shape or icon plus a text
label; a list or table view of the same sites is the keyboard and screen-reader alternative. Locations that are not
water bodies (air stations) are shown as such or hidden, never as "No water data". A legend, a filter by status and
country, and a persistent freshness line (live, snapshot, stale snapshot with its age) sit above the map.

**Site detail** answers in this order: (1) the score and class in words, with confidence; (2) the veto and
"eclipsed" explained in one sentence each; (3) which limit regime applies (drinking-water values, river standards,
national) and, per parameter, the basis of its limit (legal, indicator, national, proxy, convention, override,
unverified); (4) what was left out and why, from the data-quality counters in plain language; (5) an on-demand
explanation.

**Explanation.** Off until the reader asks. Shows the model text as plain text (never as HTML), the grounding badge,
the `unsafe` state, the fixed disclaimer and whether the answer was cached; handles the 429 budget and Retry-After.

**Method page** holds the long-form honesty content so screens stay light: the index formulas, the limit regimes, the
sources and licences (from `SOURCES.yaml`), the changeable limits file, and a plain statement that the values are
reference values for a hackathon.

**Synthetic lab.** Reliability campaign (seeded, so reproducible), the review queue with a decision form (label from
the offered set or "other", a pseudonymous reviewer handle), and the demo risk topology. A banner states "synthetic
data, not real hydrology".

## 5. Trust elements that must appear (from the audit)

| Element | Source field | Where |
|---|---|---|
| Data origin badge | `origin` | every screen with data |
| Freshness | `data_freshness.status`, `as_of`, `age_seconds` | map header, site detail |
| Not a compliance determination | `interpretation_notice` | next to every score |
| Limit basis per parameter | `limit_basis` in `/indices` | site detail table |
| Low confidence | `confidence`, `confidence_note` | marker, site header |
| Veto and eclipsed | `veto_triggered`, `eclipsed`, `veto_parameters` | site header |
| Overridden limits | `limit_overrides`, `override:` in `limit_basis` | banner when a limits file is in force |
| Model text is unverified | `unsafe`, `grounded`, `disclaimer` | explanation panel |

## 6. States the interface must handle

Loading, empty (no evaluated site), partial (some sites skipped, with their reasons), 401 (missing or invalid key),
404 (unknown site), 409 and 422 (review decisions), 429 (rate limit or LLM budget, show the wait), 502 and 503 (the
model provider or the sandbox unavailable, generic message), offline. Each has a message written for a person and a
retry where it makes sense.

## 7. Authentication (the deferred decision)

| Option | Fits | Cost |
|---|---|---|
| A. Local demo with `OAH_INSECURE_NO_AUTH=1` (today) | judges run it on a laptop; the hackathon | none; must never be used on a public host |
| B. Same-origin proxy that keeps the API key on the server side | a hosted public demo | a small server component; the key never reaches the browser |
| C. Per-user sessions | a real deployment | not justified for a hackathon |

Recommendation: A for the demo, B if it is hosted; never a key in the bundle. Under a hosted demo, hide or disable
the write actions (`decide`, exports) or route them through the proxy with their own limits.

## 8. Data layer

A typed client per route, types generated from the OpenAPI document (exported by a script from `app.openapi()`,
because the live `/openapi.json` route is off by default), so the contract cannot drift again. Server state
handled with a small fetching layer (plain hooks or one well-known library), with a short cache and no polling.
The base URL comes from an environment variable. The API returns English text (notice, basis, model output): the
interface translates its own labels and shows backend text as it is, with a "text in English" hint.

## 9. Technology

Keep: Vite, React, TypeScript, react-router, react-i18next, Leaflet (BSD-2) with OpenStreetMap tiles (ODbL,
attribution required, light use). Add only if needed: a charting approach (simple SVG is enough for a per-parameter
bar), `vitest` with Testing Library for components, one browser smoke test. CI: extend the workflow with the
frontend lint, type check, build and tests, and `npm audit`. Remove the template assets and README; verify or drop
`hero.png`.

## 10. Backend gaps to decide before or with the frontend

1. A per-site **measurement detail** (value, unit, limit, excursion per parameter): `/indices` has counters and the
   worst parameters but not the table a reader expects.
2. A **site kind** field on `Site` (water body or air station) so the map can treat them correctly.
3. A **language parameter** for explanations (the model currently answers in English).
4. An exported **OpenAPI file** as a build artefact for type generation.
5. Optional: the remaining LLM budget, so the interface can say how many explanations are left.

## 11. Delivery phases

| Phase | Content | Exit criterion |
|---|---|---|
| F0 | this analysis, decisions in section 12 | scope and auth mode agreed |
| F1 | foundation: generated types, API client with error mapping, states, auth mode, clean template | contract test passes against the running API |
| F2 | map and site detail without the explanation | the one real site reads correctly end to end |
| F3 | trust layer: freshness, notice, limit basis, data quality in words | every element in section 5 visible |
| F4 | on-demand explanation | budget and unsafe states handled |
| F5 | synthetic lab | clearly labelled, no mixing with real data |
| F6 | accessibility, ES translation, tests, CI, demo script | keyboard and screen-reader pass, CI green |

## 12. Decisions

Taken by the user on 2026-09-29:

1. **Hosting:** a public hosted demo on Vercel (frontend) with Supabase. This replaces "local demo only" and makes
   the authentication and hosting questions of section 13 real.
2. **The existing frontend is discarded** and rebuilt from scratch (nothing in it is reused).
3. **Backend endpoint additions (section 10) are approved.**
4. Everything else (MVP scope, the one-real-site map story, default language, visual identity) was left open by the
   user: the defaults in section 13.4 apply until they say otherwise.

## 13. Hosting on Vercel and Supabase: analysis

### 13.1 What the choice changes for the Python backend

Vercel functions have a read-only filesystem with a writable but ephemeral `/tmp` (up to 500 MB), isolated per
instance and cleared when a function is archived; SQLite files do not persist there
(https://vercel.com/docs/functions/limitations, https://vercel.com/kb/guide/is-sqlite-supported-in-vercel).
Concurrent instances share nothing. The current backend keeps state in exactly those ways:

| Backend state today | Problem on serverless | Supabase-side answer |
|---|---|---|
| SQLite review store and hash-chained audit events | not persistent, one file per instance | Postgres tables; the chain tail read and the insert in one transaction with a lock |
| LLM audit log (JSONL file with rotation) | no persistent disk | an append-only Postgres table, chained the same way |
| In-process rate limiter, per-minute explanation budget, daily LLM cap | counters are per instance, so the cap can be exceeded; this is a COST-SAFETY problem | atomic counters in Postgres (a function called with the request) or a shared key-value store |
| In-process cache of sandbox Observations and the freshness state | every cold start re-fetches about 415 Observations from the sandbox | a cache table refreshed on a schedule (Vercel Cron) and read by requests |
| Snapshots and exports written to disk | no persistent disk | Supabase Storage, or return the Bundle in the response |
| Limits file (`OAH_LIMITS_FILE`, re-read on change) | no editable local file | store the overrides as a row or an environment value; same validation |
| Bundle size (fastapi, fhir.resources, numpy, networkx, anthropic) | possible size limit on the Python runtime | to be measured before committing to serverless; not verified |

### 13.2 Where does the Python backend run? (the one blocking question)

| Option | What it means | Cost |
|---|---|---|
| A. FastAPI in a container on a small host (a third vendor), Supabase for auth and Postgres, Vercel for the frontend | the API stays one long-lived process, so the in-process limiter, budget and caches keep working; only the SQLite store and the disk files move to Postgres | least backend change; adds a vendor |
| B. FastAPI as a Vercel function, all state in Supabase | two vendors only | the whole stateful list above must be ported and tested; cold starts; size limit unverified |
| C. Rewrite the API in TypeScript | one language | throws away the 1100-plus tests and the audited logic; not recommended |

Recommendation: A for a hackathon if a third host is acceptable (fastest and safest, the LLM budget stays correct);
B if only Vercel and Supabase are allowed, accepting the backend rework as its own work package before any UI.

### 13.3 Authentication becomes a real design (the deferred decision is now decided by the hosting)

Supabase Auth issues a JWT per signed-in user. The backend verifies it against the project's published keys (the
asymmetric signing keys are exposed at `/auth/v1/.well-known/jwks.json`,
https://supabase.com/docs/guides/auth/signing-keys), so no shared secret reaches the backend. Consequences:

- The shared `X-API-Key` stops being the user-facing credential; the browser never holds a secret. A server-side
  component (Next.js route handlers) can still call the API with a server-held key for anonymous read-only pages.
- The review audit `actor` becomes the pseudonymous Supabase user id (a UUID, never the e-mail), which resolves the
  self-asserted reviewer weakness found in the audit.
- Roles: anonymous visitor (read-only map and detail), signed-in user (explanations, which cost money), reviewer
  (synthetic review decisions). Explanations behind sign-in keep the LLM budget from being drained anonymously.
- Row Level Security enabled on every table with no policy for the browser roles, so a table is unreadable except
  through the API even if the public key leaks.

### 13.4 Defaults chosen for the from-scratch frontend (change them if you disagree)

| Topic | Default | Reason |
|---|---|---|
| Framework | Next.js (App Router) with TypeScript on Vercel | native Vercel hosting, server-side route handlers keep secrets off the browser, official Supabase server helpers |
| Styling and components | Tailwind CSS with a small set of accessible components | fast, consistent, no design system to maintain |
| Map | Leaflet (BSD-2) with a tile provider suited to public traffic (the public OpenStreetMap tile server is not meant for heavy use and needs attribution) | keeps the current library knowledge; tile provider to be chosen |
| Server state | TanStack Query | caching, retry and error states mapped to the API's statuses |
| Types | generated from an exported OpenAPI file of the backend | the contract cannot drift |
| i18n | English default, Spanish available | the backend texts are English; the labels of the interface are translated |
| Tests | Vitest with Testing Library, one Playwright smoke test; frontend lint, types, build and tests in CI | matches the backend's quality bar |
| Scope | phases F1 to F4 first (map, detail, trust layer, explanation), the synthetic lab after | the real data supports one evaluated site; the story is trust, not volume |
| One-site problem | show it as the hero site; optional, clearly labelled synthetic demo sites later | honest and still readable |

### 13.5 Approved endpoint additions (section 10), in the hosting context

1. Per-site measurement detail (value, unit, limit, excursion, basis per parameter).
2. `Site.kind` (water body or air-quality station).
3. A `language` parameter for explanations.
4. An exported OpenAPI file as a build artefact.
5. Remaining LLM budget, shown to signed-in users.
6. `GET /me` returning the verified identity and role from the JWT.
7. Pagination or a size limit on list responses for the hosted case.

### 13.6 Risks to keep in view

Cost exposure of the public LLM route (mitigate: sign-in, shared daily cap, per-user cap); the public write actions
(review decisions, exports) must require a role; environment variables on Vercel must never use the public prefix for
a secret; Supabase and Vercel plan limits should be read before the demo date; attribution and terms of the tile
provider and of the frontend dependencies must be recorded in `SOURCES.yaml` and `docs/third_party_dependencies.md`.

## 14. Demo-only scope (supersedes 13.2 and most of 13.3)

The user's reminder (2026-09-29): this is only for the **demo version**. Sections 13.1 to 13.3 describe what a real,
stateful deployment would need; for the demo almost none of it is required. The demo is **read-only and stateless**,
with no accounts.

| Piece | Demo decision | Why |
|---|---|---|
| Real data | a frozen, labelled snapshot of the public sandbox (Locations and Observations, with retrieval date and hash) shipped with the deployment; freshness reads "snapshot as of <date>" | no request-time calls to the sandbox, no cold-start fetch, no dependence on its availability, honest labelling |
| Backend | the existing FastAPI as a Vercel Python function in a demo mode: indices computed per request from the snapshot, no SQLite, no disk writes, exports returned in the response | the index is pure computation; nothing has to persist |
| Explanations | pre-generated offline with the real model by the developer and stored with model, date and grounding flags, labelled "pre-generated"; an optional live "ask" behind a passcode and a small daily cap only if wanted | no public cost exposure and no model key on the host |
| Synthetic lab | reliability campaign and risk topology are seeded and stateless, so they can run live; the review queue is demo state kept in the browser or a read-only sample, decisions are not persisted | keeps the labelled synthetic section without a database |
| Authentication | none: public read-only site, write actions disabled; any backend key lives only in the Next.js server environment (never a public variable) and the browser calls the same origin through a proxy, so CORS is not needed | the deferred authentication decision is not needed for a read-only demo |
| Supabase | not required for the first demo; use it only for (a) a shared cap and cache if live explanations are enabled, or (b) persisting review decisions | avoids work the demo does not need |

**Size check for the Python function** (installed size of the runtime dependencies on the Windows wheels used in this
project's clean environment, indicative only): numpy about 35 MB plus 21 MB of libraries, fhir.resources about 26 MB,
networkx about 18 MB, anthropic about 16 MB, pydantic about 10 MB, the rest about 15 MB: roughly 145 MB. That is
probably within a serverless size limit but is NOT verified on Linux or against Vercel's actual limit; lazy imports of
the heavy modules (networkx only for the risk demo, fhir.resources only for validation and exports, anthropic only for
live explanations) would shrink the cold path if needed.

**Backend changes the demo needs:** a demo mode setting that reads the snapshot and disables writes; the snapshot
loader; the pre-generated explanation store; exports returned in the response; and the approved endpoint additions
of section 13.5 that a read-only demo uses (per-site measurement detail, `Site.kind`, a `language` parameter, the
exported OpenAPI file). `GET /me`, the remaining-budget field and pagination are dropped for the demo.

**Left for "if it ever becomes real":** the state migration to Postgres (13.1), Supabase Auth with roles and Row
Level Security (13.3), per-user reviewer identity and shared LLM caps.

**Two choices left:** (1) explanations pre-generated (recommended) or live behind a passcode; (2) whether the Python
API on Vercel is acceptable, to be confirmed by a size and cold-start check before any frontend phase.
