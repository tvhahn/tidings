import { describe, expect, it } from "vitest";
import { makeTxn } from "@/test/factories";
import type { SearchResponse, Transaction } from "@/types/api";
import {
  aggregateMerchantAnswer,
  daysRemainingInMonth,
  parseMonthToken,
  parseOmniQuery,
  type OmniIntent,
} from "./omniQuery";

// June 2026 is the reference "now" for bare-month resolution throughout.
const NOW = { year: 2026, month: 6 };

describe("parseMonthToken", () => {
  const cases: Array<{ input: string; expected: string | null; desc: string }> = [
    { input: "march", expected: "2026-03", desc: "bare full month <= now resolves this year" },
    { input: "mar", expected: "2026-03", desc: "bare abbreviation resolves this year" },
    { input: "mar 2025", expected: "2025-03", desc: "abbreviation with explicit year" },
    { input: "march 2025", expected: "2025-03", desc: "full month with explicit year" },
    { input: "2026-03", expected: "2026-03", desc: "explicit YYYY-MM" },
    { input: "june", expected: "2026-06", desc: "month equal to now resolves this year" },
    { input: "december", expected: "2025-12", desc: "bare month > now resolves last year" },
    { input: "MARCH", expected: "2026-03", desc: "case-insensitive" },
    { input: "  march  ", expected: "2026-03", desc: "surrounding whitespace tolerated" },
    { input: "marchh", expected: null, desc: "garbage month name" },
    { input: "2026-13", expected: null, desc: "out-of-range month number" },
    { input: "2026-00", expected: null, desc: "zero month number" },
    { input: "", expected: null, desc: "empty input" },
    { input: "costco", expected: null, desc: "non-month word" },
  ];

  for (const { input, expected, desc } of cases) {
    it(`${desc}: "${input}" -> ${expected}`, () => {
      expect(parseMonthToken(input, NOW)).toBe(expected);
    });
  }
});

describe("parseOmniQuery", () => {
  const categories = ["Dining", "Dining Out", "Groceries", "Transport"];
  const ctx = { categories, now: NOW };

  const cases: Array<{ input: string; expected: OmniIntent; desc: string }> = [
    {
      input: ">100",
      expected: { kind: "amount", minAmount: 100 },
      desc: "amount min, no space",
    },
    {
      input: "> 100",
      expected: { kind: "amount", minAmount: 100 },
      desc: "amount min, with space",
    },
    {
      input: "<50",
      expected: { kind: "amount", maxAmount: 50 },
      desc: "amount max",
    },
    {
      input: "> 50 march",
      expected: { kind: "amount", minAmount: 50, month: "2026-03" },
      desc: "amount + month combo",
    },
    {
      input: "< 25",
      expected: { kind: "amount", maxAmount: 25 },
      desc: "amount max, with space",
    },
    {
      input: "<100 march 2025",
      expected: { kind: "amount", maxAmount: 100, month: "2025-03" },
      desc: "amount max + explicit-year month combo",
    },
    {
      input: ">100 notamonth",
      expected: { kind: "amount", minAmount: 100 },
      desc: "amount with unparseable trailing token ignores the month",
    },
    {
      input: ">12.50",
      expected: { kind: "amount", minAmount: 12.5 },
      desc: "decimal amount",
    },
    {
      input: "< abc",
      expected: { kind: "merchant", query: "< abc" },
      desc: "malformed max amount falls through to merchant",
    },
    {
      input: "dining",
      expected: { kind: "category", name: "Dining" },
      desc: "category prefix, shorter-name tie-break",
    },
    {
      input: "march",
      expected: { kind: "month", month: "2026-03" },
      desc: "bare month token classifies as month",
    },
    {
      input: "2026-03",
      expected: { kind: "month", month: "2026-03" },
      desc: "explicit YYYY-MM classifies as month",
    },
    {
      input: "cost",
      expected: { kind: "merchant", query: "cost" },
      desc: "no category match falls through to merchant",
    },
    {
      input: ">abc",
      expected: { kind: "merchant", query: ">abc" },
      desc: "malformed amount falls through to merchant",
    },
    {
      input: "  groceries  ",
      expected: { kind: "category", name: "Groceries" },
      desc: "input is trimmed before classification",
    },
  ];

  for (const { input, expected, desc } of cases) {
    it(`${desc}: "${input}"`, () => {
      expect(parseOmniQuery(input, ctx)).toEqual(expected);
    });
  }

  it("returns an empty merchant intent for empty input", () => {
    expect(parseOmniQuery("   ", ctx)).toEqual({ kind: "merchant", query: "" });
  });

  it("amount precedence beats a category that would otherwise match", () => {
    const intent = parseOmniQuery(">100", { categories: ["100 club"], now: NOW });
    expect(intent.kind).toBe("amount");
  });
});

describe("aggregateMerchantAnswer", () => {
  function makeSearchResponse(
    transactions: Transaction[],
    overrides: Partial<SearchResponse> = {}
  ): SearchResponse {
    return {
      capped: false,
      total_matching: transactions.length,
      transactions,
      summary: {
        avg_amount: 0,
        by_category: {},
        months_queried: 12,
        total_amount: 0,
        total_count: transactions.length,
      },
      ...overrides,
    };
  }

  it("rolls up count, window total, current-month subtotal, and dominant category", () => {
    const resp = makeSearchResponse([
      makeTxn({ date: "03/05/2026 12:00 PST", amount: 100, category: "Groceries" }),
      makeTxn({ date: "03/20/2026 12:00 PST", amount: 50, category: "Groceries" }),
      makeTxn({ date: "01/10/2026 12:00 PST", amount: 30, category: "Dining" }),
    ]);

    const answer = aggregateMerchantAnswer(resp, "2026-03");

    expect(answer.visitCount).toBe(3);
    expect(answer.totalAmount).toBe(180);
    expect(answer.currentMonthAmount).toBe(150);
    expect(answer.dominantCategory).toBe("Groceries");
    expect(answer.capped).toBe(false);
    expect(answer.totalMatching).toBe(3);
  });

  it("uses total_matching as the visit count when capped, and passes capped through", () => {
    const resp = makeSearchResponse(
      [
        makeTxn({ date: "03/05/2026 12:00 PST", amount: 10, category: "Groceries" }),
        makeTxn({ date: "03/06/2026 12:00 PST", amount: 20, category: "Groceries" }),
      ],
      { capped: true, total_matching: 87 }
    );

    const answer = aggregateMerchantAnswer(resp, "2026-03");

    expect(answer.capped).toBe(true);
    expect(answer.totalMatching).toBe(87);
    expect(answer.visitCount).toBe(87);
    // Totals still reflect only the returned (partial) window.
    expect(answer.totalAmount).toBe(30);
    expect(answer.currentMonthAmount).toBe(30);
  });

  it("treats null amounts as zero and null categories as no vote", () => {
    const resp = makeSearchResponse([
      makeTxn({ date: "03/05/2026 12:00 PST", amount: null, category: null }),
      makeTxn({ date: "03/06/2026 12:00 PST", amount: 40, category: "Dining" }),
    ]);

    const answer = aggregateMerchantAnswer(resp, "2026-03");

    expect(answer.totalAmount).toBe(40);
    expect(answer.dominantCategory).toBe("Dining");
  });

  it("returns null dominant category for an empty result set", () => {
    const resp = makeSearchResponse([]);
    const answer = aggregateMerchantAnswer(resp, "2026-03");
    expect(answer.visitCount).toBe(0);
    expect(answer.totalAmount).toBe(0);
    expect(answer.currentMonthAmount).toBe(0);
    expect(answer.dominantCategory).toBeNull();
    expect(answer.merchantName).toBeNull();
    expect(answer.merchantCount).toBe(0);
  });

  it("collapses store-number variants into one normalized merchant name", () => {
    const resp = makeSearchResponse([
      makeTxn({ company: "SAFEWAY #1234" }),
      makeTxn({ company: "SAFEWAY #9" }),
      makeTxn({ company: "Safeway" }), // case-insensitive grouping; first-seen casing wins
    ]);

    const answer = aggregateMerchantAnswer(resp, "2026-03");

    expect(answer.merchantName).toBe("SAFEWAY");
    expect(answer.merchantCount).toBe(1);
  });

  it("picks the most frequent merchant and counts distinct names", () => {
    const resp = makeSearchResponse([
      makeTxn({ company: "COSTCO WHOLESALE #45" }),
      makeTxn({ company: "COSTCO WHOLESALE #103" }),
      makeTxn({ company: "COSTCO GAS" }),
    ]);

    const answer = aggregateMerchantAnswer(resp, "2026-03");

    expect(answer.merchantName).toBe("COSTCO WHOLESALE");
    expect(answer.merchantCount).toBe(2);
  });
});

describe("daysRemainingInMonth", () => {
  it("counts remaining days within the current month", () => {
    // 2026-06 has 30 days; on the 9th, 21 remain.
    expect(daysRemainingInMonth({ todayLocal: "2026-06-09" }, "2026-06")).toBe(21);
  });

  it("returns 0 for a fully-elapsed past month", () => {
    expect(daysRemainingInMonth({ todayLocal: "2026-06-09" }, "2026-05")).toBe(0);
  });

  it("returns the full month for a future month", () => {
    // 2026-07 has 31 days, none elapsed when today is in June.
    expect(daysRemainingInMonth({ todayLocal: "2026-06-09" }, "2026-07")).toBe(31);
  });

  it("returns 0 on the last day of the month", () => {
    expect(daysRemainingInMonth({ todayLocal: "2026-06-30" }, "2026-06")).toBe(0);
  });

  it("handles February in a non-leap year", () => {
    expect(daysRemainingInMonth({ todayLocal: "2026-02-10" }, "2026-02")).toBe(18);
  });
});
