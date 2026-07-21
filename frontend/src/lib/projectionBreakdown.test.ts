import { describe, expect, it } from "vitest";
import {
  approxAmount,
  buildProjectionBreakdown,
  type ExpectedCharge,
  type MonthPace,
  type MonthPaceBreakdown,
  ordinalDay,
  vsPrevDelta,
} from "@/lib/projectionBreakdown";

function charge(over: Partial<ExpectedCharge> = {}): ExpectedCharge {
  return {
    merchant: "acme",
    display_name: "Acme",
    amount_estimate: 100,
    expected_day: 15,
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

function pace(
  breakdownOver: Partial<NonNullable<MonthPace["breakdown"]>> | null,
  paceOver: Partial<MonthPace> = {}
): MonthPace {
  const breakdown =
    breakdownOver === null
      ? null
      : {
          observed_mtd: 0,
          assumed_committed: 0,
          upcoming_committed: 0,
          everyday_remainder: 0,
          everyday_daily_rate: null,
          days_remaining: 10,
          charges: [],
          ...breakdownOver,
        };
  return {
    day_of_month: 19,
    days_in_month: 31,
    forecast_quality: "typical",
    previous_to_date: 0,
    projected_lower: null,
    projected_month_total: null,
    projected_upper: null,
    typical_to_date: null,
    breakdown,
    ...paceOver,
  };
}

describe("ordinalDay", () => {
  it("suffixes day-of-month correctly, including the 11–13 exception", () => {
    expect(ordinalDay(1)).toBe("1st");
    expect(ordinalDay(2)).toBe("2nd");
    expect(ordinalDay(3)).toBe("3rd");
    expect(ordinalDay(11)).toBe("11th");
    expect(ordinalDay(12)).toBe("12th");
    expect(ordinalDay(13)).toBe("13th");
    expect(ordinalDay(21)).toBe("21st");
    expect(ordinalDay(23)).toBe("23rd");
    expect(ordinalDay(31)).toBe("31st");
  });
});

describe("buildProjectionBreakdown", () => {
  it("returns null when the pace has no breakdown", () => {
    expect(buildProjectionBreakdown(pace(null), "March 2026")).toBeNull();
  });

  it("excludes arrived rows from the committed section total but still lists them", () => {
    const model = buildProjectionBreakdown(
      pace({
        observed_mtd: 2461.75,
        upcoming_committed: 266,
        everyday_remainder: 1006,
        charges: [
          charge({
            merchant: "rent",
            display_name: "Rent",
            status: "arrived",
            expected_day: 1,
            amount_estimate: 2150,
            actual_amount: 2150,
            actual_date: "2026-03-01",
          }),
          charge({
            merchant: "northwind-insurance",
            display_name: "Northwind Insurance",
            status: "upcoming",
            expected_day: 20,
            amount_estimate: 175,
          }),
        ],
      }),
      "March 2026"
    );
    expect(model).not.toBeNull();
    // Section total reflects only the upcoming committed sum, not the arrived rent.
    expect(model!.committed.totalText).toBe(approxAmount(266));
    const rent = model!.committed.rows.find((r) => r.displayName === "Rent");
    expect(rent).toBeDefined();
    expect(rent!.arrived).toBe(true);
    expect(rent!.muted).toBe(true);
    expect(rent!.whenText).toBe("arrived Mar 1");
    expect(rent!.amountText).toBe("$2,150.00");
    // Rows are ordered by expected day (rent day 1 before insurance day 20).
    expect(model!.committed.rows.map((r) => r.displayName)).toEqual([
      "Rent",
      "Northwind Insurance",
    ]);
  });

  it("shows the assumed section only when statement-observed charges exist", () => {
    const without = buildProjectionBreakdown(
      pace({ charges: [charge({ status: "upcoming" })] }),
      "March 2026"
    );
    expect(without!.assumed).toBeNull();

    const withAssumed = buildProjectionBreakdown(
      pace({
        assumed_committed: 1850,
        charges: [
          charge({
            merchant: "westland-mortgage",
            display_name: "Westland Mortgage Co",
            status: "assumed",
            channel: "statement",
            expected_day: 1,
            amount_estimate: 1850,
          }),
        ],
      }),
      "March 2026"
    );
    expect(withAssumed!.assumed).not.toBeNull();
    expect(withAssumed!.assumed!.totalText).toBe(approxAmount(1850));
    expect(withAssumed!.assumed!.rows[0]!.displayName).toBe("Westland Mortgage Co");
    // Assumed charges never appear in the committed section.
    expect(withAssumed!.committed.rows).toHaveLength(0);
  });

  it("renders the quiet unrecorded line and gives it no amount", () => {
    const model = buildProjectionBreakdown(
      pace({
        charges: [
          charge({
            merchant: "gym",
            display_name: "Gym",
            status: "unrecorded",
            expected_day: 5,
            amount_estimate: 45,
          }),
        ],
      }),
      "March 2026"
    );
    const row = model!.committed.rows[0]!;
    expect(row.whenText).toBe("usually bills by the 5th — nothing yet");
    expect(row.amountText).toBeNull();
    expect(row.muted).toBe(true);
    expect(row.penciled).toBe(false);
  });

  it("totals line equals projected_month_total (the L5 identity)", () => {
    const model = buildProjectionBreakdown(
      pace(
        {
          observed_mtd: 2461.75,
          assumed_committed: 0,
          upcoming_committed: 266,
          everyday_remainder: 1006,
        },
        { projected_month_total: 2461.75 + 266 + 1006 }
      ),
      "March 2026"
    );
    expect(model!.totalText).toBe(approxAmount(2461.75 + 266 + 1006));
    expect(model!.totalLabel).toBe("Expected by Mar 31");
    expect(model!.monthEndLabel).toBe("Mar 31");
  });

  it("adds the annual price-memory line when a previous amount is known", () => {
    const model = buildProjectionBreakdown(
      pace({
        charges: [
          charge({
            merchant: "domain",
            display_name: "Domain Renewal",
            status: "upcoming",
            cadence: "annual",
            expected_day: 14,
            amount_estimate: 82,
            previous_amount: 79,
          }),
        ],
      }),
      "March 2026"
    );
    expect(model!.committed.rows[0]!.priceMemory).toBe("renewed at $79 last year");
  });

  it("builds the everyday sub-line from the daily rate and days remaining", () => {
    const model = buildProjectionBreakdown(
      pace({ everyday_remainder: 1006, everyday_daily_rate: 84, days_remaining: 12 }),
      "March 2026"
    );
    expect(model!.everyday.amountText).toBe(approxAmount(1006));
    expect(model!.everyday.subLine).toBe("12 days at about $84/day, from recent months");
  });

  it("omits the everyday sub-line when no daily rate is available", () => {
    const model = buildProjectionBreakdown(
      pace({ everyday_remainder: 0, everyday_daily_rate: null, days_remaining: 0 }),
      "March 2026"
    );
    expect(model!.everyday.subLine).toBeNull();
  });
});

describe("vsPrevDelta", () => {
  function breakdown(over: Partial<MonthPaceBreakdown>): MonthPaceBreakdown {
    return {
      observed_mtd: 0,
      assumed_committed: 0,
      upcoming_committed: 0,
      everyday_remainder: 0,
      everyday_daily_rate: null,
      days_remaining: 10,
      charges: [],
      ...over,
    };
  }

  it("returns today's delta unchanged when there is no breakdown", () => {
    expect(vsPrevDelta({ monthDelta: -141.65, prevMonthSpent: 2603.4, breakdown: null })).toEqual({
      delta: -141.65,
      likeForLike: false,
    });
  });

  it("returns today's delta unchanged when there is no assumed committed spend", () => {
    expect(
      vsPrevDelta({
        monthDelta: -141.65,
        prevMonthSpent: 2603.4,
        breakdown: breakdown({ observed_mtd: 2461.75, assumed_committed: 0 }),
      })
    ).toEqual({ delta: -141.65, likeForLike: false });
  });

  it("folds assumed spend into the current side for a like-for-like comparison", () => {
    // The prior month's to-date total already includes its imported mortgage;
    // the current month's mortgage is assumed but not yet imported — count it on
    // both sides so the comparison is honest.
    const result = vsPrevDelta({
      monthDelta: -9401.5,
      prevMonthSpent: 7494.6,
      breakdown: breakdown({ observed_mtd: 2461.75, assumed_committed: 1850 }),
    });
    expect(result.likeForLike).toBe(true);
    expect(result.delta).toBeCloseTo(2461.75 + 1850 - 7494.6, 5);
  });
});
