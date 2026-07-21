import { describe, expect, it } from "vitest";
import {
  formatCurrency,
  formatCurrencyRounded,
  formatCurrencyZeroDash,
  formatDate,
  formatRelativeTime,
  titleCase,
  currentMonth,
  formatPercent,
  formatMonthLabel,
  formatMonthLabelLong,
  formatVariance,
  shiftMonth,
  currentYear,
  MONTH_SHORT,
  MONTH_LONG,
} from "./format";

describe("formatCurrency", () => {
  it("returns em-dash for null", () => {
    expect(formatCurrency(null)).toBe("—");
  });

  it("formats zero", () => {
    expect(formatCurrency(0)).toBe("$0.00");
  });

  it("formats positive amount", () => {
    expect(formatCurrency(1234.56)).toBe("$1,234.56");
  });

  it("formats negative amount", () => {
    expect(formatCurrency(-50.99)).toBe("−$50.99");
  });

  it("formats large amount with comma grouping", () => {
    expect(formatCurrency(96000)).toBe("$96,000.00");
  });
});

describe("formatCurrencyZeroDash", () => {
  it("renders zero as an em dash", () => {
    expect(formatCurrencyZeroDash(0)).toBe("—");
  });

  it("formats a positive amount as currency", () => {
    expect(formatCurrencyZeroDash(1234.56)).toBe("$1,234.56");
  });

  it("formats a negative amount with the true minus", () => {
    expect(formatCurrencyZeroDash(-50.99)).toBe("−$50.99");
  });
});

describe("formatCurrencyRounded", () => {
  it("renders null as an ASCII hyphen placeholder", () => {
    expect(formatCurrencyRounded(null)).toBe("-");
  });

  it("rounds to whole dollars with comma grouping and no cents", () => {
    expect(formatCurrencyRounded(1234.56)).toBe("$1,235");
    expect(formatCurrencyRounded(96000)).toBe("$96,000");
  });

  it("formats zero", () => {
    expect(formatCurrencyRounded(0)).toBe("$0");
  });

  it("uses the U+2212 minus for negative amounts", () => {
    expect(formatCurrencyRounded(-50)).toBe("$−50");
    // Explicitly assert the true minus, not the ASCII hyphen.
    expect(formatCurrencyRounded(-50)).toContain("−");
    expect(formatCurrencyRounded(-50)).not.toContain("-");
  });
});

describe("month name arrays", () => {
  it("MONTH_SHORT has 12 abbreviated names", () => {
    expect(MONTH_SHORT).toHaveLength(12);
    expect(MONTH_SHORT[0]).toBe("Jan");
    expect(MONTH_SHORT[11]).toBe("Dec");
  });

  it("MONTH_LONG has 12 full names", () => {
    expect(MONTH_LONG).toHaveLength(12);
    expect(MONTH_LONG[0]).toBe("January");
    expect(MONTH_LONG[11]).toBe("December");
  });
});

describe("formatDate", () => {
  it("returns em-dash for null", () => {
    expect(formatDate(null)).toBe("—");
  });

  it("returns em-dash for empty string", () => {
    expect(formatDate("")).toBe("—");
  });

  it("formats medium by default", () => {
    expect(formatDate("02/15/2026 14:30 PST")).toBe("Feb 15, 2026");
  });

  it("legacy format returns MM/DD/YYYY", () => {
    expect(formatDate("02/15/2026 14:30 PST", "legacy")).toBe("02/15/2026");
  });

  it("iso format returns YYYY-MM-DD", () => {
    expect(formatDate("02/15/2026 14:30 PST", "iso")).toBe("2026-02-15");
  });

  it("dmy format returns D Mon YYYY", () => {
    expect(formatDate("02/15/2026 14:30 PST", "dmy")).toBe("15 Feb 2026");
  });

  it("handles single-part date string", () => {
    expect(formatDate("02/15/2026", "legacy")).toBe("02/15/2026");
    expect(formatDate("02/15/2026")).toBe("Feb 15, 2026");
  });
});

describe("titleCase", () => {
  it("returns em-dash for null", () => {
    expect(titleCase(null)).toBe("—");
  });

  it("returns em-dash for empty string", () => {
    expect(titleCase("")).toBe("—");
  });

  it("capitalizes single word", () => {
    expect(titleCase("groceries")).toBe("Groceries");
  });

  it("capitalizes multiple words", () => {
    expect(titleCase("health care")).toBe("Health Care");
  });

  it("keeps short words lowercase after the first word", () => {
    expect(titleCase("sports and recreation")).toBe("Sports and Recreation");
    expect(titleCase("cost of living")).toBe("Cost of Living");
  });

  it("capitalizes a leading short word", () => {
    expect(titleCase("the basics")).toBe("The Basics");
  });

  it("handles slash-separated words", () => {
    expect(titleCase("restaurant/dining")).toBe("Restaurant Dining");
  });

  it("lowercases uppercase input", () => {
    expect(titleCase("GROCERIES")).toBe("Groceries");
  });
});

describe("currentMonth", () => {
  it("returns YYYY-MM format", () => {
    expect(currentMonth()).toMatch(/^\d{4}-\d{2}$/);
  });
});

describe("formatPercent", () => {
  it("formats positive with plus sign", () => {
    expect(formatPercent(12.34)).toBe("+12.3%");
  });

  it("formats negative with true minus", () => {
    expect(formatPercent(-5.67)).toBe("−5.7%");
  });

  it("formats zero", () => {
    expect(formatPercent(0)).toBe("0.0%");
  });

  it("returns N/A for Infinity", () => {
    expect(formatPercent(Infinity)).toBe("N/A");
  });

  it("returns N/A for negative Infinity", () => {
    expect(formatPercent(-Infinity)).toBe("N/A");
  });
});

describe("formatMonthLabel", () => {
  it("returns short month name", () => {
    expect(formatMonthLabel("2026-01")).toBe("Jan");
  });

  it("returns short month name with year", () => {
    expect(formatMonthLabel("2026-01", true)).toBe("Jan '26");
  });

  it("handles December", () => {
    expect(formatMonthLabel("2026-12")).toBe("Dec");
  });
});

describe("formatMonthLabelLong", () => {
  it("returns long month with year", () => {
    expect(formatMonthLabelLong("2026-02")).toBe("February 2026");
  });

  it("handles January", () => {
    expect(formatMonthLabelLong("2026-01")).toBe("January 2026");
  });
});

describe("formatVariance", () => {
  it("formats positive with plus sign", () => {
    expect(formatVariance(100)).toBe("+$100.00");
  });

  it("formats negative with true minus", () => {
    expect(formatVariance(-50)).toBe("−$50.00");
  });
});

describe("shiftMonth", () => {
  it("shifts forward one month", () => {
    expect(shiftMonth("2026-01", 1)).toBe("2026-02");
  });

  it("shifts backward one month", () => {
    expect(shiftMonth("2026-03", -1)).toBe("2026-02");
  });

  it("wraps forward across year boundary", () => {
    expect(shiftMonth("2026-12", 1)).toBe("2027-01");
  });

  it("wraps backward across year boundary", () => {
    expect(shiftMonth("2026-01", -1)).toBe("2025-12");
  });

  it("handles zero delta", () => {
    expect(shiftMonth("2026-06", 0)).toBe("2026-06");
  });

  it("shifts multiple months forward", () => {
    expect(shiftMonth("2026-10", 5)).toBe("2027-03");
  });

  it("shifts multiple months backward", () => {
    expect(shiftMonth("2026-03", -5)).toBe("2025-10");
  });

  it("shifts backward across multiple year boundaries", () => {
    expect(shiftMonth("2026-02", -14)).toBe("2024-12");
  });

  it("computes default 3-month search range from current month", () => {
    const now = "2026-02";
    const from = shiftMonth(now, -2);
    expect(from).toBe("2025-12");
  });
});

describe("currentYear", () => {
  it("returns a four-digit number", () => {
    const year = currentYear();
    expect(year).toBeGreaterThanOrEqual(2026);
    expect(year).toBeLessThan(2100);
  });
});

describe("formatRelativeTime", () => {
  const now = new Date("2026-03-19T20:00:00-07:00").getTime();

  it("renders null/blank/unparseable input as an em dash", () => {
    expect(formatRelativeTime(null, now)).toBe("—");
    expect(formatRelativeTime("", now)).toBe("—");
    expect(formatRelativeTime("not a date", now)).toBe("—");
  });

  it("collapses sub-minute differences to 'just now'", () => {
    expect(formatRelativeTime("2026-03-19T19:59:30-07:00", now)).toBe("just now");
  });

  it("renders minutes, hours, and days ago", () => {
    expect(formatRelativeTime("2026-03-19T19:30:00-07:00", now)).toBe("30m ago");
    expect(formatRelativeTime("2026-03-19T17:00:00-07:00", now)).toBe("3h ago");
    expect(formatRelativeTime("2026-03-17T20:00:00-07:00", now)).toBe("2d ago");
  });

  it("falls back to an absolute short date past a week", () => {
    expect(formatRelativeTime("2026-03-01T12:00:00-07:00", now)).toBe("Mar 1");
  });

  it("never renders a future timestamp as negative time", () => {
    expect(formatRelativeTime("2026-03-19T20:05:00-07:00", now)).toBe("just now");
  });
});
