import { describe, it, expect } from "vitest";
import type { StatementDetailResponse } from "@/types/api";
import { transformDetailToUploadFormat } from "./statementTransform";

type DetailTxn = StatementDetailResponse["transactions"][number];

function makeDetailTxn(overrides: Partial<DetailTxn> = {}): DetailTxn {
  return {
    acted_at: null,
    action: "pending",
    action_result: null,
    amount: 12.34,
    balance: 100,
    candidates: null,
    cleaned_description: "Cleaned",
    company_differs: false,
    date: "2026-04-01",
    db_amount: null,
    db_category: null,
    db_company: null,
    db_date_file_name: null,
    db_forwarded_to: null,
    db_transaction_type: null,
    edited_category: null,
    edited_company: null,
    enrichable: false,
    raw_description: "RAW DESCRIPTION",
    reason: null,
    reconcile_tier: "new",
    row_id: "row-1",
    suggested_category: "groceries",
    tx_index: 0,
    type: "withdrawal",
    ...overrides,
  } as DetailTxn;
}

function makeDetail(
  transactions: DetailTxn[],
  overrides: Partial<StatementDetailResponse> = {}
): StatementDetailResponse {
  return {
    id: "stmt-1",
    institution: "RBC",
    account_type: "chequing",
    period_start: "2026-04-01",
    period_end: "2026-04-30",
    filename: "stmt.pdf",
    status: "complete",
    total_parsed: transactions.length,
    matched_count: 0,
    ambiguous_count: 0,
    suspected_duplicate_count: 0,
    new_count: 0,
    previously_imported_count: 0,
    imported_count: 0,
    enriched_count: 0,
    updated_count: 0,
    skipped_count: 0,
    duplicate_count: 0,
    transactions,
    completed_at: null,
    updated_at: "2026-04-30T00:00:00Z",
    uploaded_at: "2026-04-30T00:00:00Z",
    ...overrides,
  } as StatementDetailResponse;
}

describe("transformDetailToUploadFormat", () => {
  it("returns empty buckets for an empty detail", () => {
    const result = transformDetailToUploadFormat(makeDetail([]));
    expect(result.matched).toEqual([]);
    expect(result.ambiguous).toEqual([]);
    expect(result.new).toEqual([]);
    expect(result.previously_imported).toEqual([]);
    expect(result.suspected_duplicates).toEqual([]);
    expect(result.transactions).toEqual([]);
  });

  it("routes each reconcile_tier into the matching bucket", () => {
    const detail = makeDetail([
      makeDetailTxn({ tx_index: 0, reconcile_tier: "matched", row_id: "m" }),
      makeDetailTxn({ tx_index: 1, reconcile_tier: "ambiguous", row_id: "a" }),
      makeDetailTxn({ tx_index: 2, reconcile_tier: "new", row_id: "n" }),
      makeDetailTxn({ tx_index: 3, reconcile_tier: "previously_imported", row_id: "p" }),
      makeDetailTxn({ tx_index: 4, reconcile_tier: "suspected_duplicate", row_id: "s" }),
    ]);
    const result = transformDetailToUploadFormat(detail);
    expect(result.matched.map((t) => t.row_id)).toEqual(["m"]);
    expect(result.ambiguous.map((t) => t.row_id)).toEqual(["a"]);
    expect(result.new.map((t) => t.row_id)).toEqual(["n"]);
    expect(result.previously_imported.map((t) => t.row_id)).toEqual(["p"]);
    expect(result.suspected_duplicates.map((t) => t.row_id)).toEqual(["s"]);
  });

  it("prefers edited_company / edited_category over raw values", () => {
    const detail = makeDetail([
      makeDetailTxn({
        reconcile_tier: "new",
        raw_description: "RAW",
        edited_company: "Edited Co",
        suggested_category: "groceries",
        edited_category: "dining",
      }),
    ]);
    const result = transformDetailToUploadFormat(detail);
    expect(result.new[0]?.raw_description).toBe("Edited Co");
    expect(result.new[0]?.suggested_category).toBe("dining");
  });

  it("falls back to raw values when no edits", () => {
    const detail = makeDetail([
      makeDetailTxn({
        reconcile_tier: "new",
        raw_description: "RAW",
        edited_company: null,
        suggested_category: "groceries",
        edited_category: null,
      }),
    ]);
    const result = transformDetailToUploadFormat(detail);
    expect(result.new[0]?.raw_description).toBe("RAW");
    expect(result.new[0]?.suggested_category).toBe("groceries");
  });

  it("propagates summary counts from the detail", () => {
    const detail = makeDetail([], {
      total_parsed: 10,
      matched_count: 4,
      ambiguous_count: 2,
      new_count: 3,
      previously_imported_count: 1,
      imported_count: 7,
      enriched_count: 1,
      updated_count: 0,
      skipped_count: 2,
      duplicate_count: 1,
      suspected_duplicate_count: 0,
    });
    const result = transformDetailToUploadFormat(detail);
    expect(result.summary).toMatchObject({
      total_parsed: 10,
      matched_count: 4,
      ambiguous_count: 2,
      new_count: 3,
      imported_count: 7,
    });
  });

  it("normalizes nullable db_match fields to empty-string defaults on matched", () => {
    const detail = makeDetail([
      makeDetailTxn({
        reconcile_tier: "matched",
        db_forwarded_to: null,
        db_company: null,
        db_amount: null,
        db_category: null,
      }),
    ]);
    const result = transformDetailToUploadFormat(detail);
    expect(result.matched[0]?.db_match).toEqual({
      forwarded_to: "",
      date_file_name: "",
      company: "",
      amount: 0,
      category: "",
    });
  });
});
