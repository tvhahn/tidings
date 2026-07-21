import { describe, expect, it } from "vitest";
import { suggestFromHistory, type TransactionLike } from "./categorySuggest";

const t = (over: Partial<TransactionLike>): TransactionLike => ({
  company: null,
  category: null,
  ignored: false,
  deleted_at: null,
  ...over,
});

describe("suggestFromHistory", () => {
  it("returns null when there's no history for the merchant", () => {
    const txs = [t({ company: "Costco", category: "groceries" })];
    expect(suggestFromHistory("Safeway", null, txs)).toBeNull();
  });

  it("returns null when only one historical match exists (avoid noise)", () => {
    const txs = [t({ company: "Safeway", category: "groceries" })];
    expect(suggestFromHistory("Safeway", null, txs)).toBeNull();
  });

  it("suggests the most-frequent category for repeat merchants", () => {
    const txs = [
      t({ company: "Safeway", category: "groceries" }),
      t({ company: "Safeway", category: "groceries" }),
      t({ company: "Safeway", category: "household" }),
    ];
    expect(suggestFromHistory("Safeway", null, txs)).toEqual({
      category: "groceries",
      count: 2,
    });
  });

  it("matches across normalized merchant forms (store-number variants)", () => {
    const txs = [
      t({ company: "Safeway #1234", category: "groceries" }),
      t({ company: "Safeway Store 567", category: "groceries" }),
    ];
    expect(suggestFromHistory("Safeway", null, txs)).toEqual({
      category: "groceries",
      count: 2,
    });
  });

  it("excludes the current category from the suggestion (it's already chosen)", () => {
    const txs = [
      t({ company: "Safeway", category: "groceries" }),
      t({ company: "Safeway", category: "groceries" }),
      t({ company: "Safeway", category: "household" }),
      t({ company: "Safeway", category: "household" }),
    ];
    // Current is groceries — should fall back to household (the next-best).
    expect(suggestFromHistory("Safeway", "groceries", txs)).toEqual({
      category: "household",
      count: 2,
    });
  });

  it("ignores deleted and ignored transactions", () => {
    const txs = [
      t({ company: "Safeway", category: "groceries", deleted_at: "2026-04-01" }),
      t({ company: "Safeway", category: "groceries", ignored: true }),
      t({ company: "Safeway", category: "household" }),
    ];
    // Only one un-deleted, un-ignored entry → below MIN_COUNT.
    expect(suggestFromHistory("Safeway", null, txs)).toBeNull();
  });

  it("excludes 'miscellaneous' (a non-decision)", () => {
    const txs = [
      t({ company: "Safeway", category: "miscellaneous" }),
      t({ company: "Safeway", category: "miscellaneous" }),
      t({ company: "Safeway", category: "groceries" }),
    ];
    expect(suggestFromHistory("Safeway", null, txs)).toBeNull();
  });

  it("returns null on empty/null target", () => {
    const txs = [t({ company: "Safeway", category: "groceries" })];
    expect(suggestFromHistory(null, null, txs)).toBeNull();
    expect(suggestFromHistory("", null, txs)).toBeNull();
    expect(suggestFromHistory("   ", null, txs)).toBeNull();
  });

  it("is case-insensitive on merchant matching", () => {
    const txs = [
      t({ company: "SAFEWAY", category: "groceries" }),
      t({ company: "safeway", category: "groceries" }),
    ];
    expect(suggestFromHistory("Safeway", null, txs)).toEqual({
      category: "groceries",
      count: 2,
    });
  });
});
