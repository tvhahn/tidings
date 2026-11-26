import { render, screen } from "@testing-library/react";
import { afterEach, describe, expect, it } from "vitest";
import { JournalHeadline } from "@/components/JournalHeadline";
import { formatCurrencyRounded } from "@/lib/format";
import { approxAmount, type ExpectedCharge, type MonthPace } from "@/lib/projectionBreakdown";
import { usePreferences } from "@/stores/preferences";
import type { JournalDay } from "@/types/api";

function charge(over: Partial<ExpectedCharge>): ExpectedCharge {
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

function makeDay(date: string, day_total: number): JournalDay {
  return { date, day_total, mtd_total: day_total, count: 1, transactions: [] };
}

const CHARGES: ExpectedCharge[] = [
  charge({
    merchant: "northwind-insurance",
    display_name: "Northwind Insurance",
    expected_day: 20,
    amount_estimate: 175,
  }),
  charge({ merchant: "netflix", display_name: "Netflix", expected_day: 24, amount_estimate: 19 }),
  charge({
    merchant: "westland-mortgage",
    display_name: "Westland Mortgage Co",
    status: "assumed",
    channel: "statement",
    expected_day: 1,
    amount_estimate: 1850,
  }),
];

const PACE_WITH_BREAKDOWN: MonthPace = {
  day_of_month: 19,
  days_in_month: 31,
  forecast_quality: "typical",
  previous_to_date: 2603.4,
  projected_lower: 3700,
  projected_month_total: 3860,
  projected_upper: 4000,
  typical_to_date: 2600,
  breakdown: {
    observed_mtd: 2461.75,
    assumed_committed: 1850,
    upcoming_committed: 194,
    everyday_remainder: 1006,
    everyday_daily_rate: 84,
    days_remaining: 12,
    charges: CHARGES,
  },
};

function baseProps(pace: MonthPace | null) {
  return {
    monthLabel: "March 2026",
    prevMonthLabel: "February",
    spent: 2461.75,
    budget: 4600,
    monthDelta: -141.65,
    prevMonthSpent: 2603.4,
    spentPct: 56,
    pacePct: 61,
    daysRemaining: 12,
    asOfDay: 19,
    pace,
    days: [makeDay("2026-03-05", 40), makeDay("2026-03-12", 120), makeDay("2026-03-18", 60)],
    onOpenBreakdown: () => {},
    onScrollToDay: () => {},
  };
}

afterEach(() => {
  usePreferences.setState({ headlineVariant: "standard" });
});

describe("JournalHeadline container", () => {
  it("renders the N8.2 spent hero by default: one sentence and a wordless pace bar", () => {
    render(<JournalHeadline {...baseProps(PACE_WITH_BREAKDOWN)} />);
    const projectedRounded = formatCurrencyRounded(2461.75 + 1850 + 194 + 1006); // $5,512
    const proseButton = screen.getByRole("button", {
      name: `Heading for about ${projectedRounded} by month end — open the breakdown`,
    });
    const prose = proseButton.closest("p");
    expect(prose?.textContent).toBe(`Heading for about ${projectedRounded} by month end.`);
    // The prose hedges with "about" — no tilde.
    expect(prose?.textContent).not.toContain("~");
    // The bar carries no words; its description is for screen readers only.
    expect(screen.getByRole("img").getAttribute("aria-label")).toBe(
      `$2,462 of the $4,600 ceiling is spent, 54%. The month is heading for about ${projectedRounded}, 120%.`
    );
    expect(screen.getByText("$4,600 ceiling")).toBeInTheDocument();
    // Removed in N8.2: the forecast diamond, the vs-prev figure, the verdict
    // label and the days-left caption (that lives on a tile now).
    expect(screen.queryByRole("button", { name: /^Projected/ })).not.toBeInTheDocument();
    expect(screen.queryByText(/February/)).not.toBeInTheDocument();
    expect(screen.queryByText("12 days left")).not.toBeInTheDocument();
  });

  it("renders the Timeline variant when the store selects it", () => {
    usePreferences.setState({ headlineVariant: "timeline" });
    render(<JournalHeadline {...baseProps(PACE_WITH_BREAKDOWN)} />);
    // Pencils (upcoming + assumed) and the month-end diamond all open the sheet.
    const pencilAndDiamond = screen
      .getAllByRole("button")
      .filter((b) => /— open the breakdown$/.test(b.getAttribute("aria-label") ?? ""));
    expect(pencilAndDiamond).toHaveLength(CHARGES.length + 1);
    // The "how it adds up" caption phrase also opens the sheet.
    expect(
      screen.getByRole("button", { name: "Open the projection breakdown" })
    ).toBeInTheDocument();
  });

  it("keeps merchant names and amounts off the Timeline axis (hover-only)", () => {
    usePreferences.setState({ headlineVariant: "timeline" });
    const clustered: MonthPace = {
      ...PACE_WITH_BREAKDOWN,
      breakdown: {
        ...PACE_WITH_BREAKDOWN.breakdown!,
        assumed_committed: 4290,
        charges: [
          charge({
            merchant: "westland-mortgage",
            display_name: "Westland Mortgage Co",
            status: "assumed",
            channel: "statement",
            expected_day: 2,
            amount_estimate: 1850,
          }),
          charge({
            merchant: "northwind-property",
            display_name: "Northwind Property Co",
            status: "assumed",
            channel: "statement",
            expected_day: 2,
            amount_estimate: 1500,
          }),
          charge({
            merchant: "condo-fees",
            display_name: "Condo Fees",
            status: "assumed",
            channel: "statement",
            expected_day: 4,
            amount_estimate: 940,
          }),
        ],
      },
    };
    render(<JournalHeadline {...baseProps(clustered)} />);
    // No static merchant names or amounts on the axis — details are hover-only.
    expect(screen.queryByText(/Northwind Property Co/)).not.toBeInTheDocument();
    expect(screen.queryByText(/Westland Mortgage Co/)).not.toBeInTheDocument();
    expect(screen.queryByText(approxAmount(1850))).not.toBeInTheDocument();
    // All three pencil circles still render (each opens the sheet).
    const pencils = screen
      .getAllByRole("button")
      .filter((b) =>
        /awaiting statement — open the breakdown$/.test(b.getAttribute("aria-label") ?? "")
      );
    expect(pencils).toHaveLength(3);
  });

  it("drops the sentence and projection when there is no commitment-aware pace", () => {
    render(<JournalHeadline {...baseProps(null)} />);
    expect(screen.queryByText(/Heading for about/)).not.toBeInTheDocument();
    expect(screen.queryByRole("button", { name: /open the breakdown/i })).not.toBeInTheDocument();
    expect(screen.getByRole("img").getAttribute("aria-label")).toBe(
      "$2,462 of the $4,600 ceiling is spent, 54%."
    );
  });

  it("reads a finished month against the ceiling", () => {
    render(<JournalHeadline {...baseProps(null)} asOfDay={null} pacePct={100} spent={4800} />);
    expect(screen.getByText("$200 over the $4,600 ceiling.")).toBeInTheDocument();
    expect(screen.getByText("Spent · March 2026")).toBeInTheDocument();
  });

  it("keeps the spent hero for a null-breakdown month even under the Timeline preference", () => {
    usePreferences.setState({ headlineVariant: "timeline" });
    render(<JournalHeadline {...baseProps(null)} />);
    expect(screen.getByText("$4,600 ceiling")).toBeInTheDocument();
    expect(screen.queryByRole("button", { name: /open the breakdown/i })).not.toBeInTheDocument();
  });
});
