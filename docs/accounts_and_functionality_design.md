# Accounts and functionality: design for a public, fully functional demo

Status: 2026-09-30. Analysis and decisions only; no code. Supersedes the static-site architecture of
`docs/demo_plan.md` section 1. Direction from the maintainer: a **public URL where anyone can create an account**, a
fully functional interface (screens are not the point), infrastructure already available: a GCP account, Supabase,
Vercel and Claude. The interface language is English.

## 1. Topology

```
Browser --> Vercel (Next.js web app) --> Supabase Auth (sign-up, sessions, JWT)
   |                                          |
   +---- Authorization: Bearer <JWT> --> FastAPI on GCP Cloud Run --> Supabase Postgres
                                         (verifies the JWT against the project's published keys,
                                          holds the Anthropic key, calls the HL7 Europe sandbox)
```

- The browser never holds a secret: the JWT is a per-user token, the model key lives only on Cloud Run, the database
  is reachable only through the API (Row Level Security enabled on every table with no policy for browser roles).
- The backend verifies the Supabase JWT against the keys published at the project's JWKS address, so no shared secret
  is configured on it (https://supabase.com/docs/guides/auth/signing-keys). The shared API key stays only as an
  operations credential.
- Cloud Run starts with a **single instance** so the existing in-process rate limiter, spend guard and caches stay
  valid; scaling out later means moving those counters to Postgres. Cloud Run's filesystem is ephemeral, so every file
  and SQLite store must move to Postgres (section 5). Keep one instance warm during judging to avoid a cold start.
- CORS allows only the Vercel origin (the setting already exists). The Vercel app can also proxy through its own route
  handlers; either works.

## 2. What an account is for (the functional core: a decision needed)

The product idea is monitoring and awareness of urban streams with citizen science. A signed-in person should do
something real, not just look. Options, by what the existing backend already supports:

| Option | What the person does | Backend support today | Gaps and risks |
|---|---|---|---|
| A. Contribute a macroinvertebrate sample | picks a site and date, enters taxa and counts from a controlled list | diversity indices (Shannon, Simpson, Pielou, Chao1) take counts; BMWP and ASPT take a regional tolerance table that the repo does not ship | needs storage, a controlled taxa list, validation, moderation; a sourced tolerance table is needed for BMWP (diversity needs none) |
| B. Annotate specimens | labels images of specimens | reliability model (Dawid-Skene), conformal sets, review queue (all synthetic today) | no real specimen images exist; storage and moderation of images |
| C. Report a pollution observation | picks site and a category, structured only | none | storage, moderation, map layer |
| D. Explore and ask for AI explanations | reads the water index and requests a checked explanation | complete | accounts only gate cost |

Recommendation: **A plus D**, with a reviewer role approving contributions before they count. It reuses the diversity
code, the review queue and the audit trail, gives a closed loop (contribute, review, see the effect on a site), and
needs no images or free text, which keeps moderation and privacy simple. B and C are later.

## 3. Roles and sign-up

| Role | How obtained | Can |
|---|---|---|
| Visitor | no account | read the public map, site pages and method |
| Citizen | self sign-up | everything above, request explanations within a personal daily cap, submit samples (pending until approved), see own contributions |
| Reviewer | granted by an administrator (a flag in the user's server-side metadata, never self-service) | approve or reject pending samples, decide queued items |
| Administrator | the maintainer | grant roles, view usage, switch features off |

**Sign-up methods to choose from:** e-mail with password and confirmation; magic link; Google sign-in (convenient, since
a GCP account exists). Recommendation: e-mail confirmation plus Google, with a CAPTCHA on sign-up (Supabase supports
it) to slow bots.

## 4. Keeping open sign-up safe, private and affordable

| Risk | Control |
|---|---|
| Cost of the model | explanations only for signed-in users; a personal daily cap and a global daily cap, both enforced by the backend before any call; pre-generated explanations for the demo sites cost nothing; alert and a hard stop on the Anthropic console |
| Bot sign-ups | e-mail confirmation, CAPTCHA, Supabase rate limits, a daily new-account ceiling the administrator can lower |
| Spam and false data | contributions are structured (no free text, no images), validated server-side, pending until a reviewer approves, rate-limited per user, and labelled "citizen contribution" with the reviewer's approval state |
| Personal data | the application stores only the pseudonymous user id and a chosen display handle; the e-mail stays in Supabase Auth; the audit trail records the user id, never the e-mail; consent recorded at sign-up (the project already has a consent record type); a privacy notice and terms page; account deletion removes the profile and anonymises the contributions |
| Location privacy | contributions attach to existing monitored sites, not to a person's position; any coordinate a user could enter is generalised with the project's existing geo-generalisation module |
| Abuse of write routes | roles checked on the server for every write; per-user and per-IP limits (the proxy-aware limiter exists) |
| Data integrity | the hash-chained audit trail covers decisions and contributions; verification endpoint for administrators |

## 5. Backend changes this requires

1. **JWT verification dependency** replacing the shared key for user routes: verify the signature and expiry, read the
   user id and the role from the token, reject anything else; the shared key remains for operations.
2. **Postgres stores** in place of SQLite and files: the review store and audit chain (the chain tail read and the
   insert in one transaction with a lock), the LLM audit log, per-user usage counters, and the new contribution tables.
3. **Per-user budget** on the explanation route (and the global cap), with the remaining budget returned to the user.
4. **New endpoints (approved by the maintainer):** per-site measurement detail, a site-kind field, an explanation
   language parameter, `GET /me`, size limits on lists; plus the contribution endpoints of option A (create a sample,
   list own samples, list pending samples for reviewers, approve or reject) and the sample's indices.
5. **Exports and snapshots** to Postgres or returned in the response instead of files.
6. **Deployment:** a container image, Cloud Run settings (one instance, a request timeout above the model timeout),
   the environment (Supabase URL, Anthropic key from a secret store, allowed origin), a health check.
7. **Tests** for every new rule (roles, caps, validation, the atomic audit write, token rejection) in the existing
   style, and the same quality gates in CI.

Data model (names only): profiles, sites (references to sandbox Locations), samples, sample taxa and counts, taxa list,
review items, audit events (chained), LLM audit events, usage counters.

## 6. Scope and schedule: the risk

This is larger than the static plan. Honest estimate with five days left: backend (items 1 to 4 and 6, the tests) about
two days; web app about two days; testing, recording and submission about two days, so the schedule is tight and needs
a cut line:

| Milestone | Content | If time runs out |
|---|---|---|
| M1 | sign-up and sign-in, public map and site detail, per-parameter table with the trust layer, checked explanations with personal and global caps, deployed on Vercel, Cloud Run and Supabase | never cut |
| M2 | contribute a sample, reviewer approval, the diversity indices on the site page | cut the review step first (contributions shown as unreviewed), then the indices |
| M3 | the synthetic lab pages, the FHIR download, the One Health context | cut first |

## 7. Decisions needed (in this order)

1. The functional core: A plus D (recommended), or something else?
2. Sign-up methods: e-mail confirmation plus Google, with CAPTCHA?
3. Who can approve contributions: only the administrator for the demo, or a reviewer role with a few invited users?
4. Caps: daily explanations per user (suggest 3) and globally (suggest 100)?
5. Is a regional tolerance table available for BMWP (with its source and licence), or do we show diversity indices only?
6. Cloud Run in which region, and is a warm instance acceptable?
