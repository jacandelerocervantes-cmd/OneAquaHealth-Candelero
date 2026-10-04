# Web app (`web/`)

Next.js (App Router) + TypeScript + Tailwind CSS 4 front end for the OneAquaHealth backend. Design and decisions:
`docs/web_app_design.md` (layout, rules) and `docs/web_app_chat_by_country.md` (data and language rules). This file
documents what is built, how to run it in either data mode, and every place where the app derives or maps something.

## 1. Run it

```
cd web
npm install                 # node_modules stays inside web/ (approved exception; git-ignored)
npm run dev                 # http://localhost:3000, mock data by default
npm run check               # type check + lint + tests (Vitest)
npm run types               # regenerate src/lib/api-types.ts from ../docs/openapi.json
npm run types:check         # fails when the generated file is stale
npm run build && npm start  # production build
```

`npm run check` is `tsc --noEmit`, `eslint .` and `vitest run`, in that order. CI runs the same plus `types:check` and
`build` (`.github/workflows/web.yml`).

## 2. Two data modes (server-side switch)

The browser always calls its own origin (`/api/oah/...`). A route handler decides what answers:

| Variable (server only) | Meaning |
|---|---|
| `OAH_DATA_MODE` | `mock` (default) or `real`. Anything else is read as `mock`, so a fresh checkout never calls a backend. |
| `OAH_BACKEND_URL` | Real mode: the backend origin (http or https, no credentials, query or fragment). |
| `OAH_API_KEY` | Real mode: the shared access key, sent as `X-API-Key` by the route handler only. Never written to the repository, a log, a response or the browser. |

None of them has a public prefix, so Next.js never inlines them into browser code. `web/env.example` lists the names
without values (the root `.env.example` is protected from agent edits; add the three names there when convenient).
`GET /api/status` returns only `{mode, configured}` so the interface can show the mock banner; it never returns the URL
or the key.

### Mock mode

- Responses come from `src/lib/server/mock/` and are typed from the generated schemas (so the compiler rejects a
  field the contract does not have) and validated at run time against `docs/openapi.json` by
  `tests/mock-contract.test.ts` (Ajv, every route the app calls, every chat state).
- **Every mock value is invented.** Top-level `origin` is `synthetic` wherever the contract allows it, mock ids and
  names start with `Mock` / `mock-`, notices say `MOCK DATA`, and the shell shows a permanent banner. The external
  routes (`weather`, `discharge`, `species`) cannot say `synthetic` in `origin` (the contract has no such value there);
  their `dataset`, `attribution` and `data_note` say that the values are simulated.
- **Provisional mapping:** the contract requires a `source` of `real-sandbox` on sites and measurement records and has
  no `synthetic` value there. The mock sends `real-sandbox` in that field only to satisfy the contract; the interface
  labels data by `origin`, never by `source`, and the banner says the data are simulated.
- Scripted chat states, selected by a marker in the question so every screen can be seen offline:
  `[mock:429]` (429 with `Retry-After: 20`), `[mock:error]` (502), `[mock:withheld]` (status `withheld` with an
  `evidence` block), `[mock:ungrounded]` (`withheld-ungrounded`), `[mock:unsafe]` (`unsafe: true` with text that must
  never appear), `[mock:no-answer]`. Any other language than English returns a translated answer with `answer_en`.
- Mock countries: Greece, Italy, Norway. Norway has no bathing-water data and no organic-matter index, so the sidebar
  hides those there (the catalogue marks them `applies: false`).

### Real mode

`src/lib/server/proxy.ts` forwards only what `src/lib/server/allowlist.ts` lists:

- GET `/countries`, `/languages`, `/catalog`, `/sites`, `/sites/{id}/measurements|weather|discharge|species`,
  `/indices/{id}`, `/bathing-waters`, `/bathing-waters/{id}/samples`, `/qc/report`, `/reliability/campaign`,
  `/review/queue`, `/risk/{id}`; POST `/chat`.
- Everything else (docs, health, write routes `/review/{id}/decide` and `/fhir/export*`, external status, the explain
  routes) answers 404 without a backend call. Path segments are validated (`[A-Za-z0-9._:~-]`, at most 96 characters,
  no `.` or `..`), query parameters not listed are dropped and listed ones must match a pattern.
- The chat body is rebuilt from validated fields (limits of the contract: message and history texts 1 to 500
  characters, at most 6 history turns, country two letters, language 2 to 12 characters, `index` one of the four chat
  indices); unknown fields are dropped, the body is capped at 16 KB, and a cross-site `Origin` is refused with 403.
- The backend answer is passed through on success. On failure only the documented `{detail}` string (cut to 300
  characters) is returned, plus a sanitised `Retry-After` (whole seconds, 1 to 86400). A backend 401 is shown as a 502 so a
  wrong server key is never presented as the visitor's problem. Network failures become 502, a missing URL or key a
  503. Redirects are refused, the call times out after 70 s, responses are `no-store`.
- Per-visitor fairness: the first chat call sets an opaque random cookie (`oah_visitor`, HttpOnly, SameSite=Lax, 30
  days) and the handler sends it as `X-OAH-End-User` (a fairness aid of the backend, not authentication, see
  `docs/api_routes.md`). Real per-visitor limiting and bot protection still belong in the Vercel layer.

## 3. Screens

- **Sidebar:** country selector on top (`GET /countries`), **New question**, collapsible sections each with a `+`
  (new question in that section; not for Synthetic labs) and their indices from `GET /catalog?country=XX`. Only
  `applies: true` indices are shown and sections left empty disappear. No numbers appear on any entry (a test checks
  it). A dot gives the origin kind (real, external modelled, synthetic). Bottom: "Judge account" and Settings. A small
  notice appears when the catalogue says a store is not built.
- **Header:** title, "About this index" chevron (coverage for the country, kind, origins, data freshness, routes),
  download button (JSON of the table shown or, in Ask, of the data behind the latest answer: citations, evidence and
  steps, never the answer text) and the **map icon**.
- **Index page:** tabs **Ask** (chat) and **Data** (the route data behind the index: measurements, bathing waters
  and sample summaries, weather, discharge, species, water-quality index, data-quality report), each with origin
  badge, freshness and the notices and attribution the route returned. An index that does not apply to the country
  explains why instead of showing empty.
- **Chat:** answered, `withheld` (notice + `evidence` block), `withheld-ungrounded` (notice, the numbers that could not
  be matched, evidence), `no-answer`, `budget-exceeded` and `unsafe` (blocked notice; the text is never rendered, and
  a withheld response's text is never rendered even if sent). Each answer carries origin badge, grounded, freshness
  and language, the English original next to a translation (and a note when a translation was rejected), **Sources and
  method** inside the answer (data source and licence, method steps, limits, coverage flags, translation checks, all
  from response metadata, never model text) and the response's own disclaimer at the end. The model name is not shown.
  Language selector with the languages of `GET /languages` (26 in the backend), default English; the choice changes the whole interface, not only the answers (`docs/web_app_i18n.md`).
- **Map pane:** closed by default, opened only by the header icon; Leaflet with OpenStreetMap tiles and attribution,
  loaded only when opened. Markers are drawn as circles (no marker images), names are set as text nodes. A list below
  the map gives keyboard access. Selecting a place does not start a question; it shows a card and becomes the context
  of the next one.
- **Synthetic labs** (`/labs/...`): citizen science (`/reliability/campaign`, seed input), review queue (read-only,
  no decide control) and river risk (`/risk/{id}`), each under a permanent "Synthetic lab" banner and an origin badge.
- **Settings:** default language and default country (browser storage only, validated on read) and **About and
  attributions** (EEA, Open-Meteo, GBIF, OpenStreetMap, HL7 Europe sandbox) with the fixed notice.
- **Fixed notice** (every screen): "Screening against reference values, not legal compliance. No health or safety
  verdicts. AI answers are generated from tool results and are not verified."
- **States:** loading skeletons, error boxes with "Try again", **429** with the `Retry-After` countdown (Send is
  disabled and the retry button enabled when it reaches zero), 502/503/422/404 wording, and empty states.

## 4. Derived transformations (all in `web/src/`)

| Where | What | Source |
|---|---|---|
| `components/chat.tsx` `contextPrefix` | The contract has no site field, so a picked place is prefixed to the question as `About <name> (<id>): `; the question limit (500) is reduced by the prefix length. | `ChatRequest` in `docs/openapi.json` |
| `components/chat.tsx` `buildHistory` | At most 6 turns; user turns as typed; assistant turns only when answered and not unsafe, using `answer_en` when present; each cut at 500 characters. | `ChatRequest.history` limits |
| `components/map-pane.tsx` | Marker colour from `Site.ui_status`; the label reads "Index class (screening)". No new classification is computed. Bathing waters use the latest classification text as returned. | `Site`, `BathingWaterEntry` |
| `lib/format.ts` `previousYearRange` | Default window of weather and discharge: the previous calendar year. | UI default only |
| `lib/constants.ts` `ORIGINS` | Display label and kind (real, external, synthetic) per origin value. No value outside the contract's enum is produced. | `docs/web_app_design.md` |

No formula, FHIR code or threshold is introduced by the web app.

## 5. Security headers and rendering rules

- `src/proxy.ts` (the Next.js 16 name of middleware) sets, on every page and route: a CSP with a per-request nonce
  (`default-src 'self'`, scripts from `'self'` plus the nonce and `strict-dynamic`, `connect-src 'self'`, images from
  `'self'`, `data:` and `https://tile.openstreetmap.org`, `frame-ancestors 'none'`, `base-uri`, `form-action`,
  `object-src 'none'`, no `unsafe-eval` in production; `style-src` allows inline styles because Leaflet and the framework
  set style attributes), `Referrer-Policy: strict-origin-when-cross-origin`, `X-Content-Type-Options: nosniff`,
  `X-Frame-Options: DENY`, `Strict-Transport-Security`, and `Permissions-Policy` with camera, microphone, geolocation
  and payment off (`docs/predeploy_checklist.md` section 3). The layout reads the request headers so every page is
  dynamic and the nonce is applied.
- All backend and model text is rendered as React text nodes: no `dangerouslySetInnerHTML`, no markdown, no HTML
  strings (ESLint `react/no-danger` plus `tests/security.test.ts`, which also checks that the key variables are read only
  in `lib/server/config.ts` and that no client file imports server code or ships the key header).
- Browser storage holds only the settings (country and language), validated on read; it works without storage.

## 6. What was verified, and what was not

- Verified here: type check, lint and 129 Vitest tests pass (unit, contract against `docs/openapi.json`, seeded fuzz of
  the allow-list, static security and portability checks, component tests that run the real proxy handler on mock
  data); a production build succeeds; the built app was driven in a headless Chromium on mock data (sidebar, data tab,
  map pane, chat with a translated answer, withheld answer, labs, settings, dark mode, a 390 px wide viewport without
  horizontal scroll, the response headers).
- Real mode was exercised end to end against a local stand-in backend that checks the key header: the key and the
  `X-OAH-End-User` token arrived only on the server-to-backend calls (the token only on chat), the browser contacted
  its own origin only, the key appeared in no page or API body, a 429 showed the countdown, and the mock banner was
  absent. This proves the plumbing, not the real backend.
- Not verified: the real backend (not available in this session); OpenStreetMap tiles (outbound access to the tile host
  is blocked in the build environment, so only the markers and the attribution were seen); the Vercel deployment and the
  CSP under its edge; screen readers; the machine-drafted translations shown by the backend.
- `npm audit` reports advisories in build-time dependencies (glob matching in `eslint-config-next`); nothing it flags is
  shipped to the browser or used at run time.
