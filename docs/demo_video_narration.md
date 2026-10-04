# Demo video narration (text for the voice)

Status: 2026-10-04. The text below is what is read aloud, scene by scene, in English (about 600 words, 4 minutes 30 seconds
at a calm pace). It follows `docs/demo_video_script.md` (the table of shots and the production steps). It is meant for a
text-to-speech voice (the maintainer's own voice, replicated with ElevenLabs): paste each scene as ONE block, in order.

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

## Scene 1 (about 30 s)

> Water data is fragmented. Different agencies, different formats, different languages, and a citizen or a local officer
> cannot simply ask it a question. This is our entry for Track 7, digital health standards. Aqua Ledger connects
> standards-based data, fire on the way in and on the way out, with an AI agent that can explain it but never replaces
> human judgment.

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

## Scene 4 (about 30 s)

> The map shows the places of the country, or only those of the index you are in. The data sits under the conversation,
> and one click downloads it. Change the language here, next to the country, and the whole interface follows, in twenty
> six languages, checked automatically so that a translation never adds a link or markup, and labelled as machine
> drafted.

## Scene 5 (about 60 s): the standards

> Here is the standards work. On any site, one click downloads its measurements as a fire bundle. Each value is an
> Observation, with its unit, its period and its data origin. A Provenance names the software and the source. And we never
> invent a code: where a standard code is not available, the parameter is plain text. Behind it, the sandbox is read as
> fire R four, and the official H L seven validator, run against the implementation guide, found zero errors on four
> hundred and eighty five real sandbox resources. Standards are not decoration here. They are the contract between the data
> and the agent.

## Scene 6 (about 30 s)

> Under the hood: a Fast A P I backend on Cloud Run and a Next J S web app, with the key kept on the server. Rate limits
> and spend caps protect the budget, a hash chained audit log records every request without storing questions, and more
> than three thousand automated tests run on every change. The repository is public and documented, so anyone can run the
> backend, rebuild the data and deploy it.

## Scene 7 (about 30 s)

> For One Health, this closes the gap between public monitoring data and the people who need to act on it. Adding a country
> means one more data store, not a rewrite, and the standards keep it interoperable. Aqua Ledger: ask the water, get the
> data, not a verdict.

## Notes for the voice

- One block per scene; leave about half a second of silence between scenes (the assembly adds it).
- If the engine stumbles on a word, respell it phonetically here and keep the subtitle spelling in the script.
- Every claim above is true of the product on the day of the recording; if a scene changes, change its text before
  generating the audio.
