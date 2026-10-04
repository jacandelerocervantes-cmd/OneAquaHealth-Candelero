# Language support (answers in 26 languages)

Status: 2026-10-02, backend language package, phase 1 (modules, tests, this document). Demo version. Everything here is
English; the translated strings are data (`src/oah/i18n/strings/`, `src/oah/i18n/denylist/`). No new formula, FHIR code,
threshold or source was added.

## 1. Design: English pivot with language-neutral verification

The output guard (`oah.explain.safety.guard_output`: claim, potability and leak patterns) and the grounding number check
(`oah.explain.grounding`) are written for English. Writing a reliable pack of regular expressions for 26 languages is not
feasible, so the answer is never *generated and checked* in the target language. Instead:

```
question -> agent / explainer (English, all existing guards and grounding, unchanged)
         -> English answer validated (answered) ........ if unsafe: withheld in every language, never translated
         -> language == en ? done
         -> second, constrained model call: translate the validated English text
         -> language-neutral checks (section 3)
              pass: translated text (+ answer_en = the English original, always)
              fail: the English answer, translation_status rejected | failed
```

* The grounding and unsafe flags always describe the English answer. An English answer that is unsafe OR not grounded (a number or unit that does
  not trace to the data) is withheld in every language: no text, no translation call (security hardening F6; reasons `english-answer-unsafe` and
  `english-answer-ungrounded`, notices `withheld_notice` and `withheld_ungrounded_notice`).
* The response says how far a translation is verified (`translation_checks`, section 4a).
* The translation call receives **only** the validated English answer (no question, history, tool result or other user
  text), delimited, with a system prompt that fixes what must not change.
* The English source is always returned next to the translation (`answer_en`), so the UI can show "original" and a
  reviewer can audit.
* Fixed texts (disclaimer, notices, status labels) are not model output: they come from static files
  (section 6), machine-drafted and not yet human-reviewed, and are the same on every call.

## 2. Threat model

| Threat | Control | Residual |
|---|---|---|
| The translator changes, adds or drops a number | multiset of numeric tokens must equal the source; separators are part of the token | a number moved to another claim (same multiset); number words ("three") are treated as a dropped number and rejected |
| Localised numerals (decimal comma, regrouped thousands, Arabic-Indic or fullwidth digits, superscripts) | the token includes its own `.` and `,`; non-ASCII numeral characters must occur exactly as often as in the source | none known for ASCII-vs-other digit systems |
| Prompt injection carried by the English text (an echoed question, a site name) | the call has no tools, no other input, a system prompt that says the text is material only, the delimiter inside the text is neutralised; output must pass the checks | the model may still follow it; the checks catch added numbers, links, HTML, copied instructions and a length change, not every rewording |
| A claim the English text did not make (potable, safe, contaminated) | the prompt forbids it; best-effort denylist for tier-1 languages (section 4); the English text was already guarded | other languages have only the prompt; wording that avoids the listed words is not caught |
| Instruction leak | six-word runs of the translation call's prompt (and, for chat, the chat prompt parts) must not appear in the output unless the source contains them | non-English leaks are not matched by words; the length and number checks are the backstop |
| Links, HTML, markdown, code fences | the neutral flags of `guard_output` are applied to the translation | none known |
| Invisible text (zero-width, bidi controls, soft hyphen, tag characters) | any character of category Cc, Cf, Cs, Co or Cn except `\n` and `\t` rejects the translation | none known |
| Cost | one extra reservation unit per translation; `max_tokens` 2048, timeout 30 s (hard ceiling 60 s); source at most 3000 characters; cached by language | counters are in-process, like the other guards |
| Provider failure | the English answer is returned with `translation_status: failed` | none: never a 5xx for a translation problem |
| Audit | `translation-dispatch` before the call, then `translation-result`, `translation-rejected` or `translation-error`: language, model, digests, counts, reasons, never the text; no record, no call | the chain cannot detect removal of the newest records |

## 3. The language-neutral checks (`src/oah/i18n/translate_check.py`)

| Check | Rule | Reason code |
|---|---|---|
| Empty | the translation is blank | `empty` |
| Invisible characters | none of category Cc, Cf, Cs, Co, Cn (ordinary whitespace, newline and tab allowed) | `invisible-characters` |
| Numbers | the multiset of tokens `[0-9]+([.,][0-9]+)*` is identical to the source. A decimal comma, a regrouped thousands separator, an extra, a changed or a dropped number all change it | `numeral-format-changed`, `number-added`, `number-missing` |
| Other numeral systems | the multiset of non-ASCII numeral characters (Nd, Nl, No: Arabic-Indic digits, fullwidth digits, roman-numeral characters, fractions, superscripts) equals the source's | `non-ascii-numeral` |
| Forbidden constructs | no URL, markup or markdown link or code fence (the neutral flags of `guard_output`). Since F7 the markup rule is ANY `<` followed by a letter, `/`, `!` or `?` (so `<details>`, `<button>`, `<video>`, `<math>`, `<template>` and `<url>` autolinks are caught, not only an allow-list of tags) and the link rule covers `[t](u)`, `![a](u)`, `[t][ref]`, `![a]` and `[ref]: u`; `<` before a digit or a space ("below <5 mg/L", "x < y") is fine. The same guard runs on the English answer and on every translation, and the fixed strings validator forbids the same constructs | `contains-url`, `contains-html`, `contains-markdown-link`, `contains-code-block` |
| Instruction leak | no six-word run of the prompts given (the call's own prompt, plus the chat prompt parts when called from chat) that the source does not itself contain | `leaks-instructions` |
| Length | translation length / source length (characters) between **0.4 and 3.0**, and at most 6000 characters. The bounds are a working choice: they must admit the languages whose text is longer than English (for example Finnish, German, Greek) and still catch a reply that is a fragment or an explanation; they are not measured on real output yet | `too-short`, `too-long` |
| Truncation | the provider stopped at the token limit | `truncated` |
| Denylist (optional, tier-1 only) | no pattern of `denylist/<family>.json` matches the NFKC text | `denylist-term` |

A translation identical to the source is accepted (a text made only of codes and numbers does not change).
The English claim patterns (`unsupported-health-claim`) and the `assess` format flag are deliberately **not** applied to a
translation: they belong to the English text, which was guarded before translation.

Numerals stay international **on purpose**: decimal point, ASCII digits, no thousands regrouping. A number must read the same
in the answer, the data and the English original; localising separators is the commonest way a unit or a limit gets
misread (3,5 versus 3.5 versus 3.500). Parameter names, units, site names, water-body names, codes and the names of
sources, directives and legal acts are not translated either (the prompt requires it; the number check protects the digits
inside them).

## 4. Best-effort denylist (tier 1: es, it, el, fr, de, pt, nb)

`src/oah/i18n/denylist/<family>.json`, one file per language family; the Spanish variants share `es.json`. Each holds regular
expressions for obvious potability and safety claim words that the English source did not have: "potable", "drinkable",
"safe for drinking or swimming", "contaminated", "toxic", "harmful", "health risk" and their usual inflections. Matching is
case-insensitive with word boundaries on the NFKC text.

* Marked `"best_effort": true`; **never the only protection** (the English guard, the prompt and the neutral checks come first).
* Noun forms such as the Spanish or Italian word for "potability" are not listed: the English guard allows "potability",
  and a faithful translation of "this is not a potability determination" must not be rejected. The German "Trinkwasser"
  and the Greek plain adjective for drinking are also not listed, because drinking-water reference limits are named in the
  data.
* Not reviewed by a native speaker. Inflection (Greek, Norwegian) makes any list incomplete; unlisted synonyms are a known gap.

### 4a. Verification level of a translation (`translation_checks`, F8)

Only seven language families have a denylist (es for both Spanish variants, it, el, fr, de, pt, nb); the other 19 languages get the neutral
checks of section 3 (numbers, forbidden constructs, instruction leak, length, invisible characters) and nothing else. Every chat and explanation response and
every entry of `GET /languages` therefore carries `translation_checks`: `neutral-and-denylist` for those seven families, `neutral-only` for the
other 19, null for English (`oah.i18n.localize.translation_checks_level`, derived from `oah.i18n.denylist.DENYLIST_FAMILIES`, so it follows the data files).
Client rule: label every translated text "machine translation" and always offer `answer_en`; for `neutral-only` label it, in addition, as unverified
(no word list was applied). `neutral-and-denylist` is the stronger level, still best-effort and not a proof that the meaning is preserved (section 10).

## 5. Languages and statuses

Registry: `src/oah/i18n/languages.py`. Status of every language except English is `translated-by-model`; English is `source`.
Tier 1 languages have a denylist and are first in line for a native-speaker review; tier 2 rely on the neutral checks.

| Code | Language | Endonym | Script | Tier |
|---|---|---|---|---|
| bg | Bulgarian | Български | Cyrillic | 2 |
| hr | Croatian | Hrvatski | Latin | 2 |
| cs | Czech | Čeština | Latin | 2 |
| da | Danish | Dansk | Latin | 2 |
| nl | Dutch | Nederlands | Latin | 2 |
| en | English (source) | English | Latin | 1 |
| et | Estonian | Eesti | Latin | 2 |
| fi | Finnish | Suomi | Latin | 2 |
| fr | French | Français | Latin | 1 |
| de | German | Deutsch | Latin | 1 |
| el | Greek | Ελληνικά | Greek | 1 |
| hu | Hungarian | Magyar | Latin | 2 |
| ga | Irish | Gaeilge | Latin | 2 |
| it | Italian | Italiano | Latin | 1 |
| lv | Latvian | Latviešu | Latin | 2 |
| lt | Lithuanian | Lietuvių | Latin | 2 |
| mt | Maltese | Malti | Latin | 2 |
| nb | Norwegian Bokmål (Norway is covered by the data; it is EEA, not EU) | Norsk bokmål | Latin | 1 |
| pl | Polish | Polski | Latin | 2 |
| pt | Portuguese | Português | Latin | 1 |
| ro | Romanian | Română | Latin | 2 |
| sk | Slovak | Slovenčina | Latin | 2 |
| sl | Slovenian | Slovenščina | Latin | 2 |
| es-MX | Spanish (Mexico) | Español (México) | Latin | 1 |
| es-ES | Spanish (Spain) | Español (España) | Latin | 1 |
| sv | Swedish | Svenska | Latin | 2 |

All are left to right.

**Input normalisation.** A `language` value is trimmed, matched case-insensitively and accepts `_` for `-`. Documented aliases:
`es` means `es-MX`; `no` and `nb-NO` mean `nb`; `en-GB`, `en-US`, `pt-PT`, `el-GR`, `fr-FR`, `de-DE`, `it-IT` mean their base
language. Anything else (`pt-BR`, `nn`, `Greek`, `zz`, too long, wrong shape, not a string) is rejected with the supported list.
`EL` is the EU institutions' *country* code for Greece (the EEA Waterbase file uses it; this project's country parameter uses
`GR`). As a **language** value `EL` and `el` both mean Greek; the two never meet because a country selector is never parsed
by this registry, and the country code `GR` is not accepted as a language.

**Mexican Spanish.** The maintainer is Mexican, so `es-MX` is the Spanish default (bare `es` resolves to it) and its translation
prompt asks for Mexican vocabulary and the form "usted". `es-ES` is selectable too and asks for peninsular Spanish. Both
use international numerals (decimal point) and share the Spanish denylist. Their fixed strings are separate files; the
`es-MX` file was written with extra care, and is still a **machine draft**.

## 6. Fixed strings (`src/oah/i18n/strings.py`, `src/oah/i18n/strings/<code>.json`)

English is the source of truth in code (`ENGLISH`): disclaimer, interpretation notice (same text as
`regimes.INTERPRETATION_NOTICE`), budget-exceeded and no-answer texts (same as `oah.chat.prompts`), "not available in this
data", machine-translation notice, translation-fallback notice (`{language}` placeholder), withheld and ungrounded notices,
bathing-water classification notice, measurement-only notice, the bathing-water season comparison notice, the approximation notice of
the period comparison, and the status labels. A test keeps the English text equal to the text the API uses today.

The other 25 files are model-drafted and marked `"review_status": "machine-draft"` at file level; **no file claims human
review**, and the loader refuses any other value. Loading is strict: every key present and no extra key, no empty value, the same
`{placeholders}` and the same numbers as English, no HTML, URL, markdown link, code fence, angle bracket or control character.
Each file carries `source_sha256`, the digest of the English text it was translated from; if an English string changes, every
file becomes stale and loading fails until it is re-translated. An unknown language falls back to English with `fallback=True`.
The "approximation notice" is FINAL since package 5 (period comparison, `docs/period_change.md`): "Screening aid, not a compliance
assessment: each period is summarised by its mean, which is compared with the limit. National aggregation rules such as LIMeco or
HWQI are not reproduced." Package 5 also added `bathing_change_notice` (the season comparison counts classes only by the README
order, the classes not classified and good or sufficient are not comparable, no concentration or threshold). Both are machine drafts in all
25 files, validated with the same digest and placeholder checks; the period and season routes return them in the requested `language`.
Package 6 (bathing-water samples, `docs/bathing_samples_store.md`) added four keys, again in English in code and as machine drafts in all 25 files with a new digest: `bathing_samples_notice` (individual E. coli and enterococci results in colony-forming units per 100 ml, not a classification and not a compliance assessment), `bathing_no_threshold_notice` (no threshold or limit is applied; none exists in the project; ask the competent authority), `bathing_flagged_values_note` (values flagged below the limit of detection, missing or of unrecognised status are counted apart and are not in the minimum, maximum, mean or median; confirmed high values are included and counted) and `bathing_samples_change_notice` (mean and median compared, no significance tested, no limit crossing, countries compared over bathing waters with enough samples in both periods). None of them uses a word that calls a value safe or unsafe. The only number in them is the 100 of "per 100 ml", kept in every translation.

Package 7 (external context, `docs/external_context.md`) added seven keys, in English in code and as machine drafts in all 25 files with a new digest:
`external_context_notice` (external context, not a measurement of this site, orientation only), `external_reanalysis_notice` (weather is modelled reanalysis for a
coarse grid cell; the most recent days may be missing), `external_discharge_notice` (modelled for the nearest river cell, not a gauge, may not be this site's river),
`external_occurrence_notice` (opportunistic observations published to GBIF, not monitoring; no record is not absence), `external_licence_notice` (each record keeps its own
licence, some non-commercial only), `external_no_causation_notice` (context only, nothing shows causation) and `external_unavailable_notice` (the provider could not be used;
nothing was estimated). None contains a number or a word that calls anything safe or unsafe, and each is under 200 characters in English so the chat sanitiser never cuts it.
The required attribution link text "Weather data by Open-Meteo.com" is not a fixed string: it is data and is never translated.

Security hardening F6 added two keys, in English in code and as machine drafts in all 25 files with a new digest: `withheld_ungrounded_notice` (the answer was
withheld because some of its numbers or units could not be traced to the data; the data that were consulted are still shown) and `status_withheld_ungrounded`
(the status label "Withheld, not grounded"). Neither contains a digit. `ungrounded_notice` stays in the files; the routes no longer produce it because a not grounded
answer is withheld, not returned with a note.

The chat evidence summary (`docs/chat_agent.md` section 10) added one key, `evidence_notice`, in English in code and as a machine draft in all 25 files with a new digest:
"Data the assistant consulted, copied from the data tools. A short list shows every value. A longer one shows how many values there are, the lowest and highest value seen, and the first and
last period. An observed range is not a confidence interval." It contains no digit. `oah.i18n.localize.notices_for(with_evidence=True)` adds it to `notices` only when the chat response
carries an evidence summary (a `withheld-ungrounded` or `withheld` answer). A withheld answer is still never translated: only this fixed notice is localised, and the evidence items carry
numbers, ids, parameter names and periods exactly as the tool results gave them.

## 7. The translation call (`src/oah/i18n/translator.py`)

`translate(source_en, language, client=, model=, reserve_model_call=, timeout_seconds=, extra_leak_parts=)` returns a
`TranslationResult` with `status` (`not-needed` for English, `ok`, `rejected` when a check failed, `failed` for a provider
error, a timeout, an exhausted budget or an input that cannot be translated), the `text` (translation, or the English source
when not `ok`), `source_en`, the `reasons`, tokens and `model_calls`. A rejected or failed result carries the flag
`translation-rejected` or `translation-failed`. It raises only for an unknown language code and for an unwritable audit log
(nothing is sent without a record). `max_tokens` is 2048, the timeout 30 s by default (ceiling 60 s). No temperature or other
sampling parameter is set; the model is the caller's (phase 2: `OAH_TRANSLATION_MODEL`, default the same as `OAH_LLM_MODEL`).

## 8. How to add a language

1. Add one `_lang(...)` line to `_LANGUAGES` in `src/oah/i18n/languages.py` (code, English name, endonym, script, tier, optional
   style note); add any alias to `ALIASES`.
2. Write `src/oah/i18n/strings/<code>.json` with every key of `ENGLISH`, the same placeholders and numbers, `"review_status":
   "machine-draft"` and the current `source_sha256` (printed by `english_digest()`).
3. Optionally, for a tier-1 language, add `denylist/<family>.json` and the family to `DENYLIST_FAMILIES`.
4. Run the tests: the registry, strings and translator tests iterate over the registry, so the new language is checked
   automatically. Update the table in section 5.

## 9. How a reviewer audits a translated answer

* The response always has `answer_en`, the validated English answer; compare it with the translation.
* `translation_status` says whether the text is the model's translation (`ok`) or the English fallback.
* The hash-chained audit log (`llm_calls.jsonl`) has the dispatch and the result or rejection with SHA-256 digests of the
  source and the output, the language, the model and the reason codes; the text itself is never stored, so a reviewer who
  holds `answer_en` can recompute the digest of the source.
* Every translated file and the translations are machine-made. Until a native speaker reviews a language, the UI must label
  its text as machine-translated (the string `machine_translation_notice` exists for that).

## 10. Limits

* Translation is machine-made, flagged, and not reviewed by a human in any language.
* Number words are rejected, not accepted: a faithful translation that spells a digit out ("tres") falls back to English.
  This is conservative on purpose and may reject some correct translations.
* The checks are neutral properties; they do not prove that the meaning is preserved. A statement can be softened or inverted
  with the numbers intact (for example "not available" rendered as "available"). The English original next to it is the control.
* Length bounds and the six-word leak size are working values, not measured on live output.
* Phase 2 (wiring into `/chat`, `/explain/*`, `GET /languages`, configuration, cost accounting and the cache key) is described in
  the ledger; until it is done no route accepts a `language`.
