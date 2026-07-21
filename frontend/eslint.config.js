import js from "@eslint/js";
import prettierConfig from "eslint-config-prettier/flat";
import globals from "globals";
import importPlugin from "eslint-plugin-import";
import jsxA11y from "eslint-plugin-jsx-a11y";
import reactHooks from "eslint-plugin-react-hooks";
import reactRefresh from "eslint-plugin-react-refresh";
import tseslint from "typescript-eslint";
import { defineConfig, globalIgnores } from "eslint/config";

export default defineConfig([
  globalIgnores(["dist"]),
  {
    files: ["**/*.{ts,tsx}"],
    extends: [
      js.configs.recommended,
      tseslint.configs.strict,
      reactHooks.configs.flat.recommended,
      reactRefresh.configs.vite,
      importPlugin.flatConfigs.recommended,
      importPlugin.flatConfigs.typescript,
      jsxA11y.flatConfigs.recommended,
      prettierConfig,
    ],
    languageOptions: {
      ecmaVersion: 2020,
      globals: globals.browser,
    },
    settings: {
      "import/resolver": {
        typescript: {
          alwaysTryTypes: true,
          project: "./tsconfig.app.json",
        },
      },
    },
    rules: {
      "import/order": [
        "warn",
        {
          groups: ["builtin", "external", "internal", "parent", "sibling", "index"],
          "newlines-between": "never",
          alphabetize: { order: "asc", caseInsensitive: true },
        },
      ],
      "import/no-cycle": "error",
      "import/no-unresolved": "error",
      // Respect the "_-prefix means intentional unused" convention used
      // throughout the codebase (esp. demoApi.ts stubs matching real signatures).
      "@typescript-eslint/no-unused-vars": [
        "error",
        {
          argsIgnorePattern: "^_",
          varsIgnorePattern: "^_",
          caughtErrorsIgnorePattern: "^_",
          destructuredArrayIgnorePattern: "^_",
        },
      ],
      // React Compiler rule from eslint-plugin-react-hooks v7. Flags common
      // and correct patterns (sync-prop-to-state-on-open, media-query
      // subscriptions, init-from-storage, interval-driven setState). Turn off
      // until we're ready to adopt the React Compiler's preferred alternatives
      // project-wide. The rules-of-hooks / exhaustive-deps / refs / purity
      // checks from the same plugin stay on.
      "react-hooks/set-state-in-effect": "off",
      // Enforce the queryConfigs.ts source-of-truth pattern for cache keys.
      // See docs/specs/_archive/2026-05-04-frontend-refactor-review/ and frontend/CLAUDE.md.
      "no-restricted-syntax": [
        "error",
        {
          // Flag `useQuery({ queryKey: ..., queryFn: ... })` — the inline
          // option-object pattern. The canonical shape is
          // `useQuery(queries.foo(...))`. Spread-and-override
          // (`useQuery({ ...queries.foo(), enabled: x })`) is allowed because
          // the spread carries queryKey through, so this selector won't match.
          selector:
            "CallExpression[callee.name='useQuery'] > ObjectExpression > Property[key.name='queryKey']",
          message:
            "Use queries.* from @/lib/queryConfigs instead of inline useQuery options. See frontend/CLAUDE.md.",
        },
        {
          // Flag `queryClient.prefetchQuery({ queryKey: ..., queryFn: ... })`
          // — the same inline-options smell as useQuery. The canonical shape
          // is `prefetchQuery(queries.foo(...))` (see usePrefetchJournalMonth.ts).
          selector:
            "CallExpression[callee.property.name='prefetchQuery'] > ObjectExpression > Property[key.name='queryKey']",
          message:
            "Use queries.* from @/lib/queryConfigs instead of inline prefetchQuery options. See frontend/CLAUDE.md.",
        },
        {
          // Flag inline literal cache keys in the filter-object methods
          // `invalidateQueries` / `cancelQueries` / `setQueriesData`
          // (`{ queryKey: ["literal", ...] }`). Pass a factory
          // (`queryKeys.foo()` / `queryKeys.prefix(name)`) or a runtime
          // variable (`[prefix]` from a loop) and the rule won't fire.
          selector:
            "CallExpression[callee.property.name=/^(invalidateQueries|cancelQueries|setQueriesData)$/] > ObjectExpression > Property[key.name='queryKey'] > ArrayExpression > Literal:first-child",
          message:
            "Use queryKeys.* factories from @/lib/queryConfigs (or queryKeys.prefix(name)) instead of inline cache keys.",
        },
        {
          // Flag `useMutation({ mutationFn: ..., ... })` — the inline
          // option-object pattern. The canonical shape is
          // `useMutation(mutations.foo(qc))`. Spread-and-override
          // (`useMutation({ ...mutations.foo(qc), onMutate: ... })`) is
          // allowed because the spread carries mutationFn through, so this
          // selector won't match.
          selector:
            "CallExpression[callee.name='useMutation'] > ObjectExpression > Property[key.name='mutationFn']",
          message:
            "Use mutations.* from @/lib/queryConfigs instead of inline useMutation options. See frontend/CLAUDE.md.",
        },
      ],
    },
  },
  {
    // Tests work with known inputs — non-null assertions are ergonomic here.
    files: ["**/*.test.{ts,tsx}"],
    rules: {
      "@typescript-eslint/no-non-null-assertion": "off",
    },
  },
]);
