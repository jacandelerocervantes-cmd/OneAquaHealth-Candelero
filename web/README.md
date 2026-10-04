# OneAquaHealth web app

Next.js (App Router), TypeScript and Tailwind CSS. Full description, data modes, security rules and what was verified:
[`docs/web_app.md`](../docs/web_app.md). Design: [`docs/web_app_design.md`](../docs/web_app_design.md).

```
npm install
npm run dev        # mock data by default (OAH_DATA_MODE=mock)
npm run check      # type check + lint + tests
npm run types      # regenerate src/lib/api-types.ts from ../docs/openapi.json
```

Real mode needs the server-side variables `OAH_DATA_MODE=real`, `OAH_BACKEND_URL` and `OAH_API_KEY` (see `env.example`).
They are read only by the route handlers; the browser never sees them.
