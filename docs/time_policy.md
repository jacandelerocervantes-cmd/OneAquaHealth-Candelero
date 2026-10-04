# Time policy

One policy for every timestamp in the project, implemented in `src/oah/timeutil.py` and guarded by
`tests/unit/test_time_policy_guard.py`. Source of the rules: the ISO 8601 / FHIR `date`, `dateTime` and
`instant` formats and the IANA time zone database (the `tzdata==2026.4` package, pinned because Windows
ships no zone data; zone rules change several times a year, so review it on every release).

## Rules

1. **Internal representation:** a timezone-aware `datetime` in UTC. A naive datetime is never an instant
   (`require_aware` raises `TimeError`).
2. **One clock:** `utc_now()`. No other module calls `datetime.now`, `utcnow`, `time.time` or
   `time.strftime` (the guard test fails otherwise), so a test can replace the clock in one place.
3. **One text form:** `format_utc(value)` = ISO 8601 with the `+00:00` offset. Previously two forms
   coexisted (`+00:00` and a trailing `Z`); `Z` is still accepted when parsing.
4. **Epoch numbers:** `from_epoch_seconds` and `from_epoch_millis` are separate functions; the unit is never
   guessed from the size of the number.
5. **Elapsed time** is computed with `elapsed(a, b)` between UTC instants. Subtracting wall-clock times is
   wrong across a clock change, when a local day lasts 23 or 25 hours (tested for Athens and Rome on
   2026-03-29 and 2026-10-25).
6. **Local time is for display and for reading sources that use it.** `to_local(instant, zone)` shows an
   instant on a wall clock; `add_local_days` adds calendar days keeping the local hour, which is not the
   same as adding 24 hours.

## Reading external timestamps: `parse_fhir_time`

| Input | Result |
|---|---|
| `2026`, `2026-09`, `2026-09-26` | The UTC interval `[start, end)` the value denotes, with `precision` `year`, `month` or `day`. With `site_tz` it is the site's local calendar period; without it, the UTC calendar period and `tz_source == "none"`. |
| `2026-09-26T10:00:00Z` or with an offset | An exact instant (`precision == "second"`, `tz_source == "explicit"`), fractions kept to the microsecond. |
| `2026-09-26T10:00:00` (time, no offset) | Rejected, unless the caller names `site_tz`. It is never guessed. |

Clock changes are reported, not resolved silently:

- A local time that **does not exist** (spring forward, for example Athens `2026-03-29T03:30`) raises
  `NonexistentLocalTime`; `on_gap="shift-forward"` moves it to the first valid instant.
- A local time that **occurs twice** (fall back, for example Athens `2026-10-25T03:30`) raises
  `AmbiguousLocalTime`; `on_ambiguous="earliest"` or `"latest"` picks one occurrence explicitly.

## Site time zones

`site_timezone(country_code)` knows only the pilot countries (`EL` and `GR` map to `Europe/Athens`, `IT` to
`Europe/Rome`) and refuses any other country instead of guessing. The FHIR sandbox `Location` resources
carry no time zone, so a time of day without an offset needs a zone supplied by the caller. Waterbase records
carry a sampling date without a time of day (`phenomenonTimeSamplingDate`); that is a `day` interval, not an
instant.

## Not yet applied

The fixture and sandbox Observations still hold their original `effective` text unparsed; nothing in the
current indices depends on their time order. When a feature needs it, read them with `parse_fhir_time`, keep
the precision, and compare intervals, never bare strings.
