# Demo plan: five days to the submission

**Superseded (2026-10-04):** the product built is the chat web app described in `docs/web_app.md`, and the video plan is
`docs/demo_video_script.md`. Kept for the history of the decisions.

Status: 2026-09-30. Definition only: no frontend code exists yet. This plan replaces the open scope questions of
`docs/frontend_conceptual_design.md` (read that document for the analysis behind it).

**Correction (2026-09-30, same day): section 1 below is superseded.** The maintainer corrected the direction: the
demo must be a **public URL where anyone can create an account**, with a fully functional interface (not a static
precomputed site, and screens are not the point). Infrastructure is available and settled: a GCP account (for the
Python backend, for example Cloud Run), Supabase (accounts and Postgres) and Vercel (the web app). The design work
now starts from what an account lets a person do, how open sign-up is kept safe and affordable, and what the
backend must change to serve real users: see `docs/accounts_and_functionality_design.md`. The schedule, the P0/P1
cut line idea, the video outline and the submission items below still apply, but must be re-estimated once the
functional scope is chosen.

**Constraints given by the maintainer:** the hackathon deadline is fixed (7 October); the backend is done; the
public repository will be a new one (its history does not matter); two days to build the frontend, two days to test
and record together, one day for the submission; everything made with AI assistance and CapCut for the video.

**What the organisers ask for:** the track and how the project answers it; a project description (problem, solution,
target users, expected impact on ecosystems and human health); a 3 to 5 minute demo video; a public code repository
with source and documentation; a working prototype. Judging: impact and alignment 30%, innovation 20%, technical
implementation 20%, usability and experience 15%, feasibility and scalability 15%. Submissions must not violate
copyright, licensing or third-party IP, and must be original and developed during the hackathon period.

## 1. Architecture for the demo: precomputed, static, no server to keep alive

A script runs the real Python pipeline locally and writes the results as JSON files; the website is a static site
that reads them. There is no Python host, no database, no cold start, no secret on the host and no cost exposure.
The backend stays in the repository as the engine (and can be shown running locally in the video).

```
sandbox snapshot (frozen, dated, hashed)
        |  scripts/export_demo_data.py   (the existing pipeline: indices, limit_basis, QC, FHIR output,
        v                                 synthetic campaign, risk topology, pre-generated explanations)
   web/public/data/*.json  --->  static site on Vercel (Next.js)
```

Honest labelling: "computed from a snapshot of the public sandbox taken on <date>" on every real-data screen. Supabase
is not used in the demo (nothing to store, no accounts).

| File | Content | Origin |
|---|---|---|
| `meta.json` | snapshot date and hash, counts, the interpretation notice, the limits source text, model and date of the explanations | real |
| `sites.json` | every Location with position, kind (water body, air-quality station, city), status, score, class, confidence, veto, regime and country | real |
| `site/<id>.json` | per-parameter measurements (value, unit, limit, excursion, basis, verification state), veto detail, data-quality counters in plain language | real |
| `explanation/<id>.json` | the model's description and assessment, generated once offline, with grounding flags, model and date | real evidence, model text |
| `health/<city>.json` | aggregated population-health indicators per city and group (percentages) | real, aggregated |
| `lab/campaign.json` | citizen-science campaign: majority vote versus Dawid-Skene, per-observer reliability | synthetic |
| `lab/review.json` | a sample prediction-set queue (decisions are kept in the browser only) | synthetic |
| `lab/risk.json` | propagated risk on the demo river topology | synthetic |
| `fhir/indicators-bundle.json` | the exported FHIR Bundle of the indices, for download | real-derived |

**Backend work (about half a day):** the export script; per-parameter measurement detail and a site-kind field (the two
approved endpoint additions, here as export content); an optional command that regenerates explanations with the
maintainer's own model key.

## 2. Screens and the cut line

| Priority | Screen | What it shows | Judging criteria served |
|---|---|---|---|
| P0 | Map | sites with status by colour, shape and text; legend; fit to the sites; snapshot and notice banners; a list view | usability, technical |
| P0 | Site detail (Almyros) | score and class in words, confidence, veto explained, the limit regime, a per-parameter table with value, limit, basis and verification state, what was left out and why | impact, technical, usability |
| P0 | Explanation | the pre-generated description and assessment with the grounding badge and the model's disclaimer, shown as plain text | innovation, technical |
| P0 | Method and trust | the index in plain words, the limit regimes, sources and licences, what the tool is not, the architecture, test and audit figures | feasibility, technical |
| P1 | Citizen-science lab | the campaign (majority vote versus Dawid-Skene), the review queue with decisions kept in the browser, the risk graph; permanently labelled synthetic | innovation, impact |
| P1 | FHIR output | download of the Bundle and a short explanation of the HL7 Europe profiles and sandbox it follows | feasibility |
| P2 (stretch) | One Health context | population-health indicators for Benevento and Oslo beside what the water index covers, with the statement that the water data and the health data are at different places and no causal link is claimed | impact (30%) |
| P2 (stretch) | Spanish translation | labels only | usability |

**Real data limits to design around** (read from the public sandbox on 2026-09-29): 23 Locations; 12 are
Benevento air stations; only the Almyros site has evaluable water data (the Giofyros reaches only have water
temperature, which is not scored for Greek rivers); 141 population-health Observations exist for Oslo (81) and Benevento
(60), all aggregated percentages by group (for example BMI classes, long-term disease, high cholesterol). The demo
therefore tells a story of trust and method, with Almyros as the hero site, not one of volume.

## 3. Technology (decided, change only with a reason)

Next.js (App Router, static generation) with TypeScript on Vercel; Tailwind CSS; Leaflet with a tile provider that
tolerates public traffic (OpenStreetMap attribution required); the interface in English (the judges are
international and the backend texts are English); a typed loader for the JSON files, with the types written from the
export script's schema so the files cannot drift from the screens; Vitest for the data loaders and one browser smoke
test. All text rendered as plain text, never as HTML.

## 4. Schedule

| Day | Date | Work |
|---|---|---|
| 1 | 1 October | export script and data files; scaffold, design tokens, map and list wired to the data |
| 2 | 2 October | site detail, trust layer, explanation, method page, lab (P1); first deployment to Vercel |
| 3 | 3 October | functional, keyboard and mobile testing; fixes; video script and shot list; start recording |
| 4 | 4 October | finish recording; edit in CapCut (captions, voice-over); README, project description and Devpost text; the new public repository created from a clean copy |
| 5 | 5 October | submission and a final check of the deployed site and the repository; 6 and 7 October kept as reserve |

If a day slips, drop P2 first, then the FHIR page, then the review queue; never drop the trust layer or the method page.

## 5. Video and submission (prepared with AI assistance)

Video 3 to 5 minutes, in English with captions: (1) the problem (urban streams and health, one sentence), (2) the map
and the one real site, (3) why the score can be trusted (limits with their source, freshness, the veto, what was left
out), (4) the model explanation and how it is checked, (5) the citizen-science lab and its uncertainty handling,
(6) the FHIR output and the HL7 integration, (7) the test and audit figures and the repository. The script and shot
list are written before recording; the voice-over and captions are produced in CapCut.

Submission checklist: track statement; description (problem, solution, users, impact on ecosystems and health); video;
public repository with source and documentation; live prototype link; Devpost registration confirmed before the
deadline.

## 6. Repository and eligibility items for the submission day

- A new public repository from a clean copy (the history is not carried over). Confirm that no file with an
  unstated licence is included: the implementation-guide archive, the organisers' slides and the reference archives
  stay out (the guard test checks this).
- State the origin clearly in the README: which modules were adapted from the author's earlier projects
  (`SOURCES.yaml` lists them) and what was developed during the hackathon, because the rules require the project
  to be original and developed in the hackathon period.
- The hand-off ledger and the two hand-off notes contain a personal e-mail address and the names of a private cloud
  project and bucket: publish a trimmed version or leave them out of the public repository.
- Keep the honesty statement visible: reference values, not legal compliance; synthetic data always labelled.

## 7. Open items

1. The track chosen (needed for the description, not for the build).
2. Narration: English recommended; the maintainer's decision.
3. Whether the One Health context screen (P2) is attempted.
4. Confirmation of the trimmed ledger approach for the public repository.
