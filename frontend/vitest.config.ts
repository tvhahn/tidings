import path from "path";
import { configDefaults, defineConfig } from "vitest/config";

// Test files that are pure logic — no DOM, no React rendering, no jsdom-only
// globals (window/document/localStorage/matchMedia) at runtime or import time.
// These run in the lightweight `node` environment, skipping the ~0.7s jsdom
// boot each incurs (see the two `projects` below). Everything else stays on
// jsdom with the shared DOM setup. When in doubt, leave a file OFF this list —
// a wrong entry fails loudly at import, it never silently mis-passes.
const NODE_TEST_FILES = [
  "src/lib/activityGrouping.test.ts",
  "src/lib/apiParity.test.ts",
  "src/lib/attachments.test.ts",
  "src/lib/budgetCalc.test.ts",
  "src/lib/budgetHeat.test.ts",
  "src/lib/cashFlow.test.ts",
  "src/lib/categoryGroups.test.ts",
  "src/lib/categorySuggest.test.ts",
  "src/lib/demoApiGateway.test.ts",
  "src/lib/demoEmails.test.ts",
  "src/lib/filters.test.ts",
  "src/lib/format.test.ts",
  "src/lib/merchantDisplay.test.ts",
  "src/lib/merchantNormalize.test.ts",
  "src/lib/parseFailures.test.ts",
  "src/lib/queryConfigs.test.ts",
  "src/lib/severity.test.ts",
  "src/lib/sort.test.ts",
  "src/lib/statementTransform.test.ts",
  "src/lib/summaryPace.test.ts",
  "src/lib/summaryText.test.ts",
  "src/lib/transactionSearchParams.test.ts",
  "src/stores/editedTransactions.test.ts",
  "src/stores/freshness.test.ts",
  "src/stores/theme.ssr.test.ts",
];

export default defineConfig({
  test: {
    coverage: {
      provider: "v8",
      reporter: ["text", "json-summary"],
      // Without `include`, v8 only reports files that the test suite happens
      // to import — which makes the % look reasonable while hiding ~85
      // untested components and pages. Force the denominator to be the
      // whole app so coverage tells the truth.
      include: ["src/**/*.{ts,tsx}"],
      exclude: [
        "src/**/*.test.{ts,tsx}",
        "src/test/**",
        "src/**/*.d.ts",
        "src/types/**",
        "src/main.tsx",
        "src/main-marketing.tsx",
        "src/marketing/**",
      ],
      // Ratchet: floors on the directories we actually unit-test so their
      // coverage can't silently erode. Pinned just below today's measured
      // levels (stores ~95%, lib ~65%, hooks ~40%). Deliberately no global
      // threshold — components/ and pages/ ride on Playwright e2e, not unit
      // tests, so a global floor would force component tests we don't want.
      // Raise these as coverage climbs; never lower to make a red build green.
      thresholds: {
        "src/stores/**": { statements: 92, branches: 85, functions: 93, lines: 93 },
        "src/lib/**": { statements: 61, branches: 68, functions: 41, lines: 61 },
        "src/hooks/**": { statements: 37, branches: 35, functions: 32, lines: 39 },
      },
    },
    // Two projects split by DOM need. jsdom boot dominates suite wall time, so
    // DOM-free files (NODE_TEST_FILES) run in `node` and skip it. `projects`
    // is the Vitest 4 replacement for the removed `environmentMatchGlobs`.
    projects: [
      {
        extends: true,
        test: {
          name: "node",
          environment: "node",
          include: NODE_TEST_FILES,
        },
      },
      {
        extends: true,
        test: {
          name: "jsdom",
          environment: "jsdom",
          setupFiles: ["src/test/setup.ts"],
          include: ["src/**/*.test.{ts,tsx}"],
          exclude: [...configDefaults.exclude, ...NODE_TEST_FILES],
        },
      },
    ],
  },
  resolve: {
    alias: {
      "@": path.resolve(__dirname, "./src"),
    },
  },
});
