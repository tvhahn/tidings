import { describe, expect, it } from "vitest";
import type { CategoryGroup, ChartTone } from "@/lib/categoryGroups";
import { makeMonthSummary } from "@/test/factories";
import type { TrendResponse } from "@/types/api";
import { buildGroupRows } from "./CategoryTable";

const groups: CategoryGroup[] = [{ name: "Food", categories: ["groceries"] }];
const tone: ChartTone = { isDark: false, isWarm: false };

function trendMonth(ym: string, groceries: number): TrendResponse["months"][number] {
  return {
    year_month: ym,
    by_category: groceries > 0 ? { groceries: { amount: groceries, count: 1 } } : {},
    total_spending: groceries,
    spending_count: groceries > 0 ? 1 : 0,
  };
}

describe("buildGroupRows — vs avg (L7b)", () => {
  const trend: TrendResponse = {
    months: [
      trendMonth("2026-01", 100),
      trendMonth("2026-02", 200),
      trendMonth("2026-03", 300),
      trendMonth("2026-04", 400),
    ],
  };
  const current = makeMonthSummary({
    year_month: "2026-04",
    by_category: { groceries: { amount: 400, count: 1 } },
    total_spending: 400,
    spending_count: 1,
  });

  it("uses only other complete months — displayed month excluded from the mean", () => {
    const { rows } = buildGroupRows(current, trend, groups, tone, false);
    const food = rows.find((r) => r.name === "Food");
    // mean of Jan/Feb/Mar = 200; Apr (displayed) excluded from the basis
    expect(food?.vsAvg).toBe(200);
    // 400 >= 1.5 × 200 — mirrors the old anomaly rule
    expect(food?.vsAvgDanger).toBe(true);
  });

  it("is null for the current (partial) month", () => {
    const { rows } = buildGroupRows(current, trend, groups, tone, true);
    const food = rows.find((r) => r.name === "Food");
    expect(food?.vsAvg).toBeNull();
    expect(food?.vsAvgDanger).toBe(false);
  });

  it("is null when fewer than 2 other complete months exist", () => {
    const shortTrend: TrendResponse = {
      months: [trendMonth("2026-03", 300), trendMonth("2026-04", 400)],
    };
    const { rows } = buildGroupRows(current, shortTrend, groups, tone, false);
    const food = rows.find((r) => r.name === "Food");
    expect(food?.vsAvg).toBeNull();
  });

  it("stays muted (no danger) below 1.5 × mean", () => {
    const calmCurrent = makeMonthSummary({
      year_month: "2026-04",
      by_category: { groceries: { amount: 250, count: 1 } },
      total_spending: 250,
      spending_count: 1,
    });
    const calmTrend: TrendResponse = {
      months: [
        trendMonth("2026-01", 100),
        trendMonth("2026-02", 200),
        trendMonth("2026-03", 300),
        trendMonth("2026-04", 250),
      ],
    };
    const { rows } = buildGroupRows(calmCurrent, calmTrend, groups, tone, false);
    const food = rows.find((r) => r.name === "Food");
    expect(food?.vsAvg).toBe(50);
    expect(food?.vsAvgDanger).toBe(false);
  });
});

describe("buildGroupRows — zero-spend collapse (L7c)", () => {
  it("filters zero-spend rows out and counts them", () => {
    // Food had history but nothing this month; "misc" lands in Other.
    const trend: TrendResponse = {
      months: [
        trendMonth("2026-02", 100),
        trendMonth("2026-03", 200),
        {
          year_month: "2026-04",
          by_category: { misc: { amount: 50, count: 1 } },
          total_spending: 50,
          spending_count: 1,
        },
      ],
    };
    const current = makeMonthSummary({
      year_month: "2026-04",
      by_category: { misc: { amount: 50, count: 1 } },
      total_spending: 50,
      spending_count: 1,
    });
    const { rows, zeroCount } = buildGroupRows(current, trend, groups, tone, false);
    expect(rows.map((r) => r.name)).toEqual(["Other"]);
    expect(zeroCount).toBe(1);
  });

  it("keeps groups with spending and reports zero collapse count of 0", () => {
    const trend: TrendResponse = {
      months: [trendMonth("2026-03", 200), trendMonth("2026-04", 400)],
    };
    const current = makeMonthSummary({
      year_month: "2026-04",
      by_category: { groceries: { amount: 400, count: 1 } },
      total_spending: 400,
      spending_count: 1,
    });
    const { rows, zeroCount } = buildGroupRows(current, trend, groups, tone, false);
    expect(rows.map((r) => r.name)).toEqual(["Food"]);
    expect(zeroCount).toBe(0);
  });
});
