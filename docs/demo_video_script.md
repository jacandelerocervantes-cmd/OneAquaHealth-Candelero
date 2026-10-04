# Demo video: script, shot list and production

Status: 2026-10-04. Replaces the video outline of `docs/demo_plan.md` (written on 2026-09-30 for a static site that was
not built). Requirement of the organisers: a demo video of 3 to 5 minutes. Target: about 4 minutes 30 seconds, English
narration with English subtitles, recorded on the LIVE site with real data, plus one scene on the standards work.

## Track and message

- **Track 7: Digital Health Standards** ("enable interoperability across systems; fragmented data and lack of standards;
  build FHIR models, AI agents and integration frameworks"). Decision of the maintainer. Name it once, at the start.
  The scoring criteria and their weights are the same for every track (impact 30%, innovation 20%, technical 20%,
  usability 15%, feasibility 15%), so the track changes who the project is compared with, not how it is scored.
- What supports the track, and only what exists (see `docs/fhir_mapping.md`):
  - **FHIR in**: the public HL7 Europe OneAquaHealth sandbox is a FHIR R4 server; the backend reads its Locations and
    Observations and treats the implementation guide's profiles as the contract (no code is ever invented; provisional
    codes are marked as provisional).
  - **FHIR out**: derived indicators and quality-control findings are exported as FHIR R4 Bundles (Observation conforming to
    `observation-indicators-oah`, `DetectedIssue`, `Provenance`, `Device`); synthetic data carries `meta.tag` synthetic
    and a Provenance with the generator seed. The official HL7 validator, run against the IG built with SUSHI, found
    **0 errors** on 485 real sandbox resources (23 September); the warnings are the guide's own provisional terminology.
  - **Integration across systems**: one typed contract (`docs/openapi.json`) in front of FHIR, the EEA data and the
    modelled context, each labelled with its origin; a web app that only reaches an allow-list of routes.
  - **AI agent**: a read-only tool-use agent whose answers are checked against the data it retrieved, with sources,
    licence and limits shown, and no health verdicts (human judgment stays with the competent authority).
- One sentence the video must leave: **standards on the way in and on the way out, and an AI agent on top that checks its
  own numbers.** Tagline: *Ask the water. Get the data, not a verdict.*
- Where each judging criterion is served: impact and alignment (scenes 1, 7), innovation (scenes 3, 5), technical
  implementation (scenes 5, 6), usability (scenes 2, 4), feasibility and scalability (scenes 6, 7).
- The web app does not show FHIR by itself. Scene 5 is therefore a real screen of the exported Bundle and of the
  validation evidence (not a mock-up), and the narration says where each piece lives.

## Narration and shots (about 590 words)

| # | Time | On screen | Narration |
|---|---|---|---|
| 1 | 0:00-0:30 | Live site, home page, title AquaLedger | "Water data is fragmented: different agencies, formats and languages, and a citizen or a local officer cannot simply ask it a question. This is our entry for Track 7, digital health standards: AquaLedger connects standards-based data, FHIR on the way in and on the way out, with an AI agent that can explain it but never replaces human judgment." |
| 2 | 0:30-1:00 | Country selector, sidebar sections, origin legend, site search typing "lago c" in Italy | "Pick a country: Greece, Italy or Norway. Data comes from the public HL7 Europe OneAquaHealth sandbox, a FHIR server, from the EEA Waterbase for rivers and lakes, and from the Bathing Water Directive results. Each entry says what it is: real data, modelled context, or synthetic. They are never mixed silently." |
| 3 | 1:00-2:00 | Question 1 (what information is available), open "Sources and method"; question 2 (a change between two periods); then the health question | "Now ask. A read-only agent picks which data tools to call. Open Sources and method: every source, its licence, each tool call, and the reference values used, labelled as screening aids, not legal limits. Before an answer is shown, every number and unit is checked against the data the agent retrieved. If the check fails, the answer is withheld and the evidence is shown instead. And when we ask whether a beach is safe to swim, it declines and points to the competent authority. That is human-in-the-loop by design." |
| 4 | 2:00-2:30 | Map (expanded) with a picked bathing water; an index with the data under the chat and the download; language switched to Spanish | "The map shows the places of the country, or only those of the index you are in. The data sits under the conversation, and one click downloads it. Switch the language and the whole interface follows, in 26 languages, checked automatically so a translation never adds a link, and labelled as machine-drafted." |
| 5 | 2:30-3:30 | Water parameters of a site: click "Download as FHIR"; the downloaded Bundle shown in a plain page (Location, Observation, Provenance, data-origin tag); the "Real · HL7 Europe sandbox" entry; the validation evidence | See `docs/demo_video_narration.md`, scene 5 (the master text: it describes the download, the Provenance, "no invented code" and the official validator result on 485 real sandbox resources). |
| 6 | 3:30-4:00 | Repository on GitHub, README, CI checks, a quick scroll of the docs | "Under the hood: a FastAPI backend on Cloud Run and a Next.js web app, with the key kept on the server. Rate limits and spend caps protect the budget, a hash-chained audit log records every request without storing questions, and more than three thousand automated tests run on every change. The repository is public and documented, so anyone can run the backend, rebuild the data and deploy it." |
| 7 | 4:00-4:30 | Back to the home page, tagline on screen | "For One Health, this closes the gap between public monitoring data and the people who need to act on it. Adding a country means one more data store, not a rewrite, and the standards keep it interoperable. AquaLedger: ask the water, get the data, not a verdict." |

The text read aloud lives in `docs/demo_video_narration.md` (with the respellings for the voice); the table above is the plan of shots.

Questions to use are fixed after a dry run on the live site (they must answer and pass the checks); the narration names
only the kind of question. Do not claim anything the screen does not show. The validation figures are from the run of 23
September (`docs/fhir_mapping.md`); say "run against the implementation guide", not "live".

## Production (nothing here touches the repository)

1. **Dry run**: ask the candidate questions on the live site and keep the ones that are answered, grounded and not
   withheld. About eight model calls are used in total (the deployed copy allows 25 a day).
2. **Standards screen (scene 5)**: on the live site click "Download as FHIR" under the measurements of a site, then show
   the downloaded Bundle in a plain page with the Observation, the Provenance and the data-origin tag highlighted, next
   to the "Official validation evidence" section of `docs/fhir_mapping.md` (the validator result is from 23 September
   and covers the sandbox resources and the indicators Bundle, not this download: the narration says so as "run against
   the implementation guide").
3. **Recording**: a script drives Chromium (Playwright) through the scenes against the live URL, at 1920x1080, and saves
   one WebM per scene. Real data, no mock mode.
4. **Voice**: the narration text above is sent scene by scene to the ElevenLabs text-to-speech service. The key is set by
   the maintainer in their own terminal and is never shown to the assistant; the maintainer runs that one step.
5. **Assembly**: ffmpeg joins the scenes, mixes the voice, burns the English subtitles (an SRT written from the same
   text) and exports an MP4. Each scene is stretched or trimmed to its voice length.
6. **Review** by the maintainer before upload; upload to YouTube or Vimeo, link in Devpost.

## Checklist before recording

- The live site shows real mode (no "Mock data mode" banner), English interface, no leftover context chip.
- The daily model cap has room (the counter is per day).
- The browser has no personal bookmarks or tabs; the recording uses a clean profile.
- No secret, key or personal e-mail appears on screen (the Cloud console is never shown).
