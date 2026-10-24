# MarketMyna web app

React + TypeScript + Vite front end for the MarketMyna API.

```bash
npm install
npm run dev      # http://localhost:5174, /api/* proxied to the API on :8001 (vite.config.ts)
npm run build    # translation check, type check, production bundle in dist/
npm run lint     # oxlint
```

- `src/pages/` one file per route (`App.tsx`), `src/components/` shared UI
  (`ui.tsx` holds the primitives), `src/api/` typed calls to `/api/v1`,
  `src/lib/` helpers, `src/seo/` page titles.
- `npm run build` writes `dist/`, which the API serves at `/` (`api/app.py`
  `serve_frontend`), so one `uvicorn` process runs the whole app.
