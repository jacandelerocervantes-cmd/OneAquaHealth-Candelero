# Limits: changing them, and how one becomes verified

## Status of this project (hackathon)

This is a hackathon project, not a tool for regulatory use in Europe or anywhere else. The shipped limits are
documented reference values (EU, Italian and Greek) with their sources; nobody has signed them, and signing is
**optional** and only becomes worth doing if the project is used for real decisions. What the project does need
is an easy, honest way to change the values, described first.

## Changing the values without editing code

Set `OAH_LIMITS_FILE` to the absolute path of a JSON file (keep it outside the repository, for example in the data
folder). It can replace any shipped limit, add limits for a new country, and assign countries or regimes to
locations. A starting point is `docs/limits_override.example.json` (invented demonstration values). The format
and rules are documented in `src/oah/indices/limit_overrides.py`; the important ones:

- every entry states its `unit`, which must equal the parameter's unit (a value in the wrong unit is refused, not
  guessed) and its `source` (say where the number comes from);
- values are finite and positive; a range needs the lower value below the upper one;
- a bad file is refused with a message naming the entry. At startup a bad file stops the server; while running,
  a bad edit is logged and the last good limits stay in effect;
- the file is re-read when it changes, so values can be edited while the API runs; unsetting the variable
  restores the shipped limits;
- every output shows the change: `limit_basis` reads `override: <source>` for the parameters affected and the
  result carries `limit_overrides` (file name, note, counts). An overridden limit is never reported as verified.

## How a numeric limit becomes verified (optional)

The index compares measurements with limits that look regulatory (drinking-water values, surface-water standards,
Italian LIMeco boundaries, Greek HWQI boundaries, project proxies). A wrong or unsourced number would look as
authoritative as a right one, so each limit carries a recorded verification state instead of an assumed one.

## What is recorded

`src/oah/indices/limit_verification.py` builds a **key** for every limit the code can apply, from the live
tables: `regime|country|parameter` (for example `drinking|-|Nitrate`, `surface|IT|Total phosphates`,
`surface|GR|Dissolved Oxygen`). `current_limits()` lists them with their value(s), unit and source basis.
`VERIFICATIONS` holds the **signatures**. Every site's `limit_basis` shows, for each parameter it used, the
source basis and one of:

- `[unverified]`: nobody has signed this limit (the state of every limit today);
- `[verified by <handle> on <date>]`: a person signed exactly this value and unit;
- `[verification stale: the value changed after it was signed]`: the number or unit differs from the one
  signed; the signature no longer vouches for anything and the row must be checked again.

## Who signs and how

- **Only a person signs.** An agent (including an AI assistant) prepares evidence and proposes; it never adds a
  signature. Approval given in a chat is not a signature.
- The signer compares the value with the **primary text** of the provision cited in the register
  (`docs/unvalidated_values_register.md`), not with a summary or a republication, and checks the unit basis
  (for example nitrate as the ion versus as N).
- The signature is added to `VERIFICATIONS` in a **human-authored commit**; the commit is the durable record
  of who, when and what was signed.

```python
VERIFICATIONS["drinking|-|Nitrate"] = Verification(
    verified_by="auditor-handle",          # a pseudonymous handle, never an e-mail address or a name
    verified_on="2026-10-01",              # ISO date, not in the future
    values=(50.0,),                        # exactly the value(s) compared (a range or dated limit has several)
    unit="mg/L",                           # exactly the unit compared
    evidence="Directive (EU) 2020/2184, Annex I Part B, L 435/37, row Nitrate 50 mg/l",
)
```

## Worksheet

`docs/limits_signing_worksheet.md` lists every limit with its value, unit, the provision to compare with and a
ready snippet to fill in. It is generated from the live tables (regenerate it after any change to a limit) and
signs nothing.

## What the tests enforce

`tests/unit/test_limit_verification.py` fails if a signature names an unknown limit, has a malformed handle, a
future date or empty evidence, or was made for a value or unit that no longer matches (so changing a limit
without re-verifying it cannot pass silently). It also asserts that no signature exists that an agent added.

## What verification does not mean

A verified limit means a person checked the number against the cited text. It does not turn an index into a
legal compliance finding: outputs keep the `interpretation_notice`, and proxies and conventions stay labelled as
such in `limit_basis`. Values with no legal source (for example water temperature or zinc) can be signed only as
what they are, a project convention.
