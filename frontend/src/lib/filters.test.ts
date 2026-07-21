import { describe, expect, it } from "vitest";
import { applyFilters, DEFAULT_FILTERS, type Filters, hasActiveFilters } from "@/lib/filters";
import { makeTxn as txn } from "@/test/factories";
import type { Transaction } from "@/types/api";

const base: Filters = { ...DEFAULT_FILTERS };

describe("applyFilters — categoryGroup", () => {
  const transactions: Transaction[] = [
    txn({ company: "Loblaws", category: "groceries" }),
    txn({ company: "Sushi Place", category: "restaurant/dining" }),
    txn({ company: "Wine Shop", category: "liquor/beer/wine" }),
    txn({ company: "Shell", category: "gasoline" }),
    txn({ company: "Random", category: "miscellaneous" }),
  ];

  it("filters by group including all categories in the group", () => {
    const filters: Filters = { ...base, categoryGroup: "Food & Dining" };
    const result = applyFilters(transactions, filters);
    expect(result).toHaveLength(3);
    expect(result.map((t) => t.company)).toEqual(["Loblaws", "Sushi Place", "Wine Shop"]);
  });

  it("Other group catches ungrouped categories", () => {
    const filters: Filters = { ...base, categoryGroup: "Other" };
    const result = applyFilters(transactions, filters);
    expect(result).toHaveLength(1);
    expect(result[0]!.company).toBe("Random");
  });

  it("categoryGroup takes precedence over category", () => {
    const filters: Filters = { ...base, category: "gasoline", categoryGroup: "Food & Dining" };
    const result = applyFilters(transactions, filters);
    expect(result).toHaveLength(3);
    // group filter wins, category is ignored
    expect(result.map((t) => t.category)).toEqual([
      "groceries",
      "restaurant/dining",
      "liquor/beer/wine",
    ]);
  });

  it("individual category filter still works when no group set", () => {
    const filters: Filters = { ...base, category: "gasoline" };
    const result = applyFilters(transactions, filters);
    expect(result).toHaveLength(1);
    expect(result[0]!.company).toBe("Shell");
  });

  it("Transport group matches gasoline", () => {
    const filters: Filters = { ...base, categoryGroup: "Transport" };
    const result = applyFilters(transactions, filters);
    expect(result).toHaveLength(1);
    expect(result[0]!.company).toBe("Shell");
  });
});

describe("applyFilters — search (company OR comment OR category)", () => {
  const transactions: Transaction[] = [
    txn({ company: "Loblaws", comment: "weekly run", category: "groceries" }),
    txn({ company: "Shell", comment: "road trip fuel", category: "gasoline" }),
    txn({ company: "Sushi Place", comment: "birthday dinner", category: "restaurant/dining" }),
  ];

  it("matches on company", () => {
    const result = applyFilters(transactions, { ...base, search: "loblaws" });
    expect(result).toHaveLength(1);
    expect(result[0]!.company).toBe("Loblaws");
  });

  it("matches on comment", () => {
    const result = applyFilters(transactions, { ...base, search: "birthday" });
    expect(result).toHaveLength(1);
    expect(result[0]!.company).toBe("Sushi Place");
  });

  it("matches on category", () => {
    const result = applyFilters(transactions, { ...base, search: "gasoline" });
    expect(result).toHaveLength(1);
    expect(result[0]!.company).toBe("Shell");
  });

  it("excludes when needle matches none of the three fields", () => {
    const result = applyFilters(transactions, { ...base, search: "airfare" });
    expect(result).toHaveLength(0);
  });
});

describe("applyFilters — hideDeposits", () => {
  const transactions: Transaction[] = [
    txn({ company: "Loblaws", transaction_type: "purchase" }),
    txn({ company: "ATM", transaction_type: "withdrawal" }),
    txn({ company: "Payroll", transaction_type: "deposit" }),
    txn({ company: "Mom", transaction_type: "e-transfer" }),
    txn({ company: "Auth", transaction_type: "preauth" }),
  ];

  it("hides deposit type when hideDeposits is true", () => {
    const filters: Filters = { ...base, hideDeposits: true };
    const result = applyFilters(transactions, filters);
    expect(result).toHaveLength(4);
    expect(result.map((t) => t.company)).toEqual(["Loblaws", "ATM", "Mom", "Auth"]);
  });

  it("keeps e-transfers visible when hideDeposits is true", () => {
    const filters: Filters = { ...base, hideDeposits: true };
    const result = applyFilters(transactions, filters);
    expect(result.find((t) => t.transaction_type === "e-transfer")).toBeDefined();
  });

  it("shows all types when hideDeposits is false", () => {
    const filters: Filters = { ...base, hideDeposits: false };
    const result = applyFilters(transactions, filters);
    expect(result).toHaveLength(5);
  });
});

describe("applyFilters — hideIgnored", () => {
  const transactions: Transaction[] = [
    txn({ company: "Active1", ignored: false }),
    txn({ company: "Active2", ignored: false }),
    txn({ company: "Ignored1", ignored: true }),
  ];

  it("hides ignored transactions when hideIgnored is true", () => {
    const filters: Filters = { ...base, hideIgnored: true };
    const result = applyFilters(transactions, filters);
    expect(result).toHaveLength(2);
    expect(result.map((t) => t.company)).toEqual(["Active1", "Active2"]);
  });

  it("shows ignored transactions when hideIgnored is false", () => {
    const filters: Filters = { ...base, hideIgnored: false };
    const result = applyFilters(transactions, filters);
    expect(result).toHaveLength(3);
  });
});

describe("applyFilters — combined toggles", () => {
  const transactions: Transaction[] = [
    txn({ company: "Purchase", transaction_type: "purchase", ignored: false }),
    txn({ company: "Deposit", transaction_type: "deposit", ignored: false }),
    txn({ company: "IgnoredPurchase", transaction_type: "purchase", ignored: true }),
    txn({ company: "IgnoredDeposit", transaction_type: "deposit", ignored: true }),
  ];

  it("hides both deposits and ignored when both toggles are true", () => {
    const filters: Filters = { ...base, hideDeposits: true, hideIgnored: true };
    const result = applyFilters(transactions, filters);
    expect(result).toHaveLength(1);
    expect(result[0]!.company).toBe("Purchase");
  });

  it("combines with category filter", () => {
    const txns = [
      txn({ company: "Groceries", category: "groceries", transaction_type: "purchase" }),
      txn({ company: "Dining", category: "restaurant/dining", transaction_type: "purchase" }),
      txn({ company: "Payroll", category: "groceries", transaction_type: "deposit" }),
    ];
    const filters: Filters = { ...base, category: "groceries", hideDeposits: true };
    const result = applyFilters(txns, filters);
    expect(result).toHaveLength(1);
    expect(result[0]!.company).toBe("Groceries");
  });
});

describe("hasActiveFilters", () => {
  it("returns false when all filters are defaults", () => {
    expect(hasActiveFilters(DEFAULT_FILTERS)).toBe(false);
  });

  it("returns false for a spread copy of defaults", () => {
    expect(hasActiveFilters({ ...DEFAULT_FILTERS })).toBe(false);
  });

  it("returns true when category differs", () => {
    expect(hasActiveFilters({ ...DEFAULT_FILTERS, category: "groceries" })).toBe(true);
  });

  it("returns true when categoryGroup is set", () => {
    expect(hasActiveFilters({ ...DEFAULT_FILTERS, categoryGroup: "Food & Dining" })).toBe(true);
  });

  it("returns true when institution differs", () => {
    expect(hasActiveFilters({ ...DEFAULT_FILTERS, institution: "rbc" })).toBe(true);
  });

  it("returns true when search is non-empty", () => {
    expect(hasActiveFilters({ ...DEFAULT_FILTERS, search: "loblaws" })).toBe(true);
  });

  it("returns true when hideDeposits is true", () => {
    expect(hasActiveFilters({ ...DEFAULT_FILTERS, hideDeposits: true })).toBe(true);
  });

  it("returns true when hideIgnored is true", () => {
    expect(hasActiveFilters({ ...DEFAULT_FILTERS, hideIgnored: true })).toBe(true);
  });

  it("returns true when multiple filters are active", () => {
    expect(
      hasActiveFilters({ ...DEFAULT_FILTERS, category: "groceries", hideDeposits: true })
    ).toBe(true);
  });
});
