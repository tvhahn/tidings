import type { TransactionType } from "@/types/api";

/**
 * Every transaction type the API accepts, in picker order. Mirrors
 * `ALL_TRANSACTION_TYPES` in `src/finance/transaction_types.py`; a refund
 * reduces spending and a card payment counts as neither spending nor income.
 */
export const TRANSACTION_TYPES = [
  "purchase",
  "withdrawal",
  "preauth",
  "e-transfer",
  "deposit",
  "refund",
  "card-payment",
] as const satisfies readonly TransactionType[];
