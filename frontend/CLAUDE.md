# Frontend agent guide

This file is a frontend-specific addendum to `/workspace/CLAUDE.md`. Read the
root file first for project-wide context (architecture, parsers, deployment,
brand voice). This file documents conventions specific to `frontend/src/`.

## File layout

Non-obvious placement rules (the tree itself is `ls`-discoverable):

- `src/components/` — shared components used by 2+ pages; `src/components/<feature>/` holds feature-scoped composites (settings/, insights/, merchants/)
- `src/components/ui/` — shadcn/Radix design-system primitives only; don't add app state here
- `src/pages/settings/` — settings sub-pages, lazy-loaded
- `src/hooks/` — React Query hooks; see "Data layer" below
- `src/stores/` — zustand stores (theme, preferences, transient UI state)
- `src/types/` — `api.generated.ts` (codegen, do NOT edit) + the `api.ts` barrel
- `src/test/` — vitest setup, factories, render helper

## Data layer

`src/lib/queryConfigs.ts` is the source of truth for all React Query cache
keys, fetch functions, stale times, and mutation invalidation contracts.
Three exports drive everything:

- `queryKeys.*` — key factories (e.g. `queryKeys.journal(month)`).
- `queries.*` — full `useQuery` option objects (e.g. `queries.journal(month)`).
- `mutations.*` — full `useMutation` option objects (e.g. `mutations.updateBudget(year, qc)`).

### Query hook convention (enforced by ESLint)

Every hook in `src/hooks/` is a **thin wrapper** around a `queries.*` factory —
the canonical one-liner is `return useQuery(queries.categories())` (see
`src/hooks/useCategories.ts`).

When a hook needs to override one option (e.g. conditional `enabled`), spread the
factory: `useQuery({ ...queries.foo(), enabled: !!arg })`. The lint rule
(`no-restricted-syntax` in `eslint.config.js`) flags inline
`useQuery({ queryKey: ..., queryFn: ... })` — if you hit it, add the missing factory
to `queryConfigs.ts` instead of inlining.

### Mutation hook convention (enforced by ESLint)

Same shape as queries: every `useMutation` is called with `mutations.foo(qc)` or
`{ ...mutations.foo(qc), ...overrides }` — inline `mutationFn` is flagged. The
factory takes `QueryClient` and returns the full option object including the
`onSuccess`/`onSettled` invalidation contract, so simple hooks are 3-line wrappers
(see `useUpdateBudget.ts`). Optimistic, transaction-touching hooks spread the factory
and override only the cache callbacks (`onMutate` snapshot, `onError` rollback,
`onSuccess` toast/undo) while the factory's `onSettled` still owns invalidation — see
`useSoftDelete.ts` for the canonical snapshot/rollback shape.

### Cache invalidation

- Use `queryKeys.*` factories instead of inline `["foo", x]` arrays. The lint
  rule flags inline literal-string arrays in `invalidateQueries`.
- For prefix-style invalidation (invalidate all variants), use
  `queryKeys.prefix("name")`.
- For mutations that change transaction state (delete, restore, ignore, edit
  fields, rename a category, manual-add, statement import), call
  `invalidateTransactionDependents(queryClient)` from `src/lib/queryConfigs.ts`.
  It iterates `TRANSACTION_DEPENDENT_PREFIXES` (also in `queryConfigs.ts`) —
  adding a new transaction-dependent query is a one-place change. New mutation
  factories should call this in `onSettled` rather than reinventing the loop.

### Adding a new endpoint

1. Add the fetch function to `src/lib/api.ts` (real) and `src/lib/demoApi.ts`
   (parallel demo implementation).
2. Add `queryKeys.foo()` and `queries.foo()` factories to
   `src/lib/queryConfigs.ts`. For mutations, add `mutations.foo(qc)` alongside.
3. Add a thin hook wrapper in `src/hooks/useFoo.ts`.
4. If the new query depends on transaction state, add its prefix to
   `TRANSACTION_DEPENDENT_PREFIXES`.

## Components

- Components live at `src/components/<Name>.tsx` (PascalCase). Cross-cutting
  primitives live in `src/components/ui/`.
- Feature-specific composites live in `src/components/<feature>/` (currently
  `settings/`, `insights/`, `merchants/`).
- Page components live in `src/pages/`. **Pull pure data transformations into
  `src/lib/`** — don't let pure functions accumulate inside page modules.
  See `src/lib/statementTransform.ts` for the canonical extraction.

## Visual verification

Assume the frontend and backend dev servers are already running (do not start
them). After ANY frontend or API changes that affect the UI, you MUST verify
visually. Chrome DevTools MCP is the Claude Code path (steps below); any agent
without it satisfies this rule with an ordinary browser — open the page, check
the devtools console, exercise the interaction:

1. Open the affected page in Chrome DevTools (`take_snapshot` or `take_screenshot`)
2. Check `list_console_messages` for errors/warnings — zero tolerance for React errors
3. Test the specific interaction (click buttons, navigate, change month, etc.)
   and confirm expected behavior
4. If the change involves navigation/persistence, navigate away and back to
   confirm state survives

Do NOT skip this step or consider the task complete without visual
verification. This is the "am I building the right thing?" check —
complementary to `make verify` ("did I break anything?"). The fast feedback
loop is `make verify-frontend`; the full gate is `make verify`.

## Type strictness

The frontend runs with `strict`, `noUncheckedIndexedAccess`,
`exactOptionalPropertyTypes`, `noFallthroughCasesInSwitch`,
`noUncheckedSideEffectImports`, `noUnusedLocals`, `noUnusedParameters`. ESLint
extends `tseslint.configs.strict` plus `import/no-cycle`,
`eslint-plugin-react-hooks`, `eslint-plugin-jsx-a11y`,
`eslint-plugin-react-refresh`. New code is expected to pass both gates.
