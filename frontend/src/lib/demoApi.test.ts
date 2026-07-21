// @vitest-environment jsdom
import { describe, expect, it, beforeEach, vi, afterEach } from "vitest";
import { makeTxn } from "@/test/factories";

// Stub fetch for fixture loads before importing demoApi
const originalFetch = globalThis.fetch;

type FixtureMap = Record<string, unknown>;
const fixtures: FixtureMap = {
  "/demo-data/config.json": {
    storage: "sqlite",
    demo_mode: true,
    user_id: "default",
    daily_summary_provider: "disabled",
    insights_provider: "disabled",
    categorization_provider: "disabled",
    document_parsing_provider: "disabled",
  },
  "/demo-data/categories.json": { categories: ["Groceries", "Rent"] },
  "/demo-data/transactions-2026-03.json": {
    month: "2026-03",
    count: 2,
    transactions: [
      makeTxn({
        forwarded_to: "u@x.com",
        date_file_name: "f1",
        date: "2026-03-14",
        amount: 10,
        company: "Shop",
        category: "Misc",
        institution: null,
        transaction_type: null,
        name: null,
      }),
      makeTxn({
        forwarded_to: "u@x.com",
        date_file_name: "f2",
        date: "2026-03-15",
        amount: 20,
        company: "Other",
        category: "Food",
        institution: null,
        transaction_type: null,
        name: null,
      }),
    ],
  },
  "/demo-data/trash-2026-03.json": {
    month: "2026-03",
    count: 0,
    transactions: [],
  },
  "/demo-data/budget-config-2026.json": {
    year: 2026,
    spending_ceiling: 50000,
    categories: {
      Groceries: {
        target: 500,
        input_mode: "monthly",
        monthly_amount: 500,
        category_type: "variable",
      },
    },
    groups: [],
    targets_version: 1,
    groups_version: 1,
    allocated_total: 6000,
    unallocated: 44000,
  },
  "/demo-data/overrides.json": {
    overrides: [
      { company: "Amazon Prime", category: "subscriptions" },
      { company: "Netflix", category: "subscriptions" },
    ],
    count: 2,
    version: 1,
  },
  "/demo-data/overrides-suggestions.json": {
    suggestions: [
      {
        company: "Sq *Northwind Cafe",
        suggested_category: "restaurant/dining",
        correction_count: 3,
        last_corrected: "2026-03-10T00:00:00Z",
      },
      {
        company: "Etsy",
        suggested_category: "household items",
        correction_count: 2,
        last_corrected: "2026-02-12T00:00:00Z",
      },
    ],
    count: 2,
  },
};

beforeEach(() => {
  sessionStorage.clear();
  globalThis.fetch = vi.fn(async (input: RequestInfo | URL) => {
    const url = typeof input === "string" ? input : input.toString();
    if (url in fixtures) {
      return new Response(JSON.stringify(fixtures[url]), { status: 200 });
    }
    return new Response("", { status: 404 });
  }) as typeof fetch;
});

afterEach(() => {
  globalThis.fetch = originalFetch;
});

// Must import demoApi AFTER the mock is staged so its module-level imports resolve cleanly
const importDemo = () => import("./demoApi");

describe("demoApi reads", () => {
  it("fetchConfig returns fixture", async () => {
    const { fetchConfig } = await importDemo();
    const cfg = await fetchConfig();
    expect(cfg.demo_mode).toBe(true);
  });

  it("fetchTransactions applies category overlay", async () => {
    const { fetchTransactions, updateCategory } = await importDemo();
    await updateCategory("u@x.com", "f1", "Groceries");
    const res = await fetchTransactions("2026-03");
    expect(res.transactions.find((t) => t.date_file_name === "f1")?.category).toBe("Groceries");
    expect(res.transactions.find((t) => t.date_file_name === "f2")?.category).toBe("Food");
  });

  it("fetchBudgetConfig applies budget overlay", async () => {
    const { fetchBudgetConfig, updateBudgetConfig } = await importDemo();
    await updateBudgetConfig(2026, {
      spending_ceiling: 70000,
      categories: { Groceries: { target: 600, input_mode: "monthly", category_type: "variable" } },
      groups: [],
      targets_version: 1,
      groups_version: 1,
    });
    const cfg = await fetchBudgetConfig(2026);
    expect(cfg?.spending_ceiling).toBe(70000);
    expect(cfg?.categories.Groceries!.target).toBe(600);
  });

  it("fetchCategories returns fixture list", async () => {
    const { fetchCategories } = await importDemo();
    const res = await fetchCategories();
    expect(res.categories).toEqual(["Groceries", "Rent"]);
  });

  it("fetchAllTransactions prefers the standalone attention fixture over all-{month}.json's stale slice", async () => {
    const { fetchAllTransactions } = await importDemo();
    // all-2026-03.json carries an empty attention slice; attention-2026-03.json
    // has two items. Arrange the two fixtures inline, then verify the standalone
    // fixture wins.
    (globalThis.fetch as ReturnType<typeof vi.fn>).mockImplementation(async (input) => {
      const url = typeof input === "string" ? input : input.toString();
      if (url === "/demo-data/all-2026-03.json") {
        return new Response(
          JSON.stringify({
            month: "2026-03",
            transactions: { month: "2026-03", count: 0, transactions: [] },
            attention: { month: "2026-03", count: 0, transactions: [] },
            trash: { month: "2026-03", count: 0, transactions: [] },
          }),
          { status: 200 }
        );
      }
      if (url === "/demo-data/attention-2026-03.json") {
        return new Response(
          JSON.stringify({
            month: "2026-03",
            count: 2,
            transactions: [
              makeTxn({
                forwarded_to: "u@x.com",
                date_file_name: "attn-a",
                date: "2026-03-10",
                amount: 5,
                company: "Misc Co",
                category: "miscellaneous",
                institution: null,
                transaction_type: null,
                name: null,
              }),
              makeTxn({
                forwarded_to: "u@x.com",
                date_file_name: "attn-b",
                date: "2026-03-12",
                amount: 9,
                company: "Other Co",
                category: "miscellaneous",
                institution: null,
                transaction_type: null,
                name: null,
              }),
            ],
          }),
          { status: 200 }
        );
      }
      return new Response("", { status: 404 });
    });
    const res = await fetchAllTransactions("2026-03");
    expect(res.attention.count).toBe(2);
    expect(res.attention.transactions.map((t) => t.date_file_name).sort()).toEqual([
      "attn-a",
      "attn-b",
    ]);
  });
});

describe("demoApi mutations allowlist", () => {
  it("updateCategory persists to overlay", async () => {
    const { updateCategory, fetchTransactions } = await importDemo();
    const res = await updateCategory("u@x.com", "f2", "Dining");
    expect(res.new_category).toBe("Dining");
    const list = await fetchTransactions("2026-03");
    expect(list.transactions.find((t) => t.date_file_name === "f2")?.category).toBe("Dining");
  });

  it("updateBudgetConfig returns optimistic typed response", async () => {
    const { updateBudgetConfig } = await importDemo();
    const res = await updateBudgetConfig(2026, {
      spending_ceiling: 80000,
      categories: {
        Groceries: { target: 7200, input_mode: "yearly", category_type: "variable" },
      },
      groups: [],
      targets_version: 1,
      groups_version: 1,
    });
    expect(res.year).toBe(2026);
    expect(res.spending_ceiling).toBe(80000);
    expect(res.categories.Groceries!.monthly_amount).toBeCloseTo(600);
  });

  // Every demoApi export that should be rejected in demo mode. Adding a new
  // throwing mutation without appending it here (or removing one without pruning)
  // means the allowlist policy has silently drifted.
  const THROWING_MUTATIONS: [name: string, callArgs: readonly unknown[]][] = [
    ["updateConfig", [{}]],
    ["uploadEml", [new File([], "x.eml")]],
    ["updateTransactionFields", ["u@x.com", "f1", { company: "x" }]],
    ["generateJournalSummaries", ["2026-03", ["2026-03-01"]]],
    ["testOpenAiConnection", ["sk-test"]],
    ["updateGroups", [2026, { groups: [], groups_version: 1 }]],
    ["consolidateOverrides", [{ overrides: [] }]],
    ["addCategory", ["New", null]],
    ["renameCategory", ["Old", "New"]],
    ["deleteCategory", ["Groceries"]],
    ["updateCategoryGroup", ["Groceries", "Food & Dining"]],
    ["uploadStatement", [new File([], "s.pdf")]],
    ["importStatementTransactions", [{ statement_id: "s1", transactions: [] }]],
    ["fetchStatement", ["s1"]],
    ["deleteStatement", ["s1"]],
    ["updateTransactionAction", ["s1", 0, { action: "import" }]],
    ["reparseStatement", ["s1"]],
    ["generateInsights", ["2026-03"]],
    ["putMerchantAlias", ["raw", "canonical"]],
    ["deleteMerchantAlias", ["raw"]],
    ["setCategoryIcon", ["Groceries", "ShoppingCart"]],
    ["clearCategoryIcon", ["Groceries"]],
  ];

  describe.each(THROWING_MUTATIONS)("%s throws DemoModeError", (name, args) => {
    it("rejects in demo mode", async () => {
      const mod = (await importDemo()) as unknown as Record<string, (...a: unknown[]) => unknown>;
      const fn = mod[name];
      expect(fn, `export "${name}" missing from demoApi`).toBeTypeOf("function");
      expect(() => fn!(...args)).toThrow(/demo/i);
    });
  });
});

describe("demoApi tx-state overlay", () => {
  it("markReviewed sets category_audit and hides from attention", async () => {
    const { markReviewed, fetchAttentionQueue } = await importDemo();
    // Prime a fresh attention fixture via a one-off route mock
    (globalThis.fetch as ReturnType<typeof vi.fn>).mockImplementationOnce(
      async () =>
        new Response(
          JSON.stringify({
            month: "2026-03",
            count: 1,
            transactions: [
              makeTxn({
                forwarded_to: "u@x.com",
                date_file_name: "f1",
                date: "2026-03-14",
                amount: 10,
                company: "Shop",
                category: "miscellaneous",
                institution: null,
                transaction_type: null,
                name: null,
              }),
            ],
          }),
          { status: 200 }
        )
    );
    await markReviewed("u@x.com", "f1");
    const after = await fetchAttentionQueue("2026-03");
    expect(after.count).toBe(0);
  });

  it("setIgnored persists and round-trips via fetchTransactions", async () => {
    const { setIgnored, fetchTransactions } = await importDemo();
    await setIgnored("u@x.com", "f1", true);
    const list = await fetchTransactions("2026-03");
    expect(list.transactions.find((t) => t.date_file_name === "f1")?.ignored).toBe(true);
  });

  it("setComment persists and round-trips", async () => {
    const { setComment, fetchTransactions } = await importDemo();
    await setComment("u@x.com", "f1", "hello");
    const list = await fetchTransactions("2026-03");
    expect(list.transactions.find((t) => t.date_file_name === "f1")?.comment).toBe("hello");
  });

  it("softDeleteTransaction moves item from list to trash; restore moves back", async () => {
    const { softDeleteTransaction, fetchTransactions, fetchTrash } = await importDemo();
    await softDeleteTransaction("u@x.com", "f1", true);
    const active = await fetchTransactions("2026-03");
    expect(active.transactions.some((t) => t.date_file_name === "f1")).toBe(false);
    const trash = await fetchTrash("2026-03");
    expect(trash.transactions.some((t) => t.date_file_name === "f1")).toBe(true);
    await softDeleteTransaction("u@x.com", "f1", false);
    const after = await fetchTransactions("2026-03");
    expect(after.transactions.some((t) => t.date_file_name === "f1")).toBe(true);
  });

  it("permanentlyDeleteTransaction tombstones: invisible in both active and trash", async () => {
    const { softDeleteTransaction, permanentlyDeleteTransaction, fetchTransactions, fetchTrash } =
      await importDemo();
    await softDeleteTransaction("u@x.com", "f2", true);
    await permanentlyDeleteTransaction("u@x.com", "f2");
    const active = await fetchTransactions("2026-03");
    const trash = await fetchTrash("2026-03");
    expect(active.transactions.some((t) => t.date_file_name === "f2")).toBe(false);
    expect(trash.transactions.some((t) => t.date_file_name === "f2")).toBe(false);
  });
});

describe("demoApi override overlay", () => {
  it("putOverride adds a new rule", async () => {
    const { putOverride, fetchOverrides } = await importDemo();
    await putOverride("Starbucks", "restaurant/dining");
    const list = await fetchOverrides();
    expect(list.overrides.some((o) => o.company === "Starbucks")).toBe(true);
    expect(list.overrides.find((o) => o.company === "Starbucks")?.category).toBe(
      "restaurant/dining"
    );
  });

  it("putOverride updates an existing rule's category", async () => {
    const { putOverride, fetchOverrides } = await importDemo();
    await putOverride("Netflix", "entertainment");
    const list = await fetchOverrides();
    expect(list.overrides.find((o) => o.company === "Netflix")?.category).toBe("entertainment");
  });

  it("deleteOverride removes a baseline rule", async () => {
    const { deleteOverride, fetchOverrides } = await importDemo();
    await deleteOverride("Amazon Prime");
    const list = await fetchOverrides();
    expect(list.overrides.some((o) => o.company === "Amazon Prime")).toBe(false);
  });

  it("dismissSuggestion removes it from fetchOverrideSuggestions", async () => {
    const { dismissSuggestion, fetchOverrideSuggestions } = await importDemo();
    await dismissSuggestion("Sq *Northwind Cafe", "restaurant/dining");
    const res = await fetchOverrideSuggestions();
    expect(res.suggestions.some((s) => s.company === "Sq *Northwind Cafe")).toBe(false);
    expect(res.suggestions.some((s) => s.company === "Etsy")).toBe(true);
  });
});

describe("demoApi searchTransactions", () => {
  // Regression: matchesSearch compared the raw "MM/DD/YYYY HH:MM TZ" date string
  // against "YYYY-MM" from/to bounds, so every transaction was lexically filtered
  // out ("03/..." < "2025-07") and search always returned zero rows.
  it("matches transactions whose real-format date falls inside the YYYY-MM range", async () => {
    (globalThis.fetch as ReturnType<typeof vi.fn>).mockImplementation(async (input) => {
      const url = typeof input === "string" ? input : input.toString();
      if (url === "/demo-data/transactions-2026-03.json") {
        return new Response(
          JSON.stringify({
            month: "2026-03",
            count: 2,
            transactions: [
              makeTxn({
                forwarded_to: "u@x.com",
                date_file_name: "s1",
                date: "03/14/2026 22:12 PST",
                amount: 10,
                company: "Shop",
                category: "Misc",
              }),
              makeTxn({
                forwarded_to: "u@x.com",
                date_file_name: "s2",
                date: "03/19/2026 08:00 PST",
                amount: 20,
                company: "Other",
                category: "Food",
              }),
            ],
          }),
          { status: 200 }
        );
      }
      return new Response("", { status: 404 });
    });

    const { searchTransactions } = await importDemo();
    const res = await searchTransactions({
      from: "2026-03",
      to: "2026-03",
    } as Parameters<typeof searchTransactions>[0]);

    expect(res.summary.total_count).toBe(2);
    expect(res.summary.total_amount).toBeCloseTo(30);
    expect(res.transactions.map((t) => t.date_file_name).sort()).toEqual(["s1", "s2"]);
  });

  it("excludes transactions whose month is outside the range", async () => {
    (globalThis.fetch as ReturnType<typeof vi.fn>).mockImplementation(async (input) => {
      const url = typeof input === "string" ? input : input.toString();
      if (url === "/demo-data/transactions-2026-03.json") {
        return new Response(
          JSON.stringify({
            month: "2026-03",
            count: 1,
            transactions: [
              makeTxn({
                forwarded_to: "u@x.com",
                date_file_name: "s1",
                date: "03/14/2026 22:12 PST",
                amount: 10,
              }),
            ],
          }),
          { status: 200 }
        );
      }
      return new Response("", { status: 404 });
    });

    const { searchTransactions } = await importDemo();
    // Window is a later month with no fixture; nothing should match.
    const res = await searchTransactions({
      from: "2026-05",
      to: "2026-05",
    } as Parameters<typeof searchTransactions>[0]);

    expect(res.summary.total_count).toBe(0);
  });

  it("honors q across company OR comment OR category (mirrors backend)", async () => {
    (globalThis.fetch as ReturnType<typeof vi.fn>).mockImplementation(async (input) => {
      const url = typeof input === "string" ? input : input.toString();
      if (url === "/demo-data/transactions-2026-03.json") {
        return new Response(
          JSON.stringify({
            month: "2026-03",
            count: 3,
            transactions: [
              makeTxn({
                forwarded_to: "u@x.com",
                date_file_name: "byCompany",
                date: "03/14/2026 22:12 PST",
                amount: 10,
                company: "Loblaws",
                comment: "weekly run",
                category: "groceries",
              }),
              makeTxn({
                forwarded_to: "u@x.com",
                date_file_name: "byComment",
                date: "03/15/2026 09:00 PST",
                amount: 20,
                company: "Shell",
                comment: "birthday dinner",
                category: "gasoline",
              }),
              makeTxn({
                forwarded_to: "u@x.com",
                date_file_name: "byCategory",
                date: "03/16/2026 12:00 PST",
                amount: 30,
                company: "Sushi Place",
                comment: "lunch",
                category: "restaurant/dining",
              }),
            ],
          }),
          { status: 200 }
        );
      }
      return new Response("", { status: 404 });
    });

    const { searchTransactions } = await importDemo();

    // Matches on comment: only the "birthday dinner" row.
    const byComment = await searchTransactions({
      from: "2026-03",
      to: "2026-03",
      q: "birthday",
    } as Parameters<typeof searchTransactions>[0]);
    expect(byComment.transactions.map((t) => t.date_file_name)).toEqual(["byComment"]);

    // Matches on category: only the "restaurant/dining" row.
    const byCategory = await searchTransactions({
      from: "2026-03",
      to: "2026-03",
      q: "restaurant",
    } as Parameters<typeof searchTransactions>[0]);
    expect(byCategory.transactions.map((t) => t.date_file_name)).toEqual(["byCategory"]);

    // A needle matching none of the three fields returns nothing.
    const none = await searchTransactions({
      from: "2026-03",
      to: "2026-03",
      q: "airfare",
    } as Parameters<typeof searchTransactions>[0]);
    expect(none.summary.total_count).toBe(0);
  });
});
