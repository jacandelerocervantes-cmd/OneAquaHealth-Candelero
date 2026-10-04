# Web app interface language

Status: 2026-10-04. The whole interface (menus, labels, notices, table headers, error messages) follows the language
selected in the language selector next to the question box, not only the chat answers. Default: English (a visitor who has not chosen a language sees English; the choice is kept in
the browser). The 26 codes are
the ones of the backend (`GET /languages`): English plus the 25 dictionaries in `web/src/lib/locales/`.

## How it works

- The key of every text is the English text itself: `t("Search by name")`. English shows the key. A language that lacks the
  key shows the English text, never a blank (a missing translation is readable, not broken).
- `web/src/lib/i18n-core.ts` holds the pure helpers (`msg`, `interpolate`, `resolveLocale`, `countryName`);
  `web/src/lib/i18n.ts` holds the `useT()` hook, which loads the dictionary of the selected language on demand (one
  dynamic import per language, so a visitor downloads one dictionary, not 25).
- Texts that live in constants or arrive from the service are wrapped in `msg("...")` where they are declared and shown with
  `t(text)` where they are rendered (`web/src/lib/constants.ts`, `DYNAMIC_TEXTS` lists the catalogue titles and the status
  words). A text that is in no dictionary is shown as received (English).
- Placeholders are written `{name}`; every translation must keep exactly the same placeholders.
- Numbers use the decimal mark of the language (`formatNumber`); country names come from the browser's region names
  (`Intl.DisplayNames`); dates stay in ISO form (`2024-12-31`), which is unambiguous in every language.
- `<html lang>` follows the selected language. The backend also receives the language: `/catalog` returns the reason
  an index does not apply in that language, and the chat answers in it (`docs/language_support.md`).

## What is NOT translated, on purpose

- Attribution and credit wording required by the data providers (EEA, Open-Meteo, GBIF, OpenStreetMap): the `name` and
  `credit` of `web/src/lib/attributions.ts`, and the attribution strings returned by the service with each response.
- Notices and data notes written by the backend routes (`notice`, `data_note`, `interpretation_notice`): they arrive in
  English from the service and are shown as received.
- Names of places, parameters and units, and the technical tokens E. coli, GBIF, EEA, Waterbase, CC BY 4.0, HL7.

## Quality of the translations

The 24 dictionaries that are not English are **machine-drafted** (written by the model, not by native speakers) and have not
been reviewed by humans, in line with `docs/language_support.md`. They are checked automatically, not linguistically:
`npm run i18n` (also part of `npm run check` and of the Web app workflow) fails when a language misses a text, holds a text
that is not in the source, changes a `{placeholder}`, or adds markup or a link. A native-speaker review is open work, and
`es-MX` (the maintainer's language) should be reviewed first.

## Changing or adding a text

1. Write the text through `t("...")` (or `msg("...")` for a constant) with a double-quoted literal.
2. `npm run i18n:extract` rewrites `web/src/lib/locales/_keys.json` (the list of English texts).
3. Add the translation to each file in `web/src/lib/locales/` (the check names every missing key).
4. `npm run check`.

Tests: `web/tests/i18n.test.tsx` (resolution, placeholders, fallback, number format, country names, language switch).
