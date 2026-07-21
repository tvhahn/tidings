import { describe, expect, it } from "vitest";
import type { SummaryComparisonResponse } from "@/types/api";
import { computeCategoryAnomalies, inferMerchantType, topCategoryDeltas } from "./demoAnalytics";

// These tests characterize CURRENT demo behavior (exact numbers), not the
// "ideal" backend math. They lock the observed outputs so future edits to
// demoAnalytics.ts are intentional. See the module header for the Python twins.

type SummarySide = SummaryComparisonResponse["current"];
type CategoryAmountMap = SummarySide["by_category"];

const cs = (amount: number) => ({ amount, count: 0 });

function side(byCategory: Record<string, number>): SummarySide {
  const by_category: Record<string, { amount: number; count: number }> = {};
  for (const [cat, amount] of Object.entries(byCategory)) by_category[cat] = cs(amount);
  return { by_category } as unknown as SummarySide;
}

/** Build the 6 per-month baseline maps for a single category. */
function baselineFor(cat: string, amounts: number[]): CategoryAmountMap[] {
  return amounts.map((a) => ({ [cat]: cs(a) }) as unknown as CategoryAmountMap);
}

function targetFor(cat: string, amount: number): CategoryAmountMap {
  return { [cat]: cs(amount) } as unknown as CategoryAmountMap;
}

describe("topCategoryDeltas", () => {
  it("pins positive/negative deltas, 1-dp pct rounding, and the topN cut", () => {
    const current = side({ groceries: 120, dining: 60, gas: 45 });
    const previous = side({ groceries: 90, dining: 80, gas: 40 });

    const out = topCategoryDeltas(current, previous, 2);

    // gas (|delta| = 5) is dropped by the topN=2 cut; sort is by |delta_amount| desc.
    expect(out).toEqual([
      { category: "groceries", current: 120, previous: 90, delta_amount: 30, delta_pct: 33.3 },
      { category: "dining", current: 60, previous: 80, delta_amount: -20, delta_pct: -25 },
    ]);
  });

  it("returns delta_pct null when the previous amount is zero/absent", () => {
    const out = topCategoryDeltas(side({ newcat: 50 }), side({}));

    expect(out).toEqual([
      { category: "newcat", current: 50, previous: 0, delta_amount: 50, delta_pct: null },
    ]);
  });
});

describe("computeCategoryAnomalies (z-score core)", () => {
  // Baseline [90,110,...] → mean 100, sample stdev sqrt(120) ≈ 10.9545.
  const baseAmounts = [90, 110, 90, 110, 90, 110];

  it("excludes categories with |z| < 1.5", () => {
    // current 110 → dev 10 → z ≈ 0.91.
    const out = computeCategoryAnomalies(
      baselineFor("dining", baseAmounts),
      targetFor("dining", 110)
    );
    expect(out).toEqual([]);
  });

  it("classifies |z| in [1.5, 2) as low", () => {
    // current 120 → dev 20 → z ≈ 1.83.
    const out = computeCategoryAnomalies(
      baselineFor("dining", baseAmounts),
      targetFor("dining", 120)
    );
    expect(out).toEqual([
      {
        category: "dining",
        current: 120,
        baseline: 100,
        severity: "low",
        reason: "roughly 20% above the 6-month average of $100",
        annotated_amount: 0,
      },
    ]);
  });

  it("transitions low→medium: |z| in [2, 3) is medium", () => {
    // current 130 → dev 30 → z ≈ 2.74.
    const out = computeCategoryAnomalies(
      baselineFor("dining", baseAmounts),
      targetFor("dining", 130)
    );
    expect(out).toEqual([
      {
        category: "dining",
        current: 130,
        baseline: 100,
        severity: "medium",
        reason: "roughly 30% above the 6-month average of $100",
        annotated_amount: 0,
      },
    ]);
  });

  it("transitions medium→high: |z| >= 3 is high", () => {
    // current 140 → dev 40 → z ≈ 3.65.
    const out = computeCategoryAnomalies(
      baselineFor("dining", baseAmounts),
      targetFor("dining", 140)
    );
    expect(out).toEqual([
      {
        category: "dining",
        current: 140,
        baseline: 100,
        severity: "high",
        reason: "roughly 40% above the 6-month average of $100",
        annotated_amount: 0,
      },
    ]);
  });

  it("reports 'below' direction for a downward anomaly", () => {
    // current 60 → dev -40 → z ≈ -3.65 → high, below.
    const out = computeCategoryAnomalies(
      baselineFor("dining", baseAmounts),
      targetFor("dining", 60)
    );
    expect(out).toEqual([
      {
        category: "dining",
        current: 60,
        baseline: 100,
        severity: "high",
        reason: "roughly 40% below the 6-month average of $100",
        annotated_amount: 0,
      },
    ]);
  });

  it("skips categories whose baseline stdev is zero", () => {
    // Flat baseline → stdev 0 → skipped despite a huge current value.
    const out = computeCategoryAnomalies(
      baselineFor("rent", [50, 50, 50, 50, 50, 50]),
      targetFor("rent", 500)
    );
    expect(out).toEqual([]);
  });

  it("emits the unexpected-zero anomaly (active every month, current 0) before any z check", () => {
    // Flat active baseline → stdev 0, but the current===0 branch fires first.
    const out = computeCategoryAnomalies(
      baselineFor("gym", [40, 40, 40, 40, 40, 40]),
      targetFor("gym", 0)
    );
    expect(out).toEqual([
      {
        category: "gym",
        current: 0,
        baseline: 40,
        severity: "medium",
        reason: "no activity this month — usually averages $40",
        annotated_amount: 0,
      },
    ]);
  });

  it("orders by severity desc, then by |current - baseline| desc", () => {
    const baseline: CategoryAmountMap[] = baseAmounts.map(
      (a) =>
        ({
          low_cat: cs(a),
          high_cat: cs(a),
          med_cat: cs(a),
        }) as unknown as CategoryAmountMap
    );
    const target = {
      low_cat: cs(120), // z ≈ 1.83 → low
      high_cat: cs(140), // z ≈ 3.65 → high
      med_cat: cs(130), // z ≈ 2.74 → medium
    } as unknown as CategoryAmountMap;

    const out = computeCategoryAnomalies(baseline, target);
    expect(out.map((a) => [a.category, a.severity])).toEqual([
      ["high_cat", "high"],
      ["med_cat", "medium"],
      ["low_cat", "low"],
    ]);
  });
});

describe("inferMerchantType", () => {
  it("returns 'none' when never active", () => {
    expect(inferMerchantType(0, 6, 0.05)).toBe("none");
    expect(inferMerchantType(0, 6, null)).toBe("none");
  });

  it("returns 'lumpy' when active in fewer than all months", () => {
    expect(inferMerchantType(3, 6, 0.05)).toBe("lumpy");
    expect(inferMerchantType(5, 6, null)).toBe("lumpy");
  });

  it("returns 'fixed' when active every month with cv < 0.15", () => {
    expect(inferMerchantType(6, 6, 0.14)).toBe("fixed");
    expect(inferMerchantType(6, 6, 0)).toBe("fixed");
  });

  it("treats cv === 0.15 as the boundary → 'variable' (not fixed)", () => {
    expect(inferMerchantType(6, 6, 0.15)).toBe("variable");
  });

  it("returns 'variable' when active every month with cv >= 0.15 or unknown", () => {
    expect(inferMerchantType(6, 6, 0.3)).toBe("variable");
    expect(inferMerchantType(6, 6, null)).toBe("variable");
  });
});
