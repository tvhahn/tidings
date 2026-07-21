import type { Transaction } from "@/types/api";

export type SortColumn = "date" | "company" | "amount" | "category" | "institution" | "type";
export type SortDirection = "asc" | "desc";
export interface SortConfig {
  column: SortColumn;
  direction: SortDirection;
}

export const DEFAULT_SORT: SortConfig = { column: "date", direction: "desc" };

const FIELD_MAP: Record<SortColumn, keyof Transaction> = {
  date: "date_file_name",
  company: "company",
  amount: "amount",
  category: "category",
  institution: "institution",
  type: "transaction_type",
};

export function sortTransactions(transactions: Transaction[], sort: SortConfig): Transaction[] {
  const field = FIELD_MAP[sort.column];
  const dir = sort.direction === "asc" ? 1 : -1;

  return [...transactions].sort((a, b) => {
    const av = a[field];
    const bv = b[field];

    // Nulls always sort to bottom regardless of direction
    if (av == null && bv == null) return 0;
    if (av == null) return 1;
    if (bv == null) return -1;

    if (sort.column === "amount") {
      return ((av as number) - (bv as number)) * dir;
    }

    // String comparison (case-insensitive)
    return String(av).localeCompare(String(bv), undefined, { sensitivity: "base" }) * dir;
  });
}
