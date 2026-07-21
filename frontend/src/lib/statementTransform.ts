import type { StatementDetailResponse, StatementUploadResponse } from "@/types/api";

/**
 * Transform a `StatementDetailResponse` (returned when resuming a statement
 * from history) into the `StatementUploadResponse` shape that
 * `StatementReview` expects (returned by a fresh upload). Pure function;
 * separating it from the page module makes it testable and keeps page-level
 * routing decoupled from statement-domain reshaping.
 */
export function transformDetailToUploadFormat(
  detail: StatementDetailResponse
): StatementUploadResponse {
  const matched = detail.transactions
    .filter((t) => t.reconcile_tier === "matched")
    .map((t) => ({
      index: t.tx_index,
      row_id: t.row_id,
      statement_txn: {
        date: t.date,
        description: t.raw_description,
        cleaned_description: t.cleaned_description,
        amount: t.amount,
        type: t.type as "withdrawal" | "deposit",
        balance: t.balance,
      },
      db_match: {
        forwarded_to: t.db_forwarded_to ?? "",
        date_file_name: t.db_date_file_name ?? "",
        company: t.db_company ?? "",
        amount: t.db_amount ?? 0,
        category: t.db_category ?? "",
      },
      company_differs: t.company_differs,
      cleaned_description: t.cleaned_description,
      raw_description: t.edited_company ?? t.raw_description,
      suggested_category: t.edited_category ?? t.suggested_category,
    }));

  const ambiguous = detail.transactions
    .filter((t) => t.reconcile_tier === "ambiguous")
    .map((t) => ({
      index: t.tx_index,
      row_id: t.row_id,
      statement_txn: {
        date: t.date,
        description: t.raw_description,
        cleaned_description: t.cleaned_description,
        amount: t.amount,
        type: t.type as "withdrawal" | "deposit",
        balance: t.balance,
      },
      candidates: t.candidates ?? [],
      reason: t.reason ?? "",
      cleaned_description: t.cleaned_description,
      raw_description: t.edited_company ?? t.raw_description,
      suggested_category: t.edited_category ?? t.suggested_category,
      enrichable: t.enrichable,
    }));

  const newItems = detail.transactions
    .filter((t) => t.reconcile_tier === "new")
    .map((t) => ({
      index: t.tx_index,
      row_id: t.row_id,
      statement_txn: {
        date: t.date,
        description: t.raw_description,
        cleaned_description: t.cleaned_description,
        amount: t.amount,
        type: t.type as "withdrawal" | "deposit",
        balance: t.balance,
      },
      cleaned_description: t.cleaned_description,
      raw_description: t.edited_company ?? t.raw_description,
      suggested_category: t.edited_category ?? t.suggested_category,
    }));

  const previouslyImported = detail.transactions
    .filter((t) => t.reconcile_tier === "previously_imported")
    .map((t) => ({
      index: t.tx_index,
      row_id: t.row_id,
      statement_txn: {
        date: t.date,
        description: t.raw_description,
        cleaned_description: t.cleaned_description,
        amount: t.amount,
        type: t.type as "withdrawal" | "deposit",
        balance: t.balance,
      },
      db_match: {
        forwarded_to: t.db_forwarded_to ?? "",
        date_file_name: t.db_date_file_name ?? "",
        company: t.db_company ?? "",
        amount: t.db_amount ?? 0,
        category: t.db_category ?? "",
      },
      cleaned_description: t.cleaned_description,
      raw_description: t.edited_company ?? t.raw_description,
      suggested_category: t.edited_category ?? t.suggested_category,
    }));

  const suspectedDuplicates = detail.transactions
    .filter((t) => t.reconcile_tier === "suspected_duplicate")
    .map((t) => ({
      index: t.tx_index,
      row_id: t.row_id,
      statement_txn: {
        date: t.date,
        description: t.raw_description,
        cleaned_description: t.cleaned_description,
        amount: t.amount,
        type: t.type as "withdrawal" | "deposit",
        balance: t.balance,
      },
      db_match: {
        forwarded_to: t.db_forwarded_to ?? "",
        date_file_name: t.db_date_file_name ?? "",
        company: t.db_company ?? "",
        amount: t.db_amount ?? 0,
        category: t.db_category ?? "",
        transaction_type: t.db_transaction_type ?? "",
      },
      cleaned_description: t.cleaned_description,
      raw_description: t.edited_company ?? t.raw_description,
      suggested_category: t.edited_category ?? t.suggested_category,
      reason: t.reason ?? "",
    }));

  return {
    statement_id: detail.id,
    transactions: detail.transactions.map((t) => ({
      date: t.date,
      description: t.raw_description,
      cleaned_description: t.cleaned_description,
      amount: t.amount,
      type: t.type as "withdrawal" | "deposit",
      balance: t.balance,
    })),
    metadata: {
      institution: detail.institution,
      account_type: detail.account_type,
      period_start: detail.period_start,
      period_end: detail.period_end,
      transaction_count: detail.total_parsed,
      parsed_with_ai: detail.parsed_with_ai,
    },
    matched,
    ambiguous,
    suspected_duplicates: suspectedDuplicates,
    new: newItems,
    previously_imported: previouslyImported,
    summary: {
      total_parsed: detail.total_parsed,
      matched_count: detail.matched_count,
      ambiguous_count: detail.ambiguous_count,
      suspected_duplicate_count: detail.suspected_duplicate_count,
      new_count: detail.new_count,
      previously_imported_count: detail.previously_imported_count,
      imported_count: detail.imported_count,
      enriched_count: detail.enriched_count,
      updated_count: detail.updated_count,
      skipped_count: detail.skipped_count,
      duplicate_count: detail.duplicate_count,
    },
  };
}
