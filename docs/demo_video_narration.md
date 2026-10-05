# Demo video narration (text for the voice)

Status: 2026-10-05, final version. The text below is what is read aloud, scene by scene, in English (about 620 words, about
4 minutes 30 seconds at a calm pace). It follows `docs/demo_video_script.md` (the table of shots and the production steps)
and is written so that the video serves the five judging criteria: impact and the One Health link (scenes 1, 4), innovation
(scenes 3, 5), technical implementation (scenes 6, 7), usability (scenes 2, 4, 5) and feasibility and scalability, told as
what can be done next and how (scene 8). It is meant for a text-to-speech voice (the maintainer's own voice, replicated with
ElevenLabs): paste each scene as ONE block, in order.

## Spellings for the voice

A text-to-speech engine reads some names badly. Paste the VOICE text of each scene; the subtitles use the normal spelling.

| In the subtitles | In the voice text | Why |
|---|---|---|
| FHIR | fire | the standard is pronounced "fire" |
| HL7 | H L seven | letters and number |
| EEA | E E A | letters |
| E. coli | E coli | no pause at the full stop |
| AquaLedger | Aqua Ledger | two words |
| OneAquaHealth | One Aqua Health | three words |

## Scene 1 (about 25 s)

> Water data is fragmented. Different agencies, different formats, different languages, and a citizen or a local officer
> cannot simply ask it a question. This is our entry for Track 7, digital health standards. Aqua Ledger puts
> standards-based water data behind one interface, with an AI agent that explains it, checks its own numbers, and never
> replaces human judgment.

## Scene 2 (about 30 s)

> Pick a country: Greece, Italy or Norway. The data comes from the public H L seven Europe One Aqua Health sandbox, which
> is a fire server, from the E E A Waterbase for rivers and lakes, and from the Bathing Water Directive results. Every
> entry says what it is: real data, modelled context, or synthetic. They are never mixed silently. Search a site as you
> type, and pick it.

## Scene 3 (about 60 s)

> Now ask. A read-only agent chooses which data tools to call. Open Sources and method: every source, its licence, each
> tool call, and the reference values used, always labelled as screening aids, not legal limits. Before an answer is
> shown, every number and unit is checked against the data the agent retrieved. If the check fails, the answer is
> withheld and the evidence is shown instead. And when we ask whether a beach is safe to swim, it declines and points to
> the competent authority. That is human in the loop by design.

## Scene 4 (about 35 s)

> The data sits under the conversation, and one click downloads it. The map shows the places of the country. For One
> Health, weather, river discharge and species records add context around the measurements, each one labelled as modelled
> context, never as a measurement. Change the language next to the country, and the whole interface follows, in twenty six
> languages, labelled as machine drafted.

## Scene 5 (about 18 s): what "Not scored" means

> A note on honesty. In the Reference check column, Not scored means the value is shown exactly as measured, but there is no
> limit to compare it with. For turbidity, organic matter and lakes, this project has no limit regime, and we never invent
> one. Within limit and Exceeds limit appear only where a real reference value exists, and even then it is screening, not
> legal compliance.

## Scene 6 (about 55 s): the standards

> Here is the standards work. On any site, one click downloads its measurements as a fire bundle. Each value is an
> Observation, with its unit, its period and its data origin. A Provenance names the software and the source. And we never
> invent a code: where a standard code is not available, the parameter is plain text. The sandbox is read as fire R four,
> and the official H L seven validator, run against the implementation guide, found zero errors on four hundred and eighty
> five real sandbox resources. This download is structurally valid fire, and matching the full profiles is the next step.

## Scene 7 (about 30 s)

> Under the hood: a Fast A P I backend on Cloud Run and a Next J S web app, with the key kept on the server. Rate limits
> and spend caps protect the budget, a hash chained audit log records every request without storing questions, and more
> than three thousand automated tests run on every change. The repository is public and documented, so anyone can run the
> backend, rebuild the data and deploy it.

## Scene 8 (about 55 s): what can be done next, and how

> What can be done next, and how. More countries, with their own limits: the data stores are built by scripts from public
> E E A data, and the reference values live in a file that reloads without changing code, each value carrying its source.
> More parameters: a parameter is one entry in a mapping table, then a rebuild. More languages: one dictionary file,
> checked automatically. Fresh data: the same scripts can run on a schedule. More users: the rate limits and the audit log
> move to a shared store, so the service can run on several instances. More standards: a fire capability statement and
> search, and standard codes once the implementation guide confirms them. And with people: translations reviewed by local
> agencies, and a pilot with local water officers.

## Scene 9 (about 15 s)

> For One Health, this closes the gap between public monitoring data and the people who need to act on it. Aqua Ledger: ask
> the water, get the data, not a verdict.

## Notes for the voice

- One block per scene; leave about half a second of silence between scenes (the assembly adds it).
- If the engine stumbles on a word, respell it phonetically here and keep the subtitle spelling in the script.
- Every claim above is true of the product on the day of the recording, or is said as "next" (scene 8 and the last
  sentence of scene 6): nothing in scene 8 exists yet, and the video says so by its wording. If a scene changes, change its
  text before generating the audio.
- Scenes whose text changed since the first version, to regenerate: 1, 4, 6, 8, 9. Scenes 2, 3, 5 and 7 keep their audio.
