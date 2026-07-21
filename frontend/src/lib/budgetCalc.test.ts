import { describe, expect, it } from "vitest";
import type {
  BudgetStatusResponse,
  CategoryPaceDetail,
  HistoricalAveragesResponse,
  HistoricalCategoryAverage,
} from "@/types/api";
import {
  buildAvgMap,
  buildPrefillEntries,
  buildSpendingMap,
  buildSuggestedMap,
  computeGroupSubtotals,
  forecastOverBudget,
  forecastRangeLabel,
  groupEntries,
  projectedOverallYtdPct,
  projectedYtdPct,
  recalculateEntry,
  type CategoryFormEntry,
} from "./budgetCalc";

function makeEntry(overrides: Partial<CategoryFormEntry> = {}): CategoryFormEntry {
  return {
    key: "groceries",
    target: 6000,
    inputMode: "monthly",
    categoryType: "variable",
    displayAmount: "500",
    ...overrides,
  };
}

describe("recalculateEntry", () => {
  describe("inputMode switch", () => {
    it("switching monthly → yearly sets displayAmount to annual target", () => {
      const entry = makeEntry({ target: 6000, inputMode: "monthly", displayAmount: "500" });
      const result = recalculateEntry(entry, { inputMode: "yearly" });
      expect(result.inputMode).toBe("yearly");
      expect(result.displayAmount).toBe("6000");
    });

    it("switching yearly → monthly sets displayAmount to target/12", () => {
      const entry = makeEntry({ target: 6000, inputMode: "yearly", displayAmount: "6000" });
      const result = recalculateEntry(entry, { inputMode: "monthly" });
      expect(result.inputMode).toBe("monthly");
      expect(result.displayAmount).toBe("500");
    });

    it("switching yearly → monthly rounds to 2 decimal places", () => {
      const entry = makeEntry({ target: 1000, inputMode: "yearly", displayAmount: "1000" });
      const result = recalculateEntry(entry, { inputMode: "monthly" });
      // 1000/12 = 83.333... → rounds to 83.33
      expect(result.displayAmount).toBe("83.33");
    });

    it("no-op if inputMode is same as current", () => {
      const entry = makeEntry({ target: 6000, inputMode: "monthly", displayAmount: "500" });
      const result = recalculateEntry(entry, { inputMode: "monthly" });
      expect(result.displayAmount).toBe("500");
      expect(result.target).toBe(6000);
    });
  });

  describe("displayAmount change", () => {
    it("monthly: target = displayAmount * 12", () => {
      const entry = makeEntry({ inputMode: "monthly" });
      const result = recalculateEntry(entry, { displayAmount: "100" });
      expect(result.target).toBe(1200);
    });

    it("yearly: target = displayAmount", () => {
      const entry = makeEntry({ inputMode: "yearly" });
      const result = recalculateEntry(entry, { displayAmount: "2400" });
      expect(result.target).toBe(2400);
    });

    it("empty displayAmount treated as zero", () => {
      const entry = makeEntry({ inputMode: "monthly" });
      const result = recalculateEntry(entry, { displayAmount: "" });
      expect(result.target).toBe(0);
    });

    it("non-numeric displayAmount treated as zero", () => {
      const entry = makeEntry({ inputMode: "monthly" });
      const result = recalculateEntry(entry, { displayAmount: "abc" });
      expect(result.target).toBe(0);
    });

    it("handles decimal amounts", () => {
      const entry = makeEntry({ inputMode: "monthly" });
      const result = recalculateEntry(entry, { displayAmount: "99.50" });
      expect(result.target).toBe(1194);
    });
  });

  describe("other field changes", () => {
    it("changing categoryType preserves target and displayAmount", () => {
      const entry = makeEntry({ target: 6000, displayAmount: "500" });
      const result = recalculateEntry(entry, { categoryType: "fixed" });
      expect(result.categoryType).toBe("fixed");
      expect(result.target).toBe(6000);
      expect(result.displayAmount).toBe("500");
    });
  });

  describe("edge cases", () => {
    it("zero target switching to monthly", () => {
      const entry = makeEntry({ target: 0, inputMode: "yearly", displayAmount: "0" });
      const result = recalculateEntry(entry, { inputMode: "monthly" });
      expect(result.displayAmount).toBe("0");
    });

    it("displayAmount of zero in monthly mode", () => {
      const entry = makeEntry({ inputMode: "monthly" });
      const result = recalculateEntry(entry, { displayAmount: "0" });
      expect(result.target).toBe(0);
    });
  });
});

function makeCat(overrides: Partial<CategoryPaceDetail> = {}): CategoryPaceDetail {
  return {
    category: "groceries",
    target: 6000,
    input_mode: "monthly",
    monthly_amount: 500,
    category_type: "variable",
    current_month_spent: 300,
    current_month_expected: 250,
    ytd_spent: 2800,
    ytd_expected: 2700,
    variance: -50,
    pace_percent: 120,
    status: "over",
    monthly_spent: Array(12).fill(0),
    prior_year_total: null,
    forecast_month_total: 550,
    forecast_lower: 480,
    forecast_upper: 620,
    forecast_pct: 110,
    forecast_quality: "forecast",
    ...overrides,
  };
}

function makeStatus(overrides: Partial<BudgetStatusResponse> = {}): BudgetStatusResponse {
  const cat = makeCat();
  return {
    year: 2026,
    as_of: "2026-06-10",
    elapsed_year_fraction: 0.44,
    overall: {
      spending_ceiling: 50000,
      ytd_spent: 20000,
      expected_pace: 22000,
      variance: 2000,
      status: "under",
      headline: "$2,000 ahead of pace",
      projected_month_total: 4100,
      projected_month_status: "under",
    },
    groups: [
      {
        name: "Food",
        budgeted_total: 6000,
        ytd_spent: 2800,
        expected_pace: 2640,
        variance: -160,
        status: "over",
        categories: [cat],
        monthly_totals: Array(12).fill(0),
        prior_year_total: null,
      },
    ],
    unbudgeted: [],
    monthly_totals: Array(12).fill(0),
    prior_year_total: null,
    compare_year: null,
    ...overrides,
  };
}

describe("projectedYtdPct", () => {
  it("replaces the current month with its projection", () => {
    // (2800 - 300 + 550) / 6000 = 50.83%
    expect(projectedYtdPct(makeCat())).toBeCloseTo(50.833, 2);
  });

  it("returns null without a forecast", () => {
    expect(projectedYtdPct(makeCat({ forecast_month_total: null }))).toBeNull();
  });

  it("returns null with a zero target", () => {
    expect(projectedYtdPct(makeCat({ target: 0 }))).toBeNull();
  });
});

describe("projectedOverallYtdPct", () => {
  it("replaces the non-lumpy basket's current month with the projection", () => {
    // (20000 - 300 + 4100) / 50000 = 47.6%
    expect(projectedOverallYtdPct(makeStatus())).toBeCloseTo(47.6, 2);
  });

  it("excludes lumpy categories from the replaced basket", () => {
    const status = makeStatus();
    status.groups[0]!.categories.push(
      makeCat({
        category: "travel",
        category_type: "lumpy",
        current_month_spent: 1000,
        forecast_month_total: null,
      })
    );
    expect(projectedOverallYtdPct(status)).toBeCloseTo(47.6, 2);
  });

  it("returns null without an overall projection", () => {
    const status = makeStatus();
    status.overall.projected_month_total = null;
    expect(projectedOverallYtdPct(status)).toBeNull();
  });

  it("returns null with a zero ceiling", () => {
    const status = makeStatus();
    status.overall.spending_ceiling = 0;
    expect(projectedOverallYtdPct(status)).toBeNull();
  });
});

describe("forecastOverBudget", () => {
  it("true when projected past the monthly budget", () => {
    expect(forecastOverBudget(makeCat({ forecast_month_total: 550, monthly_amount: 500 }))).toBe(
      true
    );
  });

  it("false when within budget", () => {
    expect(forecastOverBudget(makeCat({ forecast_month_total: 450, monthly_amount: 500 }))).toBe(
      false
    );
  });

  it("false without a monthly budget", () => {
    expect(forecastOverBudget(makeCat({ monthly_amount: 0 }))).toBe(false);
  });
});

describe("forecastRangeLabel", () => {
  it("formats the range", () => {
    expect(forecastRangeLabel(makeCat())).toBe("Expected range $480–$620");
  });

  it("null without bounds", () => {
    expect(forecastRangeLabel(makeCat({ forecast_lower: null, forecast_upper: null }))).toBeNull();
  });

  it("null for a degenerate range", () => {
    expect(forecastRangeLabel(makeCat({ forecast_lower: 550, forecast_upper: 550 }))).toBeNull();
  });
});

function makeHistCat(
  overrides: Partial<HistoricalCategoryAverage> = {}
): HistoricalCategoryAverage {
  return {
    monthly_avg: 100,
    months_active: 6,
    suggested_annual: 1200,
    suggested_monthly: 100,
    suggested_type: "variable",
    total: 600,
    ...overrides,
  };
}

function makeHist(
  categories: Record<string, HistoricalCategoryAverage>
): HistoricalAveragesResponse {
  return { categories, months_analyzed: 12, period: {} };
}

// Reproduces the pre-extraction inline logic from BudgetEditPage verbatim, so
// the extracted helper can be asserted byte-for-byte against the old behavior.
function legacyBuildPrefill(hist: HistoricalAveragesResponse): {
  entries: CategoryFormEntry[];
  ceiling: string;
} {
  const cats = hist.categories;
  const newEntries: CategoryFormEntry[] = Object.entries(cats)
    .filter(([, info]) => info.months_active >= 3)
    .map(([key, info]) => ({
      key,
      target: info.suggested_annual,
      inputMode: "monthly" as const,
      categoryType: info.suggested_type as "fixed" | "variable" | "lumpy",
      displayAmount: String(info.suggested_monthly),
    }));
  const totalAnnual = newEntries.reduce((s, e) => s + e.target, 0);
  return { entries: newEntries, ceiling: String(Math.round(totalAnnual / 1000) * 1000) };
}

describe("buildPrefillEntries", () => {
  it("keeps only categories with months_active >= 3 (boundary at exactly 3)", () => {
    const hist = makeHist({
      groceries: makeHistCat({ months_active: 3, suggested_annual: 6000, suggested_monthly: 500 }),
      travel: makeHistCat({ months_active: 2, suggested_annual: 2400, suggested_monthly: 200 }),
      rent: makeHistCat({ months_active: 12, suggested_annual: 24000, suggested_monthly: 2000 }),
    });
    const { entries } = buildPrefillEntries(hist);
    expect(entries.map((e) => e.key)).toEqual(["groceries", "rent"]);
  });

  it("maps entry fields and preserves object insertion order", () => {
    const hist = makeHist({
      groceries: makeHistCat({
        suggested_annual: 6000,
        suggested_monthly: 500,
        suggested_type: "fixed",
        months_active: 5,
      }),
    });
    const { entries } = buildPrefillEntries(hist);
    expect(entries).toEqual([
      {
        key: "groceries",
        target: 6000,
        inputMode: "monthly",
        categoryType: "fixed",
        displayAmount: "500",
      },
    ]);
  });

  it("rounds the ceiling to the nearest $1000", () => {
    const hist = makeHist({
      a: makeHistCat({ months_active: 6, suggested_annual: 6400 }),
      b: makeHistCat({ months_active: 6, suggested_annual: 1800 }),
    });
    // total 8200 → round(8.2) * 1000 = 8000
    expect(buildPrefillEntries(hist).ceiling).toBe("8000");
  });

  it("rounds a .5 fraction upward (12500 → 13000)", () => {
    const hist = makeHist({ a: makeHistCat({ months_active: 6, suggested_annual: 12500 }) });
    expect(buildPrefillEntries(hist).ceiling).toBe("13000");
  });

  it("empty history yields no entries and a zero ceiling", () => {
    const { entries, ceiling } = buildPrefillEntries(makeHist({}));
    expect(entries).toEqual([]);
    expect(ceiling).toBe("0");
  });

  it("matches the legacy inline computation byte-for-byte", () => {
    const hist = makeHist({
      groceries: makeHistCat({ months_active: 4, suggested_annual: 6000, suggested_monthly: 500 }),
      travel: makeHistCat({ months_active: 2, suggested_annual: 2400, suggested_monthly: 200 }),
      rent: makeHistCat({
        months_active: 12,
        suggested_annual: 24300,
        suggested_monthly: 2025,
        suggested_type: "fixed",
      }),
    });
    expect(buildPrefillEntries(hist)).toEqual(legacyBuildPrefill(hist));
  });
});

describe("buildAvgMap", () => {
  it("flattens categories to monthly_avg", () => {
    const hist = makeHist({
      groceries: makeHistCat({ monthly_avg: 480 }),
      rent: makeHistCat({ monthly_avg: 2000 }),
    });
    expect(buildAvgMap(hist)).toEqual({ groceries: 480, rent: 2000 });
  });

  it("returns an empty map for undefined input", () => {
    expect(buildAvgMap(undefined)).toEqual({});
  });
});

describe("buildSuggestedMap", () => {
  it("flattens categories to suggested monthly/type", () => {
    const hist = makeHist({
      groceries: makeHistCat({ suggested_monthly: 500, suggested_type: "variable" }),
    });
    expect(buildSuggestedMap(hist)).toEqual({
      groceries: { suggestedMonthly: 500, suggestedType: "variable" },
    });
  });

  it("returns an empty map for undefined input", () => {
    expect(buildSuggestedMap(undefined)).toEqual({});
  });
});

describe("buildSpendingMap", () => {
  it("indexes budgeted and unbudgeted categories by key", () => {
    const status = makeStatus();
    status.unbudgeted = [
      { category: "gifts", current_month_spent: 40, monthly_avg_historical: 12, ytd_spent: 90 },
    ];
    const map = buildSpendingMap(status);
    expect(map.groceries).toEqual({ currentMonth: 300, ytd: 2800 });
    expect(map.gifts).toEqual({ currentMonth: 40, ytd: 90 });
  });

  it("returns an empty map for undefined input", () => {
    expect(buildSpendingMap(undefined)).toEqual({});
  });
});

describe("groupEntries", () => {
  function entry(key: string): CategoryFormEntry {
    return makeEntry({ key });
  }

  it("orders entries by group category order and drops empty groups", () => {
    const entries = [entry("rent"), entry("groceries"), entry("dining")];
    const groups = [
      { name: "Food", categories: ["groceries", "dining"] },
      { name: "Housing", categories: ["rent"] },
      { name: "Empty", categories: ["nonexistent"] },
    ];
    const result = groupEntries(entries, groups);
    expect(result.map((g) => g.name)).toEqual(["Food", "Housing"]);
    expect(result[0]!.entries.map((e) => e.key)).toEqual(["groceries", "dining"]);
    expect(result[1]!.entries.map((e) => e.key)).toEqual(["rent"]);
  });

  it("collects unclaimed entries into a trailing 'Other' group in original order", () => {
    const entries = [entry("groceries"), entry("mystery"), entry("other2")];
    const groups = [{ name: "Food", categories: ["groceries"] }];
    const result = groupEntries(entries, groups);
    expect(result.map((g) => g.name)).toEqual(["Food", "Other"]);
    expect(result[1]!.entries.map((e) => e.key)).toEqual(["mystery", "other2"]);
  });

  it("omits the 'Other' group when every entry is claimed", () => {
    const entries = [entry("groceries")];
    const groups = [{ name: "Food", categories: ["groceries"] }];
    expect(groupEntries(entries, groups).map((g) => g.name)).toEqual(["Food"]);
  });

  it("returns no groups for empty entries", () => {
    expect(groupEntries([], [{ name: "Food", categories: ["groceries"] }])).toEqual([]);
  });
});

describe("computeGroupSubtotals", () => {
  it("sums averages, spend, monthly (annual/12 to cents), and annual", () => {
    const entries = [
      makeEntry({ key: "groceries", target: 6000 }),
      makeEntry({ key: "rent", target: 1000 }),
    ];
    const avg3Map = { groceries: 480 };
    const avg12Map = { groceries: 500, rent: 90 };
    const spendingMap = { groceries: { currentMonth: 300, ytd: 2800 } };
    const sub = computeGroupSubtotals(entries, avg3Map, avg12Map, spendingMap);
    expect(sub.avg3).toBe(480); // rent missing → 0
    expect(sub.avg12).toBe(590);
    expect(sub.currentMonth).toBe(300);
    expect(sub.ytd).toBe(2800);
    // 6000/12 = 500 ; 1000/12 = 83.33 → 583.33
    expect(sub.monthly).toBeCloseTo(583.33, 2);
    expect(sub.annual).toBe(7000);
  });

  it("is all zeros for no entries", () => {
    expect(computeGroupSubtotals([], {}, {}, {})).toEqual({
      avg3: 0,
      avg12: 0,
      currentMonth: 0,
      ytd: 0,
      monthly: 0,
      annual: 0,
    });
  });
});
