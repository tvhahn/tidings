import { describe, expect, it } from "vitest";
import type { MonthSummary } from "@/types/api";
import { buildCashFlowGraph } from "./cashFlow";
import { DEFAULT_CATEGORY_GROUPS } from "./categoryGroups";

function makeSummary(overrides: Partial<MonthSummary> = {}): MonthSummary {
  return {
    year_month: "2026-02",
    total_spending: 0,
    spending_count: 0,
    deposit_total: 0,
    deposit_count: 0,
    by_category: {},
    by_company: {},
    deposits_by_company: {},
    top_categories: [],
    ...overrides,
  };
}

const HUB_ID = "__hub__";
const SAVINGS_ID = "__savings__";
const DRAWDOWN_ID = "__drawdown__";

describe("buildCashFlowGraph", () => {
  it("splits sources proportionally into Spending and Kept in a surplus month", () => {
    // I = 5000 > S = 3000 → K = 2000, D = 0. Two sources in a 60/40 income split.
    const summary = makeSummary({
      deposit_total: 5000,
      total_spending: 3000,
      deposits_by_company: {
        Payroll: { amount: 3000, count: 2 },
        Bonus: { amount: 2000, count: 1 },
      },
      by_category: {
        rent: { amount: 1800, count: 1 },
        groceries: { amount: 700, count: 12 },
        gasoline: { amount: 500, count: 3 },
      },
    });

    const graph = buildCashFlowGraph(summary, DEFAULT_CATEGORY_GROUPS);

    expect(graph.totalIncome).toBe(5000);
    expect(graph.totalSpending).toBe(3000);
    expect(graph.net).toBe(2000);

    const hub = graph.nodes.find((n) => n.kind === "hub");
    expect(hub?.label).toBe("Spending");
    expect(hub?.amount).toBe(3000);

    const kept = graph.nodes.find((n) => n.kind === "savings");
    expect(kept?.label).toBe("Kept");
    expect(kept?.amount).toBe(2000);
    expect(graph.nodes.find((n) => n.kind === "drawdown")).toBeUndefined();

    // Hub receives exactly S = min(I, S) across the source spending links.
    const spendLinks = graph.links.filter((l) => l.target === HUB_ID);
    expect(spendLinks.reduce((sum, l) => sum + l.value, 0)).toBe(3000);
    // Kept receives exactly K = 2000.
    const keptLinks = graph.links.filter((l) => l.target === SAVINGS_ID);
    expect(keptLinks.reduce((sum, l) => sum + l.value, 0)).toBe(2000);

    // 60/40 income split lands 60/40 on both the spending and kept links.
    const payrollSpend = spendLinks.find((l) => l.source === "src::Payroll");
    const bonusSpend = spendLinks.find((l) => l.source === "src::Bonus");
    expect(payrollSpend?.value).toBe(1800); // 3000 × 3000/5000
    expect(bonusSpend?.value).toBe(1200); // 2000 × 3000/5000

    const payrollKept = keptLinks.find((l) => l.source === "src::Payroll");
    const bonusKept = keptLinks.find((l) => l.source === "src::Bonus");
    expect(payrollKept?.value).toBe(1200); // 3000 × 2000/5000
    expect(bonusKept?.value).toBe(800); // 2000 × 2000/5000
  });

  it("keeps the spending and kept splits summing to the cent under rounding", () => {
    // I = 100, S = 10 → K = 90. Three near-thirds sources force sub-cent residuals.
    const summary = makeSummary({
      deposit_total: 100,
      total_spending: 10,
      deposits_by_company: {
        A: { amount: 33.33, count: 1 },
        B: { amount: 33.33, count: 1 },
        C: { amount: 33.34, count: 1 },
      },
      by_category: {
        groceries: { amount: 10, count: 1 },
      },
    });

    const graph = buildCashFlowGraph(summary, DEFAULT_CATEGORY_GROUPS);

    const spendLinks = graph.links.filter((l) => l.target === HUB_ID);
    const keptLinks = graph.links.filter((l) => l.target === SAVINGS_ID);
    expect(spendLinks.reduce((sum, l) => sum + l.value, 0)).toBeCloseTo(10, 10);
    expect(keptLinks.reduce((sum, l) => sum + l.value, 0)).toBeCloseTo(90, 10);
    // Exact-to-the-cent: every link value is a whole number of cents.
    for (const l of [...spendLinks, ...keptLinks]) {
      expect(Math.round(l.value * 100) / 100).toBe(l.value);
    }
  });

  it("rolls multiple categories into the same parent group", () => {
    const summary = makeSummary({
      deposit_total: 1000,
      total_spending: 600,
      deposits_by_company: { Payroll: { amount: 1000, count: 1 } },
      by_category: {
        groceries: { amount: 400, count: 5 },
        "restaurant/dining": { amount: 200, count: 3 },
      },
    });

    const graph = buildCashFlowGraph(summary, DEFAULT_CATEGORY_GROUPS);
    const food = graph.nodes.find((n) => n.label === "Food & Dining");
    expect(food?.amount).toBe(600);
  });

  it("feeds the hub from a From savings source when spending exceeds income", () => {
    // I = 1000 < S = 1500 → K = 0, D = 500.
    const summary = makeSummary({
      deposit_total: 1000,
      total_spending: 1500,
      deposits_by_company: { Payroll: { amount: 1000, count: 1 } },
      by_category: {
        rent: { amount: 1500, count: 1 },
      },
    });

    const graph = buildCashFlowGraph(summary, DEFAULT_CATEGORY_GROUPS);

    expect(graph.net).toBe(-500);
    expect(graph.nodes.find((n) => n.kind === "savings")).toBeUndefined();

    const drawdown = graph.nodes.find((n) => n.kind === "drawdown");
    expect(drawdown?.label).toBe("From savings");
    expect(drawdown?.amount).toBe(500);

    const hub = graph.nodes.find((n) => n.kind === "hub");
    expect(hub?.amount).toBe(1500);

    // Hub total inflow equals S: 1000 from the source + 500 from savings.
    const incoming = graph.links
      .filter((l) => l.target === HUB_ID)
      .reduce((sum, l) => sum + l.value, 0);
    expect(incoming).toBe(1500);
    const fromSavings = graph.links.find((l) => l.source === DRAWDOWN_ID);
    expect(fromSavings?.value).toBe(500);
  });

  it("uses a single From savings source when income is zero", () => {
    const summary = makeSummary({
      deposit_total: 0,
      total_spending: 800,
      deposits_by_company: {},
      by_category: {
        rent: { amount: 800, count: 1 },
      },
    });

    const graph = buildCashFlowGraph(summary, DEFAULT_CATEGORY_GROUPS);

    expect(graph.nodes.filter((n) => n.kind === "source")).toHaveLength(0);
    expect(graph.nodes.find((n) => n.kind === "savings")).toBeUndefined();

    const drawdown = graph.nodes.find((n) => n.kind === "drawdown");
    expect(drawdown?.amount).toBe(800);
    const incoming = graph.links
      .filter((l) => l.target === HUB_ID)
      .reduce((sum, l) => sum + l.value, 0);
    expect(incoming).toBe(800);
  });

  it("routes sources only to Kept when there is income but no spending", () => {
    const summary = makeSummary({
      deposit_total: 1000,
      total_spending: 0,
      deposits_by_company: { Payroll: { amount: 1000, count: 1 } },
    });

    const graph = buildCashFlowGraph(summary, DEFAULT_CATEGORY_GROUPS);

    // No hub is emitted when spending is zero.
    expect(graph.nodes.find((n) => n.kind === "hub")).toBeUndefined();
    const kept = graph.nodes.find((n) => n.kind === "savings");
    expect(kept?.amount).toBe(1000);

    // The only link runs source → Kept.
    expect(graph.links).toEqual([{ source: "src::Payroll", target: SAVINGS_ID, value: 1000 }]);
    // net is I − S; the component's empty guard (both zero) does not fire here.
    expect(graph.net).toBe(1000);
    expect(graph.totalIncome === 0 && graph.totalSpending === 0).toBe(false);
  });

  it("emits nothing but zeros when the summary is all zero", () => {
    const graph = buildCashFlowGraph(makeSummary(), DEFAULT_CATEGORY_GROUPS);
    expect(graph.nodes).toEqual([]);
    expect(graph.links).toEqual([]);
    expect(graph.net).toBe(0);
    // The empty guard fires only when both income and spending are zero.
    expect(graph.totalIncome === 0 && graph.totalSpending === 0).toBe(true);
  });

  it("ignores zero or negative source amounts", () => {
    const summary = makeSummary({
      deposit_total: 100,
      total_spending: 0,
      deposits_by_company: {
        Real: { amount: 100, count: 1 },
        Zero: { amount: 0, count: 0 },
      },
    });

    const graph = buildCashFlowGraph(summary, DEFAULT_CATEGORY_GROUPS);
    const sources = graph.nodes.filter((n) => n.kind === "source");
    expect(sources.map((n) => n.label)).toEqual(["Real"]);
  });

  it("never emits a Drawdown label in any node", () => {
    const scenarios = [
      makeSummary({
        deposit_total: 1000,
        total_spending: 1500,
        deposits_by_company: { Payroll: { amount: 1000, count: 1 } },
        by_category: { rent: { amount: 1500, count: 1 } },
      }),
      makeSummary({
        deposit_total: 5000,
        total_spending: 3000,
        deposits_by_company: { Payroll: { amount: 5000, count: 1 } },
        by_category: { rent: { amount: 3000, count: 1 } },
      }),
    ];
    for (const summary of scenarios) {
      const graph = buildCashFlowGraph(summary, DEFAULT_CATEGORY_GROUPS);
      for (const node of graph.nodes) {
        expect(node.label).not.toBe("Drawdown");
      }
    }
  });
});
