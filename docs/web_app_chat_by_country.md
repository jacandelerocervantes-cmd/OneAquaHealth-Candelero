# Web app definition: chat interface organised by country

Status: 2026-10-02. Derived only from what the code does today (inventory of `src/oah/api/` and
`src/oah/indices/regimes.py`). It supersedes the account and sign-up design in
`docs/accounts_and_functionality_design.md` and section 14 of `docs/frontend_conceptual_design.md`
for the demo. Demo version only: reference values, not legal compliance (`interpretation_notice`).

## 1. Decisions (maintainer, 2026-10-02)

1. The web app is a **chat interface** (ChatGPT, Claude or Gemini style), rebuilt from scratch; the old `frontend/` is discarded.
2. **No per-user accounts.** One shared access with rate limiting. Secrets live only in the hosting providers' environment variables (Vercel, Supabase, GCP); nothing secret in the repository or in the browser.
3. **Country selector** in the top bar (like choosing amazon.com versus amazon.com.mx). The selected country is the context of every request and answer.
4. The interface is in English. Scope is only what the code already supports; no new design work beyond the small gaps in section 6.

## 2. Reality check: what the backend can and cannot do

- There is **no free-text chat** backend. The explanation layer takes only an evidence JSON for one site (or review item) and a mode (`describe` or `assess`). So the chat is a **canned-intent front end**: the user types or taps an intent ("show sites", "explain Almyros", "assess Almyros", "why can I trust this score?") and the app maps it to endpoints. Free-text understanding is out of scope (it would need a new model-driven router with its own spend guard).
- There is **no country parameter** on any route. Country exists only as `limit_country` on evaluated sites. The country grouping is therefore built in the web server layer (section 5) until the backend gets a small endpoint (section 6).
- Supported country codes: `GR` (Greece, national river limits, alias `EL`), `IT` (Italy, national river limits), `NO` (recognised, EU values only). Any 2-letter country can be added through `OAH_LIMITS_FILE` if a location resolves to it.
- Real data today: 23 Locations; 12 are Benevento air stations (not water); only **Almyros (Crete, GR)** has evaluable water data. Italy and Norway appear on the map but are not evaluated. The UI must say so plainly instead of hiding the country.

## 3. Technology stack

| Layer | Choice | Notes |
|---|---|---|
| Web app | Next.js (App Router, TypeScript) on Vercel | Chat UI, country selector, plain-text rendering only |
| Styling and map | Tailwind; Leaflet with OpenStreetMap tiles | Attribution required |
| Server layer | Next.js route handlers (same origin) | Holds the backend key; browser never sees it |
| Backend | Existing FastAPI (`src/oah/api/app.py`) on GCP Cloud Run | One instance, so the in-process limiter, daily cap and cache stay valid |
| Storage | None required for the demo | Supabase optional later (for example persisted chat history or a shared counter) |
| LLM | Anthropic API via the backend, default `claude-sonnet-5-5` | Overridable with `OAH_LLM_MODEL` |
| Types | Generated from an exported OpenAPI file | Backend addition, section 6 |

Access control: one shared access protected at the hosting layer (Vercel deployment protection or a single shared passphrase checked in a route handler; decide at deployment). Rate limiting is two-level: Vercel route handler (per client) plus the backend's own limits (below). The browser calls only the same-origin route handlers, which add `X-API-Key` server-side.

## 4. Backend routes the chat uses (existing)

All routes except `/health` require header `X-API-Key` (= `OAH_API_KEY`) and pass the per-host rate limit (default 60 per 60 s). Every data response carries `origin` (`real-sandbox` or `synthetic`) and, for real data, `data_freshness`.

| Intent in the chat | Route | Notes |
|---|---|---|
| Health check | `GET /health` | No auth |
| List sites, map | `GET /sites` | Fields: id, name, latitude, longitude, status, ccme_wqi, ccme_class, ui_status, limit_regime, **limit_country**, confidence, veto_triggered, eclipsed, reason; plus `interpretation_notice` |
| Site detail and "why trust this" | `GET /indices/{location_id}` | Adds `limit_basis` per parameter, data quality counts, `confidence_note`, `limit_overrides`; skipped sites carry `reason` |
| Explain or assess a site | `GET /explain/indices/{location_id}?mode=describe\|assess` | See rules below |
| Data quality overview | `GET /qc/report` | Findings by type |
| FHIR output | `POST /fhir/export`, `POST /fhir/export/indicators` | Currently written to server files; should be returned in the response (section 6) |
| Synthetic citizen-science lab | `GET /reliability/campaign?seed=...` | **Synthetic only**; label it |
| Synthetic review queue | `GET /review/queue`, `GET /explain/review/{id}`, `POST /review/{id}/decide` | **Synthetic only**; write route disabled in the shared demo |
| Synthetic river risk | `GET /risk/{site_id}` | **Synthetic only**; fixed demo topology |

Explanation rules the UI must honour:
- Render as **plain text only**. If `unsafe` is true, do not render the text; show the flags instead.
- Always show the `disclaimer`, the `grounded` state (with `ungrounded_numbers` if any), and whether the answer was `cached`.
- Limits: 5 per minute per client (`OAH_EXPLAIN_RATE_LIMIT_PER_MINUTE`), 100 per rolling 24 hours for the whole process (`OAH_EXPLAIN_DAILY_CAP`), identical requests cached 600 s (`OAH_EXPLAIN_CACHE_TTL_SECONDS`). Handle 429 with `Retry-After`, plus 404, 422, 502 and 503, in chat bubbles.
- The explanation language is English only today.

## 5. Country model

- **Source of truth:** `limit_country` from `/sites` and `/indices`, resolved by `country_for_location` in `src/oah/indices/regimes.py` (id override, description suffix, country name suffix, then `partOf` parent; never guessed, may be null).
- **Selector contents:** the distinct non-null `limit_country` values, plus any code from the exported country list once available (section 6). Show each with its status: "national limits", "EU values only" (NO), or "no evaluable water data".
- **Unresolved sites (country null)** are listed under "Other or unknown" and are never attributed to a country.
- **Switching country** resets the chat context: the map is filtered, the quick-intent chips list only that country's sites, and every answer states which regime and which limit sources apply (`limit_regime`, `limit_basis`).
- **When directives change:** edit the limits override file (`OAH_LIMITS_FILE`, schema in `docs/limits_override.example.json`, rules in `src/oah/indices/limit_overrides.py`). It reloads on change, `limit_basis` then reads `override: <source>`, and the selector picks up any new country once its locations resolve to it. No web app change is needed. Verification labels: `docs/limits_verification.md`.

## 6. Small backend additions (the only new work)

1. `GET /countries`: distinct countries with regime, limit sources, and counts of evaluated and skipped sites. Removes the client-side grouping and makes the selector authoritative. Skipped sites currently do not carry `limit_country`; include it for them where resolvable.
2. Per-site measurement detail (approved earlier): the per-parameter values behind the score.
3. A site-kind field (water body, air-quality station, city), so air stations are not shown as water bodies.
4. An exported OpenAPI file for generated types.
5. FHIR export returned in the response (or stored) instead of written to a server file.
6. Optional: an explanation `language` parameter (approved earlier; not needed for the English demo).

Not needed now: JWT verification, Postgres stores, contribution endpoints, per-user budgets. Library-only capabilities (biotic and diversity indices, conformal sets, privacy modules) stay unexposed.

## 7. Environment variables (names only)

Backend (Cloud Run secrets and settings): `ANTHROPIC_API_KEY`, `OAH_API_KEY`, `OAH_CORS_ORIGINS` (the Vercel origin only), `OAH_RATE_LIMIT_MAX_REQUESTS`, `OAH_RATE_LIMIT_WINDOW_SECONDS`, `OAH_EXPLAIN_RATE_LIMIT_PER_MINUTE`, `OAH_EXPLAIN_DAILY_CAP`, `OAH_EXPLAIN_CACHE_TTL_SECONDS`, `OAH_ENABLE_DOCS`, `OAH_TRUSTED_PROXIES`, `OAH_LLM_MODEL`, `OAH_LIMITS_FILE`, `OAH_DATA_DIR`, `OAH_SANDBOX_URL`. Never set `OAH_INSECURE_NO_AUTH` in a public deployment.
Vercel (server only, never `NEXT_PUBLIC_`): the backend base URL and `OAH_API_KEY`.
Gaps in the example file: `.env.example` lacks `OAH_LIMITS_FILE`, `OAH_EXPLAIN_*`, `OAH_DATA_DIR`, `OAH_SANDBOX_URL` and `OAH_INSECURE_NO_AUTH`; add the non-secret ones when the deployment is prepared.

## 8. Minimum screens and cut line

- **Must:** top bar with country selector and an honesty banner (demo, not legal compliance); chat panel with intent chips; map panel; site card with score, class in words, confidence, veto, `limit_basis` table, freshness; explanation bubble with its trust badges.
- **Should:** `/qc/report` summary; FHIR download.
- **Could (cut first):** synthetic lab, review queue and river risk pages, each clearly labelled synthetic.
- Always state the facts honestly: only Almyros has real evaluable water data.

## 9. Open points

1. Shared access method: Vercel deployment protection versus a shared passphrase (the first depends on the Vercel plan).
2. Whether chat history is kept (browser only, or Supabase).
3. The track chosen for the hackathon, and the repository ledger trimming for the public copy.

## 10. Language selector (added 2026-10-02)

Maintainer request: a language switch so each user can use the app in their own language, with as many official EU languages as are feasible.

- **Where it lives:** next to the country selector in the top bar and remembered per browser. The language selector is independent of the country selector (a Greek river can be read in Spanish).
- **Two separate layers:**
  1. Interface labels, fixed texts, the disclaimer, the honesty banner, status words and error messages. These are static translations kept in the web app, never produced by the model at run time. The disclaimer and the interpretation notice must exist as reviewed fixed strings per language.
  2. Chat answers. The backend gets a `language` parameter (already an approved addition) and the model writes the answer in that language. The facts, numbers, units, limits and sources still come from tool results.
- **Risk to handle before enabling a language for chat answers:** the output guard and the number check were written for English. They need, per language, (a) decimal-comma and thousands-separator handling and number words in the grounding check, (b) the patterns for unsupported health claims, potability statements, links and instruction leaks, and (c) tests. A language is switched on for chat answers only when its checks and tests exist; until then the chat falls back to English and says so.
- **Proposed rollout:**
  - Tier 1, interface and chat: English, Spanish, Italian, Greek, Norwegian (Bokmal; Norway is covered by the data although it is an EEA, not EU, country), plus French, German and Portuguese.
  - Tier 2, interface only at first: the remaining official EU languages. Translations are machine drafts and are labelled as such in the interface until reviewed by a native speaker.
- **Implementation note (2026-10-02, language package):** the backend took a different route from the per-language guard packs above:
  English pivot with language-neutral verification (`docs/language_support.md`). Chat and explanation answers are produced and
  guarded in English, then translated by one more constrained call and verified (identical numbers, no links, bounded length, ...);
  `GET /languages` lists 26 languages (es-MX and es-ES, plus Bokmal), all machine-translated and flagged. The web app should show
  `answer_en` as the "original" and the `notices` from the response; the interface labels remain the web app's own static files.
- **Not translated:** codes, parameter names that come from the data (shown with the original label), site names, and source citations.
- **Cut line:** this is M3. M1 ships English (and Spanish labels if time allows); the selector structure is built from the start so adding a language is adding a file.
