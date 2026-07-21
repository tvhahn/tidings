# Tidings frontend

Vite + React 19 + TypeScript. One build, three surfaces:

- **Real dashboard** — the daily app, talks to the FastAPI backend.
- **Marketing landing** — copy at `src/marketing/`, no backend.
- **Demo SPA** — static-fixture build that powers the public hosted demo.

For project-wide context (architecture, parsers, deployment, brand voice), see
[`/workspace/CLAUDE.md`](../CLAUDE.md). For frontend-specific conventions
that AI agents should follow, see [`./CLAUDE.md`](./CLAUDE.md).

## Dev surfaces

| Make target          | Port | Mode      | What it serves                                                                                    |
| -------------------- | ---- | --------- | ------------------------------------------------------------------------------------------------- |
| `make dev-frontend`  | 5173 | real      | Real dashboard against the real backend. Pairs with `make dev-api`.                               |
| `make dev-marketing` | 5175 | marketing | Marketing landing only — for editing copy/CSS in `src/marketing/`.                                |
| `make dev-demo`      | 5176 | demo      | Static-fixture demo SPA (mode=demo). No backend; reads `public/demo-data/`.                       |
| `make dev-preview`   | 4173 | preview   | Production preview — `pnpm demo:build` then `serve dist`. Marketing at `/`, demo SPA at `/demo/`. |

`BrowserRouter` basename in `src/main.tsx` is `/` in dev (any mode) and `/demo`
only in the production demo build, so the demo SPA mounts at `/` on
`:5176/` but at `/demo/` on `:4173/demo/`.

## Entry points

- `src/main.tsx` — both real-dashboard and demo modes (mode-switched via `import.meta.env.MODE`).
- `src/main-marketing.tsx` — marketing landing only.

## Where things live

```
src/
├── pages/             # Top-level route components (one per route in App.tsx)
│   └── settings/      # Settings sub-pages (lazy-loaded)
├── components/        # Shared components used by 2+ pages
│   ├── ui/            # shadcn/Radix-based design-system primitives
│   ├── settings/      # Settings-specific composites
│   ├── insights/      # Insights-specific cards
│   └── merchants/     # Merchants-specific cards
├── hooks/             # React Query hooks (one per resource); thin wrappers around lib/queryConfigs.ts
├── lib/               # Pure utilities, API clients, formatters
│   ├── api.ts         # Real API client (FastAPI backend)
│   ├── demoApi.ts     # Demo API client (static fixtures + localStorage overlay)
│   ├── queryConfigs.ts # React Query queries.* / queryKeys.* factories
│   └── queryUtils.ts  # Shared invalidation helpers (transaction-dependent caches)
├── stores/            # Zustand stores (theme, prefs, transient UI state)
├── types/
│   ├── api.generated.ts  # openapi-typescript codegen — DO NOT edit
│   └── api.ts            # Hand-maintained barrel re-exporting friendly names
├── marketing/         # Marketing landing components and sections
└── test/              # Vitest setup, factories, render helper
e2e/                   # Playwright end-to-end tests
```

## Data layer

All HTTP calls live in `src/lib/api.ts` (real) and `src/lib/demoApi.ts` (demo,
parallel structure). React Query usage centralizes through
`src/lib/queryConfigs.ts`:

```ts
// Canonical hook shape — see src/hooks/useCategories.ts
import { useQuery } from "@tanstack/react-query";
import { queries } from "@/lib/queryConfigs";

export function useCategories() {
  return useQuery(queries.categories());
}
```

Use `queryKeys.*` factories instead of inline `["foo", x]` arrays when
invalidating. For transaction mutations, use
`invalidateTransactionDependents()` from `src/lib/queryUtils.ts` rather than
hand-rolling the dependent-query list.

## Commands

```bash
pnpm dev              # 5173 — real dashboard (use `make dev-frontend` for stable port)
pnpm marketing:dev    # 5175 — marketing landing
pnpm demo:dev         # 5176 — static-fixture demo SPA
pnpm test             # vitest run (pure-function tests in src/**/*.test.ts)
pnpm test:fast        # vitest run --bail=1 (faster local loop)
pnpm test:watch       # vitest --watch
pnpm e2e              # Playwright end-to-end suite (e2e/)
pnpm codegen          # regenerate src/types/api.generated.ts from ../openapi.json
pnpm lint             # ESLint flat config (tseslint strict + import + a11y + react-hooks)
pnpm format           # Prettier write
pnpm format:check     # Prettier check (CI-equivalent)
pnpm build            # TS build + Vite production build
pnpm demo:build       # Production build with mode=demo
pnpm demo:fixtures    # Regenerate demo fixtures from the real DB
```

## Verifying changes

After UI changes, follow the **Frontend Visual Verification** section in
`/workspace/CLAUDE.md` — start the dev server, exercise the affected page in
Chrome DevTools, check `list_console_messages` for React errors. The
fast feedback loop is `make verify-frontend`; the full gate is `make verify`.

## TypeScript strictness

`tsconfig.app.json` enables `strict`, `noUncheckedIndexedAccess`,
`exactOptionalPropertyTypes`, `noFallthroughCasesInSwitch`,
`noUncheckedSideEffectImports`, `noUnusedLocals`, `noUnusedParameters`. ESLint
extends `tseslint.configs.strict` plus `import/no-cycle`,
`eslint-plugin-react-hooks`, `eslint-plugin-jsx-a11y`,
`eslint-plugin-react-refresh`. New code is expected to pass both gates.
