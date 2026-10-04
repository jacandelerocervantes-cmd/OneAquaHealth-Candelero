# Known issues of the AI explanation layer (`/explain/*`)

Status: 2026-09-26. Source: two real runs of `scripts/eval_explain.py` with `claude-opus-5` (4 calls each, 8 outputs in
total), each output read by a human. Details of the runs are in `docs/architecture.md`; this file tracks what must be
corrected. **Eight outputs from one model support no general claim**, in either direction.

Status key: **FIXED** means a change was made and a later real run showed the problem gone (on 2 outputs at most);
**CHANGED, UNVERIFIED** means a change was made but no real run has checked it; **OPEN** means not addressed;
**BY DESIGN** means the limit is accepted and documented.

## The three findings of the first real run

| # | What happened | Cause | Status | Evidence of the status |
| --- | --- | --- | --- | --- |
| 1 | The model wrote "6.4x" for a worst excursion of 6.36. An excursion is a relative excess, so the reading was 7.36 times the limit | The evidence had `worst_excursion` only, with no meaning, value, limit or unit | **FIXED** | Veto entries now carry `worst_value`, `limit`, `unit`, `times_limit`, and the prompt has a glossary. Run 2: both WQI outputs wrote 7.36 or "about 7.4 times" |
| 2 | A conductivity exceedance was called "possibly real". It is an artefact of a drinking-water-type limit applied to a brackish coastal stream | The model was not told the limits are proxies | **FIXED** | `objective_limits_source` is in the evidence and the glossary says an exceedance is a flag, not proof. Run 2: both WQI outputs said "proxy", "flag to investigate", and one noted a saline baseline. The `assess` concern level fell from high to moderate |
| 3 | The `assess` output for a review item said the candidate families "sit differently on pollution-tolerance scales", a claim that is not in the evidence | The `assess` mode invites judgment and the model filled it with general taxonomy knowledge | **CHANGED, UNVERIFIED** | Present in run 1 and again in run 2, so it was NOT fixed by the evidence and glossary changes. The `assess` system prompt now forbids stating general domain knowledge as fact and asks the model to tell the reviewer to check it instead. No real run has tested this |

## Related items found while doing this (also to be corrected or accepted)

| # | Item | Status | What is needed |
| --- | --- | --- | --- |
| 4 | The number check cannot see a right number on the wrong claim (finding 1 was exactly that) or a claim with no number (finding 3) | **BY DESIGN** | Human review, richer evidence, and prompt rules. A deterministic detector for claims outside the evidence does not exist |
| 5 | The check flags derived counts such as "those two families" and "two measurements" (false alarms). Two of four outputs in run 1 were flagged for a harmless enumerator ("Two points for your decision"); that case is now exempt | **BY DESIGN** for derived counts, **FIXED** for enumerators | Accept the alarms, or allow counts that equal the number of distinct names quoted in the same sentence (not built) |
| 6 | The explanation of a real-sandbox site is built from evidence that may come from a stale local snapshot when the sandbox is down, and the response does not say so | **OPEN** | Add a `data_freshness` field to `/indices` and to the evidence so the model and the reader can see it |
| 7 | Explanations are English only; the frontend language switch does not translate them, and the check is built for English | **BY DESIGN** | A Spanish version needs a Spanish number-word and decimal-format check, measured with the adversarial harness before it is trusted |
| 8 | The grounding rates in the harness (0 percent false rejections, 100 percent detection) are for cases the project authors wrote; the curated set was tuned against the original failures and the newest cases were written after seeing real output | **OPEN** | A larger sample of real outputs labelled by a human |
| 9 | Cost per run was measured only for run 2 (2,906 tokens in, 2,214 out; an upper bound of about 0.21 USD if the price were 15 / 75 USD per million tokens, real price not checked) | **OPEN** | Log token usage on every run (now recorded in `Explanation`) and check the price |
| 10 | The `/explain/*` endpoints have not been called through the API with a real client in this project; the real runs used the script with the same code path | **OPEN** | One real call through `GET /explain/indices/{id}` |

| 11 | Prompt-injection defences exist (sanitiser, untrusted-data clause, delimited evidence, output flags) but no real model has been tested against injected evidence; the harness uses payloads the authors wrote | **OPEN** | About 4 real calls with hostile evidence strings, then a human read; see `docs/security_review.md` section 6 |
| 12 | Spend limits (5 a minute, 100 a day) are in process memory: a restart resets them; the real cap is the console spend limit | **BY DESIGN** | Set a spend limit in the Anthropic console; lower `OAH_EXPLAIN_DAILY_CAP` for a small budget |
| 13 | The frontend must render explanations as plain text; the output flags are advice, not a block | **OPEN** for the frontend phase | Never insert explanation text as HTML |

## How to verify finding 3 (about 4 calls, a few cents)

1. Run `scripts/eval_explain.py` once.
2. Read the two `assess` outputs. Finding 3 is fixed only if neither states taxonomic or ecological facts that are not in
   the evidence (for example tolerance to pollution) as a fact.
3. Record the result here and in `docs/handoff/LEDGER.md`. If the claim returns, the next option is a validator pass that
   flags sentences with no reference to any evidence field, which would need its own adversarial evaluation.
