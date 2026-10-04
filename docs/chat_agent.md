# Chat agent (`POST /chat`)

Status: 2026-10-04 (evidence summary and approximate figures added, sections 10 and 11; first written 2026-10-02, backend package 2). Demo version: reference values, not legal compliance. Decision (maintainer): the agent
may chain several tool calls per question. Route reference: `docs/api_routes.md`. Everything here is English and uses only
what the code already computes; no new formula, FHIR code or source was added.

## 1. Design

The chat UI sends a free-text question with the selected country and (optionally) the selected index. A bounded
Anthropic Messages API tool-use loop (`src/oah/chat/agent.py`) lets the model call read-only tools, then writes an answer
that is checked against the tool results before it is returned.

```
request -> validate (422) -> cache? -> client? (503) -> reserve 1 conversation (429) -> loop:
   model call (reserve 1 model call) -> tool calls (validated, bounded, sanitised) -> ... -> final text
   -> grounding + output guard -> answered | withheld | withheld-ungrounded        (budget reached -> budget-exceeded)
```

* The model is `OAH_LLM_MODEL` (default `claude-sonnet-5-5`), the client is the one `build_client` makes
  (`get_llm_client` seam), so the key, timeout and retry settings of the explanation layer apply.
* The model only interprets the question and calls tools. The system prompt (`src/oah/chat/prompts.py`) requires every
  number to come from a tool result with its unit and, for a limit, the `limit_basis`; forbids estimating or computing;
  requires saying so when data are missing or outside the requested window; keeps one country per answer; gives a plain
  "not available in this data" for protozoa, bacteria other than E. coli and intestinal enterococci, bathing-water samples outside the countries and dates
  the tools return, biotic or biodiversity indices, air quality and population health; and is in English. It reuses the existing scope clause (no health, potability or regulatory determination) and
  untrusted-data clause (`oah.explain.prompts`) and adds a chat clause for the question, history and tool results.
* Prior turns are given inside the single first user message as delimited, untrusted data, never as real assistant turns,
  so a forged `assistant` entry cannot speak with the model's authority. Their numbers are not evidence.

## 2. Tools

All are wrappers over the functions the REST routes call (official sandbox records only, `docs/official_record_filter.md`, and
the EEA Waterbase store, `docs/waterbase_store.md`); there is no HTTP self-call. The model can use no other tool: no write, no FHIR export, no synthetic route.

| Tool | Wraps | Notes |
|---|---|---|
| `list_countries` | `countries_overview` | `GET /countries` fields, with `latest_year`, `measurement_only_sites` and the per-source `sources` |
| `list_sites(country?, query?)` | `list_sites_with_status` and the Waterbase store | defaults to the selected country; `query` is part of a name, water body name or id (at most 64 printable characters, parameterised SQL, `%` and `_` literal); sandbox sites first, then at most 60 Waterbase sites, each with its `source`; cut again to the size bound |
| `get_site_index(location_id)` | the `GET /indices/{id}` payload | whitelisted keys; `limit_overrides` (a file path) is left out; a Waterbase site is refused with an explanation (no index) |
| `get_site_measurements(location_id, parameter?, date_from?, date_to?, limit?)` | `site_measurement_records`, or the Waterbase annual records for a Waterbase site | each number is `{amount, unit}`, the limit comes with its `limit_basis`; a Waterbase result adds `year`, `n`, `n_below_loq`, `matrix`, `attribution` and `data_freshness` `snapshot` |
| `get_qc_summary` | `build_report` | counts of findings and of excluded records; not country specific |
| `list_bathing_waters(country?, query?, quality?, type?, limit?)` | `oah.bathing.service.list_page` | EEA bathing waters with the CLASSIFICATION of their latest season (origin `real-eea-bathing-water`); `limit` 1 to 50 (default 20); the selected country is enforced; filters are printable text of at most 64 characters, parameterised SQL; no profile URL is passed on; an empty result names the countries that do have bathing-water data |
| `compare_periods(scope, id_or_country, parameter, a_from, a_to, b_from, b_to)` | `oah.api.change.site_change` / `country_change` (the REST routes' own functions) over `oah.indices.period_change` | `scope` is `site` or `country`; months are `YYYY-MM`, both ends included; the parameter is a closed name or a Waterbase label (case-insensitive, canonical name passed on); a bad call is an error result; the selected country is enforced like for sites (a site of another country, or `scope` country for another country, is refused); the result is compacted (every number is `{amount, unit}`, percents are `{amount, unit: "%"}`, the limit comes with its `limit_basis`, the flags and `data_range` are kept, the two fixed English notices and a definition line are added) and bounded like every result |
| `compare_bathing_seasons(country, season_a, season_b)` | `oah.api.change.bathing_change` over `oah.bathing.change` | counts of classification transitions between two seasons in the README order only; `country` is required and enforced; seasons are integers 1900 to 2100; no concentration or threshold; a short English comparison notice (`COMPARISON_NOTICE_SHORT`, under the sanitiser's 200-character cut) and the usual classification notice are added |
| `get_bathing_water_history(bathing_water_id)` | `oah.bathing.service.find` | one bathing water season by season (quality class, monitoring calendar, management); refused when the bathing water is in another country than the selected one |
| `get_bathing_samples(bathing_water_id, date_from?, date_to?, season?, limit?)` | `oah.api.samples.bathing_samples` over `oah.bathing_samples.store` (package 6) | the INDIVIDUAL E. coli and intestinal enterococci results (cfu/100ml, origin `real-eea-bathing-samples`) of one bathing water of Greece or Italy, newest first; `limit` 1 to 100 (default 20), `season` 1900 to 2100, ISO dates with `date_from` not after `date_to`; the `summary` covers all matches (counts by kind, min, max, mean, median as `{amount, unit}`); a quantified value is `{kind, value: {amount, unit}}`, a detection-limit, missing, unknown-status or invalid value is only `{kind}` (the reported limit of detection is NOT passed to the model); the selected country is enforced; short English notices (no threshold, flagged values counted apart) are added; cut to the size bound like every result |
| `compare_bathing_concentrations(scope, id_or_country, a_from, a_to, b_from, b_to)` | `oah.api.samples.bathing_samples_change` / `bathing_samples_country_change` over `oah.indices.period_change` | `scope` is `bathing_water` or `country` (two letters, `EL` read as `GR`); months `YYYY-MM`, both ends included; per indicator and period `n_samples`, mean, median, min, max, the flagged-value counts, the change of the mean and of the median (increase means B minus A as computed by the tool), `data_range`, flags; a country uses only the bathing waters with enough samples in BOTH periods; no limit, no limit crossing, no significance claim; the selected country is enforced for both scopes; bad calls are error results |
| `get_weather_context(site_id, date_from, date_to)` | `oah.external.service.ExternalContext.weather` (the `GET /sites/{site_id}/weather` function) through `oah.chat.external_tools` | EXTERNAL context (backend package 7): monthly precipitation sum and mean temperature from the ERA5 reanalysis (MODELLED, Open-Meteo); a site or a bathing-water id; both dates required, at most 1096 days; every number is `{amount, unit, n_days, coverage_percent}`; origin `external-open-meteo`, `data_kind`, attribution, licence, flags (`era5-delay`, `period-outside-data`, `partial-month`), `status` and the fixed English notices are in the result |
| `get_river_discharge_context(site_id, date_from, date_to)` | `ExternalContext.discharge` | monthly mean river discharge (`m3/s`) of the nearest GloFAS river cell (MODELLED, not a gauge; `grid_distance`, `data_range`, flags `nearest-cell-may-not-be-the-river`, `site-not-a-river`, `period-outside-data`, `beyond-documented-history`); water-quality sites only (a bathing water is refused) |
| `get_species_nearby(site_id, group?, date_from?, date_to?)` | `ExternalContext.species` (fixed `limit` 10) | GBIF occurrence records of the discovered macroinvertebrate groups in a 10 km square (OPPORTUNISTIC): `records_per_group` (GBIF's counts for the whole search), at most 10 records with licence, distance and dataset name, `datasets` with the citation text, `truncated`; no coordinates of a record beyond the distance, no observer name, no record id; water-quality sites only |

Selected index narrows the tools: `water-quality` gets countries, sites, index, measurements and `compare_periods`; `water-parameters` gets
countries, sites, measurements and `compare_periods`; `data-quality` gets sites and the QC summary; `microbiology` (package 4) gets countries, the two
bathing-water tools, `compare_bathing_seasons` (package 5) and the two samples tools `get_bathing_samples` and `compare_bathing_concentrations` (package 6); with no index selected the model gets all fourteen (eleven plus the three external-context tools). The route does not list the catalogue items that are not real today
(biodiversity, air quality, population health).

Every result carries `origin` (`real-sandbox`, `real-eea-waterbase`, or `real-mixed` for a list that holds both) and the
response `origin` is the one real source its tool results came from, or `real-mixed`; each citation has a `source`. The two
sources are never merged into one figure. The system prompt (`CHAT_DATA_FACTS` in `src/oah/chat/prompts.py`) states the data
facts: the two source labels, that Waterbase data are annual aggregates (mean, min, max, `n`; no median) for river and lake sites of
GR, IT and NO from 2010, to give the year and use `latest_year` of `list_countries`, that lakes have no limit regime, that
groundwater and coastal waters are not in the data, and that a `no-location` site has no coordinates. Package 4 adds to the facts:
the Waterbase groups `solids-turbidity` and `organic-matter` are MEASUREMENT ONLY (no limit regime: report values without a limit
comparison and say so), colloids as such are not measured (turbidity and suspended solids are proxies for particulate or colloidal
matter), and the third source `real-eea-bathing-water`: the per-season CLASSIFICATION (written as in the file, for example
`1 - Excellent`) for Greece and Italy (Norway has no bathing water in that file), never a concentration or a statement of legal
compliance, never to be turned into a number or a threshold; protozoa are NOT available and must be declined plainly. Since package 6 the
system prompt ALSO states that the concentrations of E. coli and intestinal enterococci ARE available for the bathing waters of Greece and Italy
(source `real-eea-bathing-samples`, individual samples in cfu/100ml, Greece from 2008 and Italy from 2010 up to the latest season in the store; Norway
has none) through `get_bathing_samples` and `compare_bathing_concentrations`, that they are MEASUREMENTS with NO threshold (no limit and no classification
rule exists in the project: never call a value good, bad, high, low, over or under a limit, never state a guideline value from memory), that only values of kind
quantified or confirmed-high are concentrations and the rest are reported as counts, that n, the unit and the dates are always given, and that a question
whether bathing is advisable or a value acceptable gets no verdict and a referral to the competent authority or an accredited laboratory. The role text no longer
declines "concentrations of E. coli or intestinal enterococci" (it declines bacteria other than those two, protozoa, and samples outside the countries and dates the tools return).
The decline wording moved into its own clause, `CHAT_DECLINE_CLAUSE`, which the instruction-leak check does not compare against: a correct refusal repeats those very words
and the earlier arrangement would have withheld it as a "leak".

Period questions (package 5, `docs/period_change.md`). The model never computes a change: `compare_periods` returns the deterministic comparison (n_samples,
mean, min, max, below-LOQ, the limit with its basis where one exists, the change, `crossed_limit`, `data_range`, flags) and the system prompt (`PERIOD QUESTIONS`
in `CHAT_DATA_FACTS`) requires: use the tool, never shift or replace a requested period, say plainly when a period lies beyond the data (flag
`period-outside-data`), give `data_range` and offer the latest available period as a suggestion for the user to confirm, always state `n_samples` and the flags
that apply (`partial-period`, `below-loq-excluded-bias-upward`, `annual-only`, `few-sites`), read "increase" as mean_B minus mean_A as computed by the tool, quote the
tool's numbers only (a null percent stays unreported), give the limit and its `limit_basis` wherever the result has one and say plainly that none exists otherwise
(measurement-only groups, lakes, parameters without a project limit), never present the comparison as compliance (national aggregation rules such as LIMeco and
HWQI are not reproduced; it is a screening aid), say that a country comparison uses only the sites with data in both periods, never describe sandbox annual
aggregates as monthly, and take every data range from `data_range` (`list_countries` per source, or the result), never from memory. The grounding check accepts the
new numbers because each is in the tool result (a percent as `{amount, unit: "%"}`, a count as a plain number, a mean as `{amount, unit}`); a number the tool did not
return, for example a percent computed by the model, is reported in `ungrounded_numbers` as before (tests in `tests/unit/test_period_change_chat.py`).

Inputs use the REST bounds: closed parameter names (the closed names plus the labels of the listed-but-not-compared Waterbase
determinands, case-insensitive, canonical name passed on), ISO dates, `date_from` not
after `date_to`, `limit` an integer from 1 to 500 (default 50), a bare site id (letters, digits, `.`, `-`, `_`), a
two-letter country. A bad call is returned to the model as an error result, never raised. Unknown argument names are refused.

Country is enforced by the tools, not trusted to the model: while a country is selected, a site whose `limit_country` is
another country or unresolved is refused (a Waterbase site by its own country), and `list_sites` for another country is refused, so two countries' regimes are
never mixed. With no country selected a site can be read and its own country is reported in the result.

Results: `MAX_TOOL_RESULT_CHARS` (12000) bound by dropping trailing items (`truncated` and `returned` then say so), then
`sanitize_evidence` (control and invisible characters, instruction-like text and URLs removed, strings cut at 200
characters), then `<` and `>` escaped. The freshness inside a result carries status and `as_of` but not the age.

### External context tools (package 7, `docs/external_context.md`)

Three tools give context AROUND a site from public providers; their results are never the site's own measurements, never monitoring, and never evidence of
causation. A tool takes a bare site id (never a coordinate, URL or host), the selected country is enforced like for the other tools (a site of another
country is refused), the period is bounded (at most 1096 days), the group is a name of the closed taxon list, and unknown arguments are refused. The result is
compacted (every number is `{amount, unit}` with `n_days` and `coverage_percent` where they apply), carries `origin` (`external-open-meteo` or `external-gbif`),
`data_kind`, `provider`, `status`, `reason`, `attribution`, `licence`, `data_note`, `flags` and the fixed English `notices` of the provider (each shorter than the
sanitiser's 200-character cut, so none is truncated), and its `data_freshness` is `external-context` (not the sandbox freshness). A provider that is off, over its budget
or failing is a normal result with `status: external-unavailable` and a `reason`: the model must say so plainly and estimate nothing. The system prompt
(`CHAT_EXTERNAL_FACTS` in `src/oah/chat/prompts.py`) requires: name the provider and its attribution (`Weather data by Open-Meteo.com`), say the values are external and
MODELLED or OPPORTUNISTIC, never present them as the site's data nor use them in a limit comparison, an index or a period comparison, never say or imply that rainfall, flow,
temperature or a species record caused, explains, led to, contributed to or indicates a water-quality value (the strongest allowed statement is that rainfall may be relevant,
and only when a weather or flow result and a water-quality result for the same site and period were both returned), never compute or compare the context numbers, report the
flags, and never read "no record" as "absent". Deterministic backstop: when an answer rests on an external tool result, `oah.chat.causation` flags a sentence that names a weather,
flow or species term and a water-quality term with a causal cue ("caused", "due to", "because of", "led to", "explains", "contributed to") or an indicator verb ("indicates",
"proves", "confirms"); the flag `unsupported-causal-claim` makes the answer `withheld`, like any unsafe answer. A negation before the cue ("does not show that rain caused ...")
is not counted. The check is English, a regular-expression heuristic and easy to evade by rewording; the prompt and the grounding check remain the other controls. The grounding check
accepts the numbers because each is in the tool result (tests: `tests/unit/test_external_chat.py` with a scripted model that quotes the numbers, invents one, uses the wrong unit and
claims causation in three wordings). The `index` values `water-quality` and `water-parameters` offer the three tools and `microbiology` offers the weather tool; with no index the model
gets all fourteen. A chat answer whose tool results were all external has `origin` `external-open-meteo` or `external-gbif`; any mix with another source is `real-mixed`.

## 3. Limits

| Limit | Value | Where |
|---|---|---|
| Model calls ("steps") per conversation | `OAH_CHAT_MAX_STEPS`, default 6, hard ceiling 8 (higher values are lowered) | `ChatLimits`, `ChatSpendGuard.max_steps` |
| Tool executions per conversation | twice the steps; at most 4 per model response | `agent.py` |
| Output tokens per model call | 1024 | `MAX_OUTPUT_TOKENS` |
| Wall clock per conversation | `OAH_CHAT_TIMEOUT_SECONDS`, default 45, ceiling 120; each call also bounded by 30 s | `agent.py` |
| Tool result size | 12000 characters | `tools.py` |
| Question, history | 500 characters, 6 turns of 500 | schema and `clean_inputs` |
| Conversations per rolling 24 h, whole process | `OAH_CHAT_DAILY_CAP`, default 100 | `ChatSpendGuard.reserve_call` |
| Requests per host per minute | `OAH_CHAT_RATE_LIMIT_PER_MINUTE`, default 5; the bucket is the client address plus the optional `X-OAH-End-User` token (section 9) | `enforce_chat_rate` |
| Provider retries | none: the client is built with `max_retries=0`, so a failed call is reported once as a 502 and no SDK retry sends a call that no cap counts | `oah.explain.client` |
| Model calls per rolling 24 h, whole process | `daily cap x max steps` (600 by default) | `ChatSpendGuard.try_reserve_model_call` |

The last step is sent with `tool_choice: none` so the model has to write its answer. If the budget, the tool allowance, the
deadline or the model-call cap is reached before an answer exists, the response is `status: budget-exceeded` with a fixed
"could not answer within the step budget" text and nothing is guessed. The loop is a `for` over the steps, so it cannot run
unbounded whatever the model returns.

Cost model: one conversation costs at most `max_steps` model calls (default 6), against one for an explanation, so chat has
its own caps and does not draw on `OAH_EXPLAIN_DAILY_CAP`. The conversation is reserved only after the request is valid,
the cache missed and the client exists; a 422, a 503 for a missing key and a cached
repeat consume nothing. A provider failure after the reservation does consume it. An identical request (message, country,
index, history, model) is answered from a cache for `OAH_EXPLAIN_CACHE_TTL_SECONDS` without a model call; only `answered`
results are cached. All counters are in-process: they are valid for the single Cloud Run instance in the deployment plan
and do not coordinate across workers.

## 4. Output checks

On the final text, against the concatenation of the successful tool results (the evidence):

* `check_grounding`: numbers and units must trace to the evidence (`grounded`, `ungrounded_numbers`, `unit_mismatches`).
  The checker's limits are in `src/oah/explain/grounding.py` (a correct number attached to the wrong claim, derived
  numbers). Because each measurement number is wrapped with its own unit, a right number with the wrong unit is caught.
* `guard_output` (mode `describe`): URL, HTML, markdown link, code block, leaked instructions, health claim, excess
  length. If any of the unsafe flags (`oah.explain.safety.UNSAFE_OUTPUT_FLAGS`) is present, `unsafe` is true and the
  `answer` is null (`status: withheld`). The leak check compares the answer with the chat-specific part of the system
  prompt; the two reused clauses are left out on purpose, because the required referral wording ("competent authority and
  an accredited laboratory") is inside the scope clause and would otherwise flag a correct answer.
  * Run length (`guard_output(..., shingle_size=6)`, default 6 for the explain routes, unchanged; an entry may be a `(text, size)` pair,
    `CHAT_LEAK_CHECK_SIZED`): the chat compares the role prompt by runs of 10 consecutive words and the untrusted-data clause by runs of 8.
    Reason: the first live run (2026-10-04) withheld a correct, grounded answer because it shared the 6-word run "are reference values not
    legal limits" with the prompt. Natural echoes of instructed wording are 6 to 8 words; a real dump of the prompt copies long verbatim
    runs (tests use 12 and 15 words and the whole text). The untrusted-data clause is a security instruction a correct answer has no reason
    to repeat, but a decline of an injection may echo "say so in one short sentence" (6 words), hence 8, not 10.
  * Moved out of `CHAT_ROLE_PROMPT` into `CHAT_WORDING_CLAUSE` (still in `CHAT_SYSTEM_PROMPT`, same text and meaning, not leak-checked):
    the sentences that tell the model what to say ("say so plainly" for no records or an unknown site; the out-of-scope list with "not
    available in this data"; "Values are reference values, not legal limits"). Residual: a dump of only that clause is not flagged; it is
    public in this document. Tests: `tests/unit/test_chat_leak_check.py`.
* A not grounded answer is WITHHELD (security hardening F6; the grounding rule itself is unchanged, and rounded numbers it already
  accepts still pass): when `check_grounding` reports an ungrounded number or a unit mismatch and no unsafe flag applies, the status is
  `withheld-ungrounded`, `answer` is null, and the response carries `grounded: false`, `ungrounded_numbers`, `unit_mismatches`, the fixed
  localised `notices.withheld_ungrounded_notice`, and the `steps` and `citations` of the tool results the model consulted, so the web app can
  still show that data. An answer that is both unsafe and not grounded is `withheld` (unsafe wins). Only a grounded, safe answer is
  `answered` (and cached). A withheld answer is never translated and never costs a translation call. A withheld answer (`withheld-ungrounded` or `withheld`) also carries `evidence`, a
  compact summary of the data the tools returned (section 10); an `answered` response never does. `/explain/*` behaves the same way
  (`status` `withheld` or `withheld-ungrounded`, `explanation` null, `evidence` kept).
* Markup guard (F7): `guard_output` flags ANY `<` followed by a letter, `/`, `!` or `?` (every tag, closing tag, comment, doctype and `<url>`
  autolink, whatever the tag name), and every markdown link form: `[text](url)`, `![alt](url)`, `[text][ref]`, `![alt]` and a `[ref]: url` definition at the start of a
  line (also after NFKC folding, so fullwidth forms are caught). Ordinary scientific text is not flagged: `<` before a digit, a space or `=` ("below <5 mg/L",
  "x < y", "<=") passes. Residual: `a<b` written without a space is flagged (a rare false positive), and a model can still produce a plain word that
  a reader might read as a link; plain text rendering remains the client rule.

## 5. Audit

Events in the existing hash-chained log (`oah.explain.audit`, `CHAT_EVENTS`): `chat-dispatch` (before anything is sent:
model, country, index, SHA-256 and character count of the question, history
turn count, sanitisation notes, tool names), `chat-model-call` (step, SHA-256 of the messages, written before each call),
`chat-tool-call` (tool, SHA-256 of the raw arguments), `chat-tool-result` (tool, ok, SHA-256 and size of the result,
number of sanitisation notes, `error_sha256`), `chat-error`, `chat-result` (status, steps, tool calls, tokens, grounded, flags, evidence and
answer digests) and `chat-cache-hit`. Security hardening F9: the question excerpt (80 characters, partly redacted) is REMOVED; the
trail holds the digest and the length of the question and no user text, no answer text, no tool result, no error message text and no client
address or end-user token. If a record cannot be written, the conversation stops with 503
before the next call leaves the process. A test checks that the chain verifies after multi-step conversations. Each record is also
emitted as one structured JSON line on stdout (digest-only, so Cloud Logging keeps it across restarts) and at most 4 rotated files are kept
on disk (`docs/architecture.md`, "LLM audit trail").

## 6. Threat model

| Threat | Control | Residual |
|---|---|---|
| Injection in the question | delimited `<question>` block with escaped angle brackets; the system prompt treats it as data; instruction-like text is flagged in `input_notes` and audited, not erased | pattern lists miss novel wording; the model may still follow it |
| Injection in `history`, or a forged assistant turn | cleaned, instruction-like turns replaced, URLs removed, passed as data inside the first user message, numbers not evidence | as above |
| Injection in tool output (a Location name, a note) | `sanitize_evidence`, escaped, the untrusted-data clauses; a tool cannot do anything but read | as above |
| Inventing numbers or units | grounding and unit check, reported to the caller | derived numbers and right-number-wrong-claim are not caught |
| Health or potability claim | scope clause, `unsupported-health-claim` flag, answer withheld | unusual wording escapes the regex |
| Cost runaway, loops | separate caps, step, tool, time and size bounds, model-call cap, per-host limit | in-process counters, one instance; a restart resets them |
| Cross-country mixing | tools refuse other countries' sites while one is selected | with no country selected the user may ask about any site, each answer names its own country |
| Credential leakage | the key is never in a prompt, result, trace or log; arguments in the trace are schema keys only, bounded, and credential-like strings are replaced | none known |
| Over-reading external context (a modelled or opportunistic value taken for the site's data, or for a cause) | `origin`, `data_kind`, fixed notices and flags in every result; `CHAT_EXTERNAL_FACTS`; the deterministic `unsupported-causal-claim` check withholds a causal or indicator claim | a reworded claim passes the heuristic; the numbers themselves are grounded |
| An external provider failing, slow or rate-limiting | timeouts, bounded retries, a cool-down after a 429, a process-wide budget and cache; a failure is a readable `external-unavailable` result, never an error that stops the conversation | in-process state, one instance |
| A URL, host or coordinate chosen by the model | none exists as an argument: the tools take a site id; hosts are constants on a three-host allow-list | none known |
| Data exfiltration through the model | no tool writes; only the three external-context tools reach the network, and they call three allow-listed hosts with parameters the code builds from a site id (no model-chosen URL, host or coordinate, nothing from the conversation is sent); links and HTML in answers are withheld | the model sees sandbox data by design |

## 7. Answer language (`language` field)

The agent, its tools and its system prompt stay in English and are unchanged; the guards (`check_grounding`, `guard_output`) run on the
English answer. If `language` is not English and the status is `answered`, `oah.i18n.translator` makes ONE more model call that translates
only the validated English answer, and the translation must pass language-neutral checks (same numeric tokens, no other numeral
systems, no URL, HTML, markdown link, code fence or invisible character, bounded length, no copied instructions, optional best-effort
denylist for es, it, el, fr, de, pt, nb) or the English answer is returned with `translation_status` `rejected` or `failed`.

* Cost: the translation call is reserved with `ChatSpendGuard.try_reserve_model_call` (the rolling cap of `daily cap x max steps`), not as
  a conversation, so `usage.model_calls` of a translated conversation is at most `max_steps + 1`; when the cap is reached the translation is
  `failed` (reason `budget`) and the English answer is shown. The translation has its own cache entry (key: question, country, index,
  history, model, and the language with the translation model); the English entry is shared across languages.
* A `withheld` answer is never translated (`answer` and `answer_en` null). The budget-exceeded and no-answer texts are fixed strings
  localised from `src/oah/i18n/strings/` (no model call).
* Instruction leak: the translation is also compared with `CHAT_LEAK_CHECK_PARTS` (plain strings, six-word runs, unchanged), besides the
  prompt of the translation call. Runs that the English source itself contains are not counted, so the instructed-wording false positive
  of the English check cannot occur there; the translation check was not weakened.
* Audit: `translation-dispatch`, `translation-result`, `translation-rejected`, `translation-error`, `translation-cache-hit` in the same
  hash-chained log (digests, language, model, reason codes; no text).
* Threat model additions are in `docs/language_support.md` section 2. Not tested live: only the scripted fake client was used.

## 10. Evidence summary of a withheld answer (`evidence`)

A withheld answer has no text, but the web app can still show the DATA the agent consulted. `oah.chat.evidence.build_evidence` makes a compact list from the sanitised results of the tools the
model called (never from model text). It is built only when the status is `withheld-ungrounded` or `withheld`; the field is null for `answered`, `budget-exceeded` and `no-answer`. An empty list means
a withheld answer whose tools returned no figures (a list of sites, a classification, an index).

| Tool result | Items |
|---|---|
| `get_site_measurements` | one per parameter and unit: the records' values with their year or dates (`statistic`, `n`) |
| `compare_periods` | site: one item with the two period means and `n_samples`; country: one item per source with the two means of site means |
| `get_bathing_samples` | one per indicator: the quantified sample values with their date; when the rows are only a cut of a longer selection (`truncated`) the item is the tool's own summary (`n_quantified`, minimum, maximum) |
| `compare_bathing_concentrations` | one per indicator: mean and, at a bathing water or in a country, median of each period with `n_samples` |
| `get_weather_context`, `get_river_discharge_context` | one per series (precipitation sum, mean temperature, mean discharge): the monthly values; `data_kind` says modelled |

Tools without figures (lists, `get_site_index`, `get_qc_summary`, the bathing history and season comparison, `get_species_nearby`) add nothing, and a failed tool adds nothing.

Rule for the values (documented constant `MAX_EXACT_VALUES` = 10, a working value): AT MOST 10 values are listed exactly, each with its period; MORE are replaced by `summary`:
`{kind: "observed-range", n, minimum, maximum, first_period, last_period}`. This is an OBSERVED range (the lowest and highest value seen, picked from the results, not computed), not a statistical
interval of any kind. A value reported as a bound (a `comparator` such as `<`) is listed with its comparator when few and counted apart (`n_censored`) when many, and is never taken for a result. Every number is
copied from the tool result unchanged: no rounding and no arithmetic.

Item fields: `tool`, `scope` (`type` site, country or bathing-water; `id`; optional `name`), `parameter` (a parameter or an indicator), `unit`, `period` (first and last period), `origin`, `attribution`, optional
`data_kind`, and `values` or `summary`. Only names and ids the tool results already hold as sanitised fields are kept (a site or bathing-water name, an identifier); remarks, rights holders, species text and
every other provider free text are never copied. Bounds (documented constants): `MAX_EVIDENCE_ITEMS` = 20 items in call order, `MAX_EVIDENCE_CHARS` = 12000 characters once serialised (trailing items are dropped), the same
call made twice is listed once, and `evidence_truncated` is true when anything was left out. The whole block goes once more through `oah.explain.safety.sanitize_evidence` (the function the tool results use: control
characters, instruction-like text and URLs removed, strings cut at 200 characters), so a hostile name in a result reaches the response as `[removed: instruction-like text]`. A short English `notices.evidence_notice`
(localised in 25 languages) explains it to the reader; it says that an observed range is not a confidence interval. Translation is unchanged: a withheld answer is never translated and costs no model call.

Tests: `tests/unit/test_chat_evidence.py` (few values exact, the ten/eleven boundary, many summarised, censored values, unsafe case, no evidence on answered, bound, injection, remarks dropped, the response,
no translation call, schema and OpenAPI).

## 11. Approximate figures and observed ranges (`approximate`)

Maintainer request: normal answers should avoid false precision. When the data are few or weak the agent says "about 0.34 mg/L, between 0.28 and 0.52 observed" instead of "0.340954".

**This is presentation rounding, NOT statistical uncertainty.** Nothing computes a standard error, a confidence interval or a significance. The observed range is the lowest and highest value seen, rounded
outward; it is not a confidence interval and the agent must never call it one. The policy lives in `src/oah/chat/precision.py` (pure; the constants are working values, not measured):

| Constant | Value | Meaning |
|---|---|---|
| `LARGE_SAMPLE_COUNT` | 20 | `n` of at least 20: `FIGURES_LARGE` (3) significant figures |
| `MEDIUM_SAMPLE_COUNT` | 5 | `n` from 5 to 19: `FIGURES_SMALL` (2); fewer than 5: 2 and `low_precision` |
| `FIGURES_LARGE`, `FIGURES_SMALL` | 3, 2 | any weakness reason also caps the figures at 2 |
| `BELOW_DETECTION_SHARE_THRESHOLD` | 0.25 | a quarter or more of the values below the detection or quantification limit |

Properties (property tests): rounding is half away from zero, so the sign is kept (an increase stays an increase, a decrease a decrease); a nonzero value is never rounded to zero (at least two figures
are kept); the error is at most half a rounding step; the figures never decrease as `n` grows; the observed range is rounded OUTWARD (minimum down, maximum up) so it contains every observed value; the approximate mean
or median always lies inside that range (and, as a last resort, more figures are used until it does).

Tool results (`oah.chat.tools.approximate`). The exact numbers stay; the block is added next to them, every number as `{amount, unit}` so the grounding check still pairs it with its unit, and no digit in a text field:

| Tool | Where | Contents |
|---|---|---|
| `compare_periods`, site | `approximate` | per period `mean` and `observed_range`; `change` (`absolute`, `relative_percent`, `direction` copied) |
| `compare_periods`, country | `approximate` in each result entry | per period `mean_of_site_means`; `change_of_site_means`; `median_site_relative_change`; no observed range (a country result carries no minimum and maximum, none is invented) |
| `get_site_measurements` | `approximate` on each LOW-PRECISION record, and a result-level note (`low_precision`, `reasons`, `basis`) | per weak record `value`, `observed_range` when it differs from the record's own minimum and maximum, `low_precision`, `reasons`; a record that is not weak carries no block (the exact value is given as usual, and long lists stay long); a sandbox record has no `n` and is always `annual-only-data`; a value with a comparator is left alone |
| `get_bathing_samples` | `approximate.indicators` | per indicator `mean`, `median`, `observed_range` |
| `compare_bathing_concentrations` | `approximate` in each indicator entry | per period mean and median (site: with `observed_range`; country: means of site means and medians of site medians); changes |

Common fields: `low_precision` (boolean), `reasons`, `rounding` (in words: two or three significant figures) and `basis` (a fixed sentence: presentation rounding, not a statistical uncertainty; the observed range is not a confidence interval).
Reason codes, taken from facts the tools already carry: `few-samples-in-a-period` (`n` below 5 in a period that has a mean), `partial-period` (the existing flag), `high-below-detection-share`
(below-quantification or detection-limit values at least a quarter of the period's values), `few-paired-sites` (flag `few-sites`, or fewer paired sites than the threshold), `annual-only-data` (flag `annual-only`, or a sandbox record).
`compare_bathing_seasons` returns class counts only (no mean and no change of a number), so it has no block.

Prompt (`CHAT_PRECISION_FACTS`, added to the system prompt after `CHAT_DATA_FACTS`; like it, not compared by the instruction-leak check, which holds only the role and untrusted-data clauses): when `low_precision` is true write the approximate values
with "about" or "roughly" and the observed range, state n, say briefly why the data are weak and give a percent change only as precisely as the block does; when it is false give the exact values as before; never state an interval that
is not an observed range from a tool; never write "confidence interval" or "margin of error" or imply significance; keep the screening-not-compliance wording. The earlier rule "never round beyond what a tool result shows" is unchanged: the approximate numbers are in the result.

Grounding is NOT loosened (`src/oah/explain/grounding.py` is unchanged). The approximate numbers pass because each is in the tool result; the exact numbers pass as before; an invented interval (numbers absent from the result) and a
wrongly rounded number (neither the exact nor the approximate value, beyond the half-unit tolerance) are reported in `ungrounded_numbers` and the answer is withheld. Translation keeps the existing numeric-token checks, so an
answer with approximate values and a range translates and verifies like any other (a changed number is rejected). Tests: `tests/unit/test_chat_precision.py`.

Size (measured on invented data): the block adds about 770 characters to a site period comparison (2911 characters in all, against the 12000 bound), about 615 to a country entry and about 210 to a low-precision measurement record (a record is about 560 characters without it); a record that is not weak adds nothing. A long measurement or samples list is still shortened by the existing list shrink, which runs after the block is added, so no result can exceed `MAX_TOOL_RESULT_CHARS` (tests with 500 records). A list of 500 weak records returns fewer records per call than before because each carries its block. Not verified live: whether the model follows the prompt guidance (the only control for the wording; the checks above catch only numbers and units).

## 9. Per-visitor fairness, spend and the Vercel layer (security hardening F3, backend part)

Behind Cloud Run every caller shares one peer address unless the address is derived from `X-Forwarded-For`, so the per-minute chat and
explanation limits would be one bucket for the whole demo. The backend offers two optional, validated aids (details and settings:
`docs/api_routes.md`, "Access control and abuse limits"):

* `OAH_TRUSTED_PROXY_HOPS` (default 0 = off): the client address is the entry that many places from the right of `X-Forwarded-For`.
* `X-OAH-End-User`: an opaque 16 to 64 character token (`A-Z a-z 0-9 _ -`) set by the trusted web server layer, for example a keyed hash of a visitor,
  used ONLY as an extra part of the per-minute chat and explanation bucket. It is a fairness aid, NOT authentication: it is untrusted, it is ignored when absent
  or invalid, it is never logged or stored, and the shared `X-API-Key` remains the access control. A key holder can rotate tokens to escape the per-minute
  bucket, so the daily caps (`OAH_CHAT_DAILY_CAP`, the model-call cap) and the provider-side spend limit remain the real ceiling.

REAL per-visitor limiting and bot protection must live at the Vercel layer: a firewall or rate-limit rule on the chat route, a bot or
challenge check, and a per-visitor limit in the route handler before it calls this backend. The backend cannot tell visitors apart by itself and
does not try to authenticate them. The remaining budget is deliberately not shown to callers (`usage` no longer carries it), so a visitor cannot see how
much of the shared allowance is left.

## 8. Known limits and provisional items

* The "not available in this data" behaviour for unavailable topics relies on the system prompt (a model decision), not on a
  deterministic router. A question that mixes an available and an unavailable item may be answered for the first only.
* `citations` list the tool results consulted, not a per-number attribution; `list_sites` yields one citation per site.
* The tool-use format (`tools`, `tool_choice` `auto` and `none`, `tool_use` and `tool_result` blocks) was checked against the
  pinned SDK types (`anthropic==1.7.0`) and exercised only with a scripted fake client; no live provider call was made, so
  the first live run should be reviewed (token use per conversation, refusal wording).
* The conversation is English only; other answer languages are a verified translation of the validated English answer (section 7,
  `docs/language_support.md`). The default tool `limit` (50) and the other bounds above are working values, not measured ones.
* Provisional by inheritance: the site `kind` keywords and third-party record markers (`docs/api_routes.md`,
  `docs/official_record_filter.md`).
* The bathing-water tools and prompt facts (package 4) were exercised only with the scripted fake client; a live run should check
  that the model never states a class as a concentration and that "is it safe to swim" is declined (the existing health clause and
  the `unsupported-health-claim` flag are the only controls). Class strings such as `3 - Good or Sufficient` and `0 - Not
  classified` are passed as written; the README does not explain them and the model is not told to.
* The samples tools and prompt facts (package 6) were exercised only with the scripted fake client. A live run should check that the model never states or invents a
  threshold, never calls a value good, bad or safe, reports a detection-limit or missing value only as a count, gives n and the dates, and declines "is it safe to swim" with the
  referral wording (the prompt, the `unsupported-health-claim` flag and the grounding check are the only controls; the tests cover an invented concentration, an invented
  threshold, an invented percent and a "safe to swim" answer). A mean or median over a bathing season is not a classification and the model is told so.
* The period tools and prompt rules (package 5) were exercised with the scripted fake client only. The first live run should check that the model never
  computes a change itself, never shifts a period beyond the data, states `n_samples` and the flags, and does not present a limit comparison as compliance. The
  prompt is the only control for those behaviours (the grounding check catches an invented number, not a wrong claim attached to a right number).
* Waterbase additions (package 3) were exercised only with the scripted fake client as well. A question about a later year
  than a country's `latest_year`, or about a lake limit, relies on the system prompt facts and on the tool result saying so.
* The external tools and prompt facts (package 7) were exercised only with the scripted fake client and fake HTTP layers (one real end-to-end run of the helper against each provider
  is in the ledger entry). A live chat run should check that the model names the provider and attribution, says the values are modelled or opportunistic, never links rainfall or a
  species to a water-quality value beyond "may be relevant", and says plainly when a provider is unavailable or a period is outside its data. The causal check is a heuristic.
* The approximate figures and the evidence summary (sections 10 and 11) were exercised only with the scripted fake client. The first live run should check that the model writes "about" or "roughly" with the
  observed range and n when `low_precision` is true, gives the exact values otherwise, never says "confidence interval" or implies significance, and never states an interval that is not an observed range; the
  prompt is the only control for that wording (the grounding check catches an invented or wrongly rounded number, not a misleading phrase). The thresholds (20, 5, 0.25, two or three figures, ten exact values) are working values.
* Needs `code-reviewer` and `qa-test-engineer` before merge.
