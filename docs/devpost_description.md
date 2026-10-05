# Devpost description (About the project, Built with)

Status: 2026-10-04. The text below is for the "About the project" box of the Devpost submission (Markdown with LaTeX), and
the list of tags for "Built with" (at most 25). Every claim is one the repository and the live site support; if a figure
changes before the submission, change it here and in the Devpost box.

## About the project

```markdown
## Inspiration

Water data is public, but it is scattered: different agencies, formats and languages. A citizen, a journalist or a local officer
cannot simply **ask** it a question. And when an AI answers instead, nobody can tell whether the numbers are real.

We wanted the opposite of a confident chatbot: an assistant that **shows its evidence, checks its own numbers and knows
when to stop**. That is the One Health spirit applied to data: decisions about water, people and ecosystems should rest on
traceable facts, with the human judgment left to the humans who are responsible for it.

**Track 7: Digital Health Standards.** AquaLedger puts standards on the way in (the public HL7 Europe OneAquaHealth sandbox is
read as FHIR R4) and on the way out (the measurements of any site download as a FHIR R4 Bundle), with an AI agent on top.

## What it does

Ask a plain question about the rivers, lakes and bathing waters of **Greece, Italy and Norway**, in **26 languages**, and
get an answer written only from real European data:

- **EEA Waterbase** (river and lake measurements), the **EEA Bathing Water Directive** classifications and individual
  *E. coli* and enterococci samples, and the **HL7 Europe sandbox**. Modelled context (weather, river discharge, species
  records) is shown, always labelled as modelled.
- Every answer carries its **sources, licence, method and the reference values used**, labelled as screening aids, never as
  legal limits.
- **No health verdicts.** Ask "is it safe to swim?" and it declines and points to the competent authority.
- Search a site as you type, see places on a map, read the data under the conversation, and **download it as FHIR**.

## How we built it

- **Backend:** FastAPI on Google Cloud Run. Three prebuilt SQLite stores (Waterbase aggregates, bathing-water classifications,
  754,451 bathing-water samples), a read-only **tool-use agent** (Claude, Anthropic API) that chooses which data tool to call,
  a hash-chained audit log that stores digests only, rate limits and spend caps.
- **The rule that makes it trustworthy:** before an answer is shown, every number the model wrote is matched against the data it
  retrieved. A number written with $d$ decimals is accepted only if
  $$|x_{\text{text}} - x_{\text{data}}| \le 0.5 \times 10^{-d}$$
  for some value of the tool results; otherwise the answer is **withheld** and the evidence is shown instead. The model is not
  allowed to compute: a change between two periods comes from a tool. The store keeps the sum and the count of every month,
  so any coarser mean is exact: $\bar{x} = \sum_i s_i \,/\, \sum_i n_i$.
- **Standards:** the sandbox is read as FHIR R4 against the OneAquaHealth implementation guide (the official HL7 validator
  found 0 errors on 485 real sandbox resources). A site's measurements are exported as a FHIR Bundle (Location, Observation,
  Provenance). We never invent a code: a parameter without a standard code is plain text.
- **Web:** Next.js, with the access key kept on the server, a CSP, and an allow-list proxy. The whole interface, not only the
  answers, follows the selected language.
- **Quality:** more than 3,300 automated tests (98 % coverage), continuous integration, a typed OpenAPI contract and a
  documented, reproducible setup. The repository is public and the backend can be run by anyone.

## Challenges

- **Models like to compute.** Asked how phosphorus changed between two periods, the model subtracted two means itself and wrote a
  number that was in no tool result. Our own check withheld a correct-looking answer. The fix was not to loosen the check:
  the agent now gets **one** revision with a precise note (use the figures the tool returned; say data is missing only if it
  really is), and the revised text passes the same checks.
- **Guardrails have false positives.** Live testing showed a Markdown label (`**Sandbox data:**`) read as a web address, and a
  word like "two" counted as an invented number. We fixed both, with tests, and measured the result on the live site.
- **Real data is dirty.** The Italian pH data held values that cannot exist; the build now drops anything outside the pH scale
  (805 values) and counts it.
- **Honesty under time pressure.** We label what is real, modelled and synthetic, and what we could not verify.

## What we learned

A useful AI assistant for public data is mostly **plumbing for trust**: provenance, deterministic checks, refusal rules and
tests for the refusals. The model writes the sentence; the system decides whether it may be shown.

## Honest limits

The 25 non-English translations of the interface are machine drafts and have not been reviewed by native speakers. The FHIR
download is structurally valid FHIR R4 but does not claim conformance to the OneAquaHealth profiles. Citizen-science data exists
only as a clearly labelled synthetic lab. Rate limits live in memory, so the service runs as one instance. Answers vary between
runs.

## What's next

Human review of the translations, citizen-science observations as a real input (FHIR in), more countries (one data store each),
and profile-conformant FHIR export of every answer's evidence.

**Try it:** https://one-aqua-health-candelero.vercel.app/ — **Code:** https://github.com/jacandelerocervantes-cmd/OneAquaHealth-Candelero
```

## Built with (25 tags)

python, fastapi, pydantic, typescript, next.js, react, tailwindcss, leaflet, openstreetmap, fhir, hl7, claude, anthropic-api,
google-cloud-run, google-cloud-build, google-secret-manager, docker, vercel, sqlite, github-actions, pytest, vitest,
elevenlabs, open-meteo, eea-data
