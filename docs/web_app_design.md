# Web app design (final, from the maintainer's decisions of 2026-10-03)

Reference: the layout of the Claude desktop app (left sidebar with grouped entries, conversation in the centre, input
box at the bottom). Supersedes the layout sketches in `docs/web_app_chat_by_country.md`; the data rules, the access
model (one shared access protected by Vercel, secrets only server-side) and the language rules of that document and of
`docs/language_support.md` still apply. Index catalogue and data sources: `docs/indices_catalog.md`.

## Layout

- **Left sidebar, top:** the **country selector** (Greece, Italy, Norway: the list comes from `GET /countries`). It sits
  where Claude shows "New chat". Below it, **New question**.
- **Left sidebar, body:** collapsible **sections**, each with a `+` that starts a new question inside that section, and
  the **indices** of that section as entries. **No numbers anywhere** (neither on indices nor as counts).
  - Indices that do not apply to the selected country are **hidden**. Indices that are not available at all (biotic
    quality, protozoa, air quality, population health) are **not shown**.
  - Sections and indices: **Water** (Water quality, Water parameters, Solids and turbidity, Organic matter);
    **Microbiology** (Bathing classes, E. coli and enterococci); **Context** (Weather, River discharge, Species nearby);
    **Data** (Data quality); **Synthetic labs** (Citizen science, Review queue, River risk).
  - A small coloured dot tells the origin of each index: real data, external modelled context, synthetic.
- **Left sidebar, bottom:** the user (a shared "Judge account" label) and a **settings** button. Settings holds the
  default language, the default country, and **About and attributions** (licences and credits required by the data
  providers: EEA, Open-Meteo, GBIF, OpenStreetMap, the HL7 Europe sandbox).
- **Header of the conversation:** the title of the current index, a chevron that opens a short "About this index"
  panel (coverage for the selected country, data range, sources), a download button for the data behind the answer,
  and the **map icon**.
- **Map:** only an **icon** in the header. The map is a **right-hand pane that is closed by default** and opens only when
  the user clicks the icon, like the preview or diff pane of Claude Code. Opening it does not start a question. It
  shows the sites of the selected country and index; selecting a site shows its card and can pass it as the context of
  the next question. OpenStreetMap tiles with the required attribution, no tile proxy or prefetch.
- **Conversation:** a centred column. Each answer carries its origin tags (real, external modelled, synthetic; grounded;
  data range) and a **"Sources and method" block inside the answer** (data source and licence, the method, the limit and
  its source where one exists, the screening-not-compliance warning, coverage flags), filled from the metadata the
  routes return, never written by the model. The fixed disclaimer closes every answer. There is **no separate "Method and
  sources" page**.
- **Input:** a text box at the bottom with a row of controls: the **language** chip (the 26 languages of
  `GET /languages`, default Spanish (Mexico) for the maintainer) and send. The chat model is fixed (Sonnet 5.5) and not shown.

## Rules that carry over

- All model text is rendered as plain text; an answer marked `unsafe` is never rendered; the translation status and the
  English original (`answer_en`) are available from the answer.
- The browser never holds a secret: it calls same-origin route handlers on the server, which add the backend access key
  from a server-only variable and allow only the routes the app uses.
- Honesty first: real, external (modelled or opportunistic) and synthetic data are always labelled and never mixed
  silently; a period outside the data range is reported, never shifted; no health or safety verdicts.

## Backend support needed

- `GET /catalog?country=XX` (built, 2026-10-03): the families and indices with their availability for a country
  (authoritative: the web app only hides what the backend marks as not applicable). `country` is required; `language` is
  optional and localises the reasons only. Every index is returned with `applies`, so the app hides the ones where it is
  false; `stores` says which store is not built so a notice can be shown. Routes and tools behind each index, the rules and
  the reason codes: `docs/api_routes.md`.
