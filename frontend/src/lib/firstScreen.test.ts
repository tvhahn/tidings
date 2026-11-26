import { describe, expect, it } from "vitest";
import {
  budgetBarWidths,
  budgetHero,
  ceilingTile,
  chargeDayLabel,
  closedMonthSentence,
  groupTiles,
  monthBars,
  paceBarWidths,
  splitCents,
  stillExpectedTile,
  upcomingCharges,
} from "@/lib/firstScreen";
import type { ExpectedCharge, MonthPaceBreakdown } from "@/lib/projectionBreakdown";
import { makeBudgetStatus } from "@/test/factories";
import type { GroupPace } from "@/types/api";

function charge(over: Partial<ExpectedCharge>): ExpectedCharge {
  return {
    merchant: "acme",
    display_name: "Acme",
    amount_estimate: 10,
    expected_day: 20,
    status: "upcoming",
    channel: "email",
    cadence: "monthly",
    category: null,
    actual_amount: null,
    actual_date: null,
    previous_amount: null,
    ...over,
  };
}

function breakdown(charges: ExpectedCharge[], upcoming: number): MonthPaceBreakdown {
  return {
    observed_mtd: 4923.98,
    assumed_committed: 0,
    upcoming_committed: upcoming,
    everyday_remainder: 741,
    everyday_daily_rate: 61.75,
    days_remaining: 12,
    charges,
  };
}

function group(name: string, spent: number, expected: number): GroupPace {
  return {
    name,
    budgeted_total: expected / 0.214,
    ytd_spent: spent,
    expected_pace: expected,
    variance: expected - spent,
    status: spent > expected ? "over" : "under",
    categories: [],
    monthly_totals: [],
    prior_year_total: null,
  };
}

describe("splitCents", () => {
  it("splits whole dollars and two-digit cents, rounding to the cent", () => {
    expect(splitCents(4923.98)).toEqual({ whole: "$4,923", cents: "98" });
    expect(splitCents(190.969)).toEqual({ whole: "$190", cents: "97" });
    expect(splitCents(12)).toEqual({ whole: "$12", cents: "00" });
  });
});

describe("Journal tiles", () => {
  it("draws the spent fill with a pale run to the projection, clamped", () => {
    expect(paceBarWidths({ spent: 4923.98, budget: 6000, projected: 5856 })).toEqual({
      fillPct: (4923.98 / 6000) * 100,
      projPct: 97.6,
    });
    expect(paceBarWidths({ spent: 7000, budget: 6000, projected: 9000 })).toEqual({
      fillPct: 100,
      projPct: null,
    });
  });

  it("names the room below the ceiling, or the overage in words", () => {
    expect(
      ceilingTile({ spent: 4923.98, budget: 6000, daysRemaining: 12, monthClosed: false })
    ).toEqual({ label: "Below the ceiling", amount: 6000 - 4923.98, caption: "12 days left" });
    expect(
      ceilingTile({ spent: 6100, budget: 6000, daysRemaining: 1, monthClosed: false })
    ).toEqual({ label: "Over the ceiling", amount: 100, caption: "1 day left" });
    expect(
      ceilingTile({ spent: 10, budget: 6000, daysRemaining: 0, monthClosed: true })?.caption
    ).toBe("at month end");
    expect(
      ceilingTile({ spent: 10, budget: null, daysRemaining: 3, monthClosed: false })
    ).toBeNull();
  });

  it("totals the upcoming charges and lists them by expected day", () => {
    const b = breakdown(
      [
        charge({ display_name: "Tangerine Savings", expected_day: 28, amount_estimate: 100 }),
        charge({ display_name: "Fox and John's", expected_day: 20, amount_estimate: 28.91 }),
        charge({ display_name: "Rent", expected_day: 1, status: "arrived" }),
      ],
      128.91
    );
    expect(upcomingCharges(b).map((c) => c.display_name)).toEqual([
      "Fox and John's",
      "Tangerine Savings",
    ]);
    expect(stillExpectedTile(b)).toEqual({
      label: "Still expected",
      amount: 128.91,
      caption: "2 regular charges",
    });
    expect(stillExpectedTile(breakdown([], 0))).toBeNull();
  });

  it("labels a charge day with its weekday", () => {
    expect(chargeDayLabel("2026-03", 20)).toBe("Fri 20");
  });

  it("reads a finished month against the ceiling", () => {
    expect(closedMonthSentence({ spent: 5800, budget: 6000 })).toBe(
      "$200 under the $6,000 ceiling."
    );
    expect(closedMonthSentence({ spent: 6000.2, budget: 6000 })).toBe(
      "Right at the $6,000 ceiling."
    );
    expect(closedMonthSentence({ spent: 100, budget: null })).toBeNull();
  });
});

describe("Budgets first screen", () => {
  it("puts expected-by-now at 60% and caps the overage at the bar end", () => {
    expect(budgetBarWidths({ spent: 2061, expected: 1325 }).overPct).toBeCloseTo(33.3, 1);
    expect(budgetBarWidths({ spent: 500, expected: 629 }).fillPct).toBeCloseTo(47.7, 1);
    expect(budgetBarWidths({ spent: 9000, expected: 1000 })).toEqual({ fillPct: 60, overPct: 40 });
  });

  it("writes the hero against the pace for the ceiling", () => {
    const status = makeBudgetStatus({
      as_of: "2026-03-19",
      elapsed_year_fraction: 0.214,
      overall: {
        expected_pace: 15408,
        headline: "",
        spending_ceiling: 72000,
        status: "under",
        variance: 174.71,
        ytd_spent: 15233.29,
        projected_month_status: null,
        projected_month_total: null,
      },
    });
    const hero = budgetHero(status);
    expect(hero.eyebrow).toBe("Spent this year · as of Mar 19");
    expect(hero.sentence).toBe("About $175 under the pace for a $72,000 year.");
    expect(hero.key).toBe("$15,408 expected by now");
  });

  it("reads a past year against the whole ceiling", () => {
    const status = makeBudgetStatus({
      year: 2025,
      elapsed_year_fraction: 1,
      overall: {
        expected_pace: 72000,
        headline: "",
        spending_ceiling: 72000,
        status: "over",
        variance: -1200,
        ytd_spent: 73200,
        projected_month_status: null,
        projected_month_total: null,
      },
    });
    const hero = budgetHero(status);
    expect(hero.eyebrow).toBe("Spent in 2025");
    expect(hero.sentence).toBe("$1,200 over the $72,000 ceiling.");
    expect(hero.key).toBe("$72,000 ceiling");
  });

  it("orders groups most over first and widens the first when the count is odd", () => {
    const status = makeBudgetStatus({
      groups: [
        group("Food & Dining", 3300, 4417),
        group("Housing", 6923, 6220),
        group("Entertainment", 2061, 1325),
      ],
    });
    const tiles = groupTiles(status);
    expect(tiles.map((t) => t.name)).toEqual(["Entertainment", "Housing", "Food & Dining"]);
    expect(tiles[0]).toMatchObject({
      wide: true,
      stateWords: "over by",
      stateAmount: "$736",
      caption: "$2,061 spent of $1,325 expected by now",
    });
    expect(tiles[2]).toMatchObject({
      wide: false,
      stateWords: "under by",
      stateAmount: "$1,117",
      caption: "$3,300 of $4,417",
    });
  });
});

describe("monthBars", () => {
  const months = [
    { year_month: "2026-02", total_spending: 5700 },
    { year_month: "2026-03", total_spending: 4923.98 },
  ];

  it("scales to the ceiling and draws the current projection behind its bar", () => {
    const model = monthBars({ months, currentMonth: "2026-03", ceiling: 6000, projected: 5856 });
    expect(model?.ceilingPct).toBe(100);
    expect(model?.bars[1]).toMatchObject({ current: true, projPct: 97.6 });
    expect(model?.bars[0]?.projPct).toBeNull();
    expect(model?.ariaLabel).toBe(
      "Spending in the last 2 months against the $6,000 ceiling. February was at 95% of it. March is at 82% and heading for 98%."
    );
  });

  it("rescales when a month runs past the ceiling", () => {
    const model = monthBars({
      months: [...months, { year_month: "2026-04", total_spending: 8000 }],
      currentMonth: "2026-04",
      ceiling: 6000,
      projected: null,
    });
    expect(model?.ceilingPct).toBe(75);
    expect(model?.bars[2]?.spentPct).toBe(100);
  });
});
