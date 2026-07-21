import { describe, expect, it } from "vitest";
import { buildHeadline, buildSummaryCards } from "@/lib/summaryPace";
import { makeMonthSummary, makeSummary } from "@/test/factories";
import type { SummaryComparisonResponse } from "@/types/api";

type MonthPace = NonNullable<SummaryComparisonResponse["pace"]>;
type MonthPaceBreakdown = NonNullable<MonthPace["breakdown"]>;

function makePace(overrides: Partial<MonthPace> = {}): MonthPace {
  return {
    day_of_month: 10,
    days_in_month: 31,
    previous_to_date: 1000,
    typical_to_date: 1200,
    projected_month_total: 3000,
    projected_lower: 2800,
    projected_upper: 3400,
    forecast_quality: "forecast",
    ...overrides,
  };
}

function makeBreakdown(overrides: Partial<MonthPaceBreakdown> = {}): MonthPaceBreakdown {
  return {
    observed_mtd: 2000,
    assumed_committed: 0,
    upcoming_committed: 400,
    everyday_remainder: 600,
    everyday_daily_rate: 30,
    days_remaining: 20,
    charges: [],
    ...overrides,
  };
}

describe("buildSummaryCards — current month (pace non-null)", () => {
  it("renders exactly the current-month card set in order", () => {
    const cards = buildSummaryCards(makeSummary({ pace: makePace() }));
    expect(cards.map((c) => c.label)).toEqual([
      "Spent so far",
      "Projected month end",
      "vs typical pace",
    ]);
  });

  it("appends the Deposits card when deposit_count > 0", () => {
    const cards = buildSummaryCards(
      makeSummary({
        pace: makePace(),
        current: makeMonthSummary({ deposit_count: 2, deposit_total: 500 }),
      })
    );
    expect(cards.map((c) => c.label)).toEqual([
      "Spent so far",
      "Projected month end",
      "vs typical pace",
      "Deposits",
    ]);
    expect(cards[3]?.value).toBe("$500.00");
    expect(cards[3]?.sub).toBe("2 e-transfers");
    expect(cards[3]?.icon).toBe("transfer");
  });

  it("Spent so far shows the total and day-of-month sub", () => {
    const cards = buildSummaryCards(
      makeSummary({
        pace: makePace({ day_of_month: 10, days_in_month: 31 }),
        current: makeMonthSummary({ total_spending: 1686.33 }),
      })
    );
    expect(cards[0]?.value).toBe("$1,686.33");
    expect(cards[0]?.sub).toBe("day 10 of 31");
    expect(cards[0]?.icon).toBe("receipt");
    expect(cards[0]?.tone).toBe("text-fg-muted");
  });

  it("projected card shows the typical range when both bounds exist and differ", () => {
    const cards = buildSummaryCards(
      makeSummary({
        pace: makePace({
          projected_month_total: 3000,
          projected_lower: 2800,
          projected_upper: 3400,
        }),
      })
    );
    expect(cards[1]?.value).toBe("$3,000");
    expect(cards[1]?.sub).toBe("typical range $2,800–$3,400");
  });

  it("projected card falls back to 'limited history' on limited quality", () => {
    const cards = buildSummaryCards(
      makeSummary({
        pace: makePace({
          projected_lower: null,
          projected_upper: null,
          forecast_quality: "limited",
        }),
      })
    );
    expect(cards[1]?.sub).toBe("limited history");
  });

  it("projected card falls back to 'based on typical spending' when bounds are equal", () => {
    const cards = buildSummaryCards(
      makeSummary({
        pace: makePace({ projected_lower: 3000, projected_upper: 3000 }),
      })
    );
    expect(cards[1]?.sub).toBe("based on typical spending");
  });

  it("projected card shows em-dash value and 'not enough history' when projection is null", () => {
    const cards = buildSummaryCards(
      makeSummary({ pace: makePace({ projected_month_total: null }) })
    );
    expect(cards[1]?.value).toBe("—");
    expect(cards[1]?.sub).toBe("not enough history");
  });

  it("vs typical pace shows above sub / danger tone when spending exceeds typical", () => {
    const cards = buildSummaryCards(
      makeSummary({
        pace: makePace({ typical_to_date: 1200, day_of_month: 10 }),
        current: makeMonthSummary({ total_spending: 1500 }),
      })
    );
    expect(cards[2]?.value).toBe("+$300.00");
    expect(cards[2]?.sub).toBe("above typical by day 10");
    expect(cards[2]?.tone).toBe("text-status-danger-calm-text");
    expect(cards[2]?.icon).toBe("up");
  });

  it("vs typical pace shows below sub / success tone with U+2212 minus when under", () => {
    const cards = buildSummaryCards(
      makeSummary({
        pace: makePace({ typical_to_date: 1200, day_of_month: 10 }),
        current: makeMonthSummary({ total_spending: 900 }),
      })
    );
    expect(cards[2]?.value).toBe("−$300.00");
    expect(cards[2]?.value).toContain("−");
    expect(cards[2]?.sub).toBe("below typical by day 10");
    expect(cards[2]?.tone).toBe("text-status-success");
    expect(cards[2]?.icon).toBe("down");
  });

  it("vs typical pace degrades to em-dash when typical_to_date is null", () => {
    const cards = buildSummaryCards(makeSummary({ pace: makePace({ typical_to_date: null }) }));
    expect(cards[2]?.value).toBe("—");
    expect(cards[2]?.sub).toBe("not enough history");
    expect(cards[2]?.icon).toBe("gauge");
    expect(cards[2]?.tone).toBe("text-fg-muted");
  });

  it("marks the projected card clickable only when the pace carries a breakdown", () => {
    const cards = buildSummaryCards(
      makeSummary({ pace: makePace({ breakdown: makeBreakdown() }) })
    );
    expect(cards[1]?.label).toBe("Projected month end");
    expect(cards[1]?.opensBreakdown).toBe(true);
  });

  it("leaves the projected card non-clickable when there is no breakdown", () => {
    const cards = buildSummaryCards(makeSummary({ pace: makePace() }));
    expect(cards[1]?.opensBreakdown).toBeFalsy();
  });

  it("never marks a non-projected card clickable, even with a breakdown present", () => {
    const cards = buildSummaryCards(
      makeSummary({
        pace: makePace({ breakdown: makeBreakdown() }),
        current: makeMonthSummary({ deposit_count: 2, deposit_total: 500 }),
      })
    );
    // Spent so far, vs typical pace, and Deposits are all inert.
    expect(cards[0]?.opensBreakdown).toBeFalsy();
    expect(cards[2]?.opensBreakdown).toBeFalsy();
    expect(cards[3]?.opensBreakdown).toBeFalsy();
  });

  it("does not mark the projected card clickable when the projection is null", () => {
    const cards = buildSummaryCards(
      makeSummary({ pace: makePace({ projected_month_total: null, breakdown: makeBreakdown() }) })
    );
    expect(cards[1]?.value).toBe("—");
    expect(cards[1]?.opensBreakdown).toBeFalsy();
  });

  it("vs typical pace folds assumed statement charges into the comparison and flags the sub", () => {
    // Observed-only (900) would read below typical (1200); the assumed 500
    // statement charges push the honest comparison above it — the motivating bug.
    const cards = buildSummaryCards(
      makeSummary({
        pace: makePace({
          typical_to_date: 1200,
          day_of_month: 17,
          breakdown: makeBreakdown({ assumed_committed: 500 }),
        }),
        current: makeMonthSummary({ total_spending: 900 }),
      })
    );
    expect(cards[2]?.value).toBe("+$200.00");
    expect(cards[2]?.sub).toBe("above typical by day 17 · statement charges assumed");
    expect(cards[2]?.tone).toBe("text-status-danger-calm-text");
    expect(cards[2]?.icon).toBe("up");
    // Hero "Spent so far" stays observed-only — never the effective figure.
    expect(cards[0]?.label).toBe("Spent so far");
    expect(cards[0]?.value).toBe("$900.00");
  });

  it("appends the assumed fragment even when the effective figure stays below typical", () => {
    const cards = buildSummaryCards(
      makeSummary({
        pace: makePace({
          typical_to_date: 1200,
          day_of_month: 17,
          breakdown: makeBreakdown({ assumed_committed: 200 }),
        }),
        current: makeMonthSummary({ total_spending: 900 }),
      })
    );
    // effective = 1100; diff = −100 vs typical 1200 → still below.
    expect(cards[2]?.value).toBe("−$100.00");
    expect(cards[2]?.sub).toBe("below typical by day 17 · statement charges assumed");
    expect(cards[2]?.tone).toBe("text-status-success");
    expect(cards[2]?.icon).toBe("down");
  });

  it("vs typical pace is byte-identical to observed-only when assumed is 0", () => {
    const cards = buildSummaryCards(
      makeSummary({
        pace: makePace({
          typical_to_date: 1200,
          day_of_month: 10,
          breakdown: makeBreakdown({ assumed_committed: 0 }),
        }),
        current: makeMonthSummary({ total_spending: 900 }),
      })
    );
    expect(cards[2]?.value).toBe("−$300.00");
    expect(cards[2]?.sub).toBe("below typical by day 10");
  });
});

describe("buildSummaryCards — complete month (pace null)", () => {
  it("renders exactly the complete-month card set in order", () => {
    const cards = buildSummaryCards(makeSummary());
    expect(cards.map((c) => c.label)).toEqual(["Total spending", "Transactions", "Daily average"]);
  });

  it("Total spending sub compares against the previous month's short label", () => {
    const cards = buildSummaryCards(
      makeSummary({
        current: makeMonthSummary({ total_spending: 3000, year_month: "2026-04" }),
        previous: makeMonthSummary({ total_spending: 2600, year_month: "2026-03" }),
        delta_amount: 400,
        delta_percent: 15.4,
      })
    );
    expect(cards[0]?.value).toBe("$3,000.00");
    expect(cards[0]?.sub).toBe("+15.4% vs Mar");
    expect(cards[0]?.icon).toBe("up");
    expect(cards[0]?.tone).toBe("text-status-danger-calm-text");
  });

  it("Total spending sub is omitted when the previous total is 0", () => {
    const cards = buildSummaryCards(
      makeSummary({
        current: makeMonthSummary({ total_spending: 3000 }),
        previous: makeMonthSummary({ total_spending: 0 }),
      })
    );
    expect(cards[0]?.sub).toBe("");
  });

  it("Transactions shows 'no deposits' when none arrived", () => {
    const cards = buildSummaryCards(
      makeSummary({ current: makeMonthSummary({ spending_count: 42, deposit_count: 0 }) })
    );
    expect(cards[1]?.value).toBe("42");
    expect(cards[1]?.sub).toBe("no deposits");
  });

  it("Transactions counts deposits received when present", () => {
    const cards = buildSummaryCards(
      makeSummary({
        current: makeMonthSummary({ spending_count: 42, deposit_count: 3, deposit_total: 100 }),
      })
    );
    expect(cards[1]?.sub).toBe("3 deposits received");
  });

  it("Daily average divides the total by that month's day count", () => {
    const cards = buildSummaryCards(
      makeSummary({
        current: makeMonthSummary({ total_spending: 3000, year_month: "2026-04" }),
      })
    );
    // April has 30 days
    expect(cards[2]?.value).toBe("$100.00");
    expect(cards[2]?.sub).toBe("across 30 days");
    expect(cards[2]?.icon).toBe("gauge");
  });
});

describe("buildHeadline — current month", () => {
  const withRatio = (total: number, typical: number) =>
    makeSummary({
      pace: makePace({ typical_to_date: typical }),
      current: makeMonthSummary({ total_spending: total }),
    });

  it("reports below typical at ratio 0.80", () => {
    expect(buildHeadline(withRatio(800, 1000))).toBe(
      "Spending is tracking 20% below typical for this point in the month."
    );
  });

  it("reports above typical at ratio 1.20", () => {
    expect(buildHeadline(withRatio(1200, 1000))).toBe(
      "Spending is tracking 20% above typical for this point in the month."
    );
  });

  it("reports close to typical at ratio 1.04", () => {
    expect(buildHeadline(withRatio(1040, 1000))).toBe(
      "Spending is tracking close to typical for this point in the month."
    );
  });

  it("treats the 1.05 boundary as close to typical", () => {
    expect(buildHeadline(withRatio(1050, 1000))).toBe(
      "Spending is tracking close to typical for this point in the month."
    );
  });

  it("returns null when typical_to_date is null", () => {
    expect(buildHeadline(makeSummary({ pace: makePace({ typical_to_date: null }) }))).toBeNull();
  });

  it("counts assumed statement charges in the lead ratio (statement-lag honesty)", () => {
    // Observed-only (700/1000) would read 30% below; effective (1200/1000) is
    // 20% above once the assumed 500 statement charges are folded in.
    expect(
      buildHeadline(
        makeSummary({
          pace: makePace({
            typical_to_date: 1000,
            breakdown: makeBreakdown({ assumed_committed: 500 }),
          }),
          current: makeMonthSummary({ total_spending: 700 }),
        })
      )
    ).toBe("Spending is tracking 20% above typical for this point in the month.");
  });

  it("lead ratio is unchanged from observed-only when assumed is 0", () => {
    expect(
      buildHeadline(
        makeSummary({
          pace: makePace({
            typical_to_date: 1200,
            breakdown: makeBreakdown({ assumed_committed: 0 }),
          }),
          current: makeMonthSummary({ total_spending: 900 }),
        })
      )
    ).toBe("Spending is tracking 25% below typical for this point in the month.");
  });
});

describe("buildHeadline — complete month", () => {
  const closed = (deltaPercent: number) =>
    makeSummary({
      current: makeMonthSummary({ total_spending: 3000, year_month: "2026-04" }),
      previous: makeMonthSummary({ total_spending: 2600, year_month: "2026-03" }),
      delta_percent: deltaPercent,
    });

  it("reports above the previous month", () => {
    expect(buildHeadline(closed(15.4))).toBe(
      "April 2026 closed at $3,000.00, 15% above March 2026."
    );
  });

  it("reports below the previous month", () => {
    expect(buildHeadline(closed(-15.4))).toBe(
      "April 2026 closed at $3,000.00, 15% below March 2026."
    );
  });

  it("treats the ±2% boundary as about even", () => {
    expect(buildHeadline(closed(2))).toBe(
      "April 2026 closed at $3,000.00, about even with March 2026."
    );
    expect(buildHeadline(closed(-2))).toBe(
      "April 2026 closed at $3,000.00, about even with March 2026."
    );
  });

  it("returns null when the previous total is 0", () => {
    expect(
      buildHeadline(
        makeSummary({
          current: makeMonthSummary({ total_spending: 3000 }),
          previous: makeMonthSummary({ total_spending: 0 }),
        })
      )
    ).toBeNull();
  });
});
