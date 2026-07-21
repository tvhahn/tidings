import { describe, expect, it } from "vitest";
import { makeTxn as txn } from "@/test/factories";
import { sortTransactions } from "./sort";

describe("sortTransactions", () => {
  it("sorts by date descending (default behavior)", () => {
    const items = [
      txn({ date_file_name: "2026.02.01_10.00_a.eml", company: "A" }),
      txn({ date_file_name: "2026.02.03_10.00_c.eml", company: "C" }),
      txn({ date_file_name: "2026.02.02_10.00_b.eml", company: "B" }),
    ];
    const sorted = sortTransactions(items, { column: "date", direction: "desc" });
    expect(sorted.map((t) => t.company)).toEqual(["C", "B", "A"]);
  });

  it("sorts by date ascending", () => {
    const items = [
      txn({ date_file_name: "2026.02.03_10.00_c.eml", company: "C" }),
      txn({ date_file_name: "2026.02.01_10.00_a.eml", company: "A" }),
      txn({ date_file_name: "2026.02.02_10.00_b.eml", company: "B" }),
    ];
    const sorted = sortTransactions(items, { column: "date", direction: "asc" });
    expect(sorted.map((t) => t.company)).toEqual(["A", "B", "C"]);
  });

  it("sorts by amount ascending", () => {
    const items = [
      txn({ amount: 50, company: "B" }),
      txn({ amount: 10, company: "A" }),
      txn({ amount: 30, company: "C" }),
    ];
    const sorted = sortTransactions(items, { column: "amount", direction: "asc" });
    expect(sorted.map((t) => t.company)).toEqual(["A", "C", "B"]);
  });

  it("sorts by amount descending", () => {
    const items = [
      txn({ amount: 10, company: "A" }),
      txn({ amount: 50, company: "B" }),
      txn({ amount: 30, company: "C" }),
    ];
    const sorted = sortTransactions(items, { column: "amount", direction: "desc" });
    expect(sorted.map((t) => t.company)).toEqual(["B", "C", "A"]);
  });

  it("sorts by company ascending (case-insensitive)", () => {
    const items = [
      txn({ company: "Zara" }),
      txn({ company: "apple" }),
      txn({ company: "McDonald's" }),
    ];
    const sorted = sortTransactions(items, { column: "company", direction: "asc" });
    expect(sorted.map((t) => t.company)).toEqual(["apple", "McDonald's", "Zara"]);
  });

  it("sorts by company descending", () => {
    const items = [
      txn({ company: "Apple" }),
      txn({ company: "Zara" }),
      txn({ company: "McDonald's" }),
    ];
    const sorted = sortTransactions(items, { column: "company", direction: "desc" });
    expect(sorted.map((t) => t.company)).toEqual(["Zara", "McDonald's", "Apple"]);
  });

  it("sorts by category ascending", () => {
    const items = [
      txn({ category: "travel", company: "C" }),
      txn({ category: "groceries", company: "A" }),
      txn({ category: "restaurant/dining", company: "B" }),
    ];
    const sorted = sortTransactions(items, { column: "category", direction: "asc" });
    expect(sorted.map((t) => t.company)).toEqual(["A", "B", "C"]);
  });

  it("sorts by institution ascending", () => {
    const items = [
      txn({ institution: "RBC", company: "B" }),
      txn({ institution: "CIBC", company: "A" }),
      txn({ institution: "MBNA", company: "C" }),
    ];
    const sorted = sortTransactions(items, { column: "institution", direction: "asc" });
    expect(sorted.map((t) => t.company)).toEqual(["A", "C", "B"]);
  });

  it("sorts by type ascending", () => {
    const items = [
      txn({ transaction_type: "withdrawal", company: "C" }),
      txn({ transaction_type: "e-transfer", company: "A" }),
      txn({ transaction_type: "purchase", company: "B" }),
    ];
    const sorted = sortTransactions(items, { column: "type", direction: "asc" });
    expect(sorted.map((t) => t.company)).toEqual(["A", "B", "C"]);
  });

  it("null values sort to bottom regardless of direction (asc)", () => {
    const items = [
      txn({ amount: null, company: "Null" }),
      txn({ amount: 10, company: "A" }),
      txn({ amount: 5, company: "B" }),
    ];
    const sorted = sortTransactions(items, { column: "amount", direction: "asc" });
    expect(sorted.map((t) => t.company)).toEqual(["B", "A", "Null"]);
  });

  it("null values sort to bottom regardless of direction (desc)", () => {
    const items = [
      txn({ amount: null, company: "Null" }),
      txn({ amount: 10, company: "A" }),
      txn({ amount: 5, company: "B" }),
    ];
    const sorted = sortTransactions(items, { column: "amount", direction: "desc" });
    expect(sorted.map((t) => t.company)).toEqual(["A", "B", "Null"]);
  });

  it("null string values sort to bottom", () => {
    const items = [txn({ company: null }), txn({ company: "Apple" }), txn({ company: "Zara" })];
    const sorted = sortTransactions(items, { column: "company", direction: "asc" });
    expect(sorted.map((t) => t.company)).toEqual(["Apple", "Zara", null]);
  });

  it("multiple nulls stay at bottom", () => {
    const items = [
      txn({ company: null, date_file_name: "2026.02.01_a.eml" }),
      txn({ company: "Apple", date_file_name: "2026.02.02_b.eml" }),
      txn({ company: null, date_file_name: "2026.02.03_c.eml" }),
    ];
    const sorted = sortTransactions(items, { column: "company", direction: "asc" });
    expect(sorted[0]!.company).toBe("Apple");
    expect(sorted[1]!.company).toBeNull();
    expect(sorted[2]!.company).toBeNull();
  });

  it("stable sort — equal values maintain relative order", () => {
    const items = [
      txn({ category: "groceries", company: "First" }),
      txn({ category: "groceries", company: "Second" }),
      txn({ category: "groceries", company: "Third" }),
    ];
    const sorted = sortTransactions(items, { column: "category", direction: "asc" });
    expect(sorted.map((t) => t.company)).toEqual(["First", "Second", "Third"]);
  });

  it("does not mutate original array", () => {
    const items = [txn({ amount: 50, company: "B" }), txn({ amount: 10, company: "A" })];
    const original = [...items];
    sortTransactions(items, { column: "amount", direction: "asc" });
    expect(items.map((t) => t.company)).toEqual(original.map((t) => t.company));
  });

  it("handles empty array", () => {
    const sorted = sortTransactions([], { column: "date", direction: "desc" });
    expect(sorted).toEqual([]);
  });

  it("handles single item", () => {
    const items = [txn({ company: "Solo" })];
    const sorted = sortTransactions(items, { column: "company", direction: "asc" });
    expect(sorted).toHaveLength(1);
    expect(sorted[0]!.company).toBe("Solo");
  });

  describe("locale edge cases", () => {
    // Pins `sensitivity: "base"` behavior: accents, case, and French ligatures
    // are all folded to the same key, so stable input order wins on ties.
    it("treats accented and unaccented characters as equal (stable)", () => {
      const items = [txn({ company: "café", amount: 1 }), txn({ company: "cafe", amount: 2 })];
      const sorted = sortTransactions(items, { column: "company", direction: "asc" });
      expect(sorted.map((t) => t.amount)).toEqual([1, 2]);
    });

    it("is case-insensitive across unicode letters", () => {
      const items = [txn({ company: "Über" }), txn({ company: "apple" }), txn({ company: "über" })];
      const sorted = sortTransactions(items, { column: "company", direction: "asc" });
      expect(sorted[0]!.company).toBe("apple");
      // Über and über tie under sensitivity:base and stay in input order
      expect(sorted[1]!.company).toBe("Über");
      expect(sorted[2]!.company).toBe("über");
    });

    it("folds French ligatures to their multi-char equivalent", () => {
      const items = [txn({ company: "œuvre", amount: 1 }), txn({ company: "oeuvre", amount: 2 })];
      const sorted = sortTransactions(items, { column: "company", direction: "asc" });
      // œ == oe under sensitivity:base — stable sort keeps input order
      expect(sorted.map((t) => t.amount)).toEqual([1, 2]);
    });

    it("orders non-tie unicode pairs correctly", () => {
      const items = [txn({ company: "dance" }), txn({ company: "café" })];
      const sorted = sortTransactions(items, { column: "company", direction: "asc" });
      expect(sorted.map((t) => t.company)).toEqual(["café", "dance"]);
    });
  });
});
