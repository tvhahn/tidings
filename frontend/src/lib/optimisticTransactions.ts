import type { QueryClient, QueryKey } from "@tanstack/react-query";
import { queryKeys } from "@/lib/queryConfigs";
import type { CombinedTransactionsResponse, Transaction } from "@/types/api";

/**
 * Optimistic updates for the `["transactions-combined", month]` cache.
 *
 * The Transactions page renders `useTransactions(month)`, which reads the
 * combined query and only *seeds* the flat `transactions` / `attention` /
 * `trash` caches from it. TanStack prefix matching treats
 * `"transactions-combined"` as a distinct key from `"transactions"`, so a
 * mutation that only touches `queryKeys.prefix("transactions")` never reaches
 * the rows on screen — and the seeding effect later overwrites the flat caches
 * with the stale combined data. Every transaction-mutating hook therefore
 * runs its optimistic change through these helpers as well.
 *
 * Bucket semantics mirror the server's `_split_items`
 * (`src/api/routers/transactions.py`): `transactions` holds every non-deleted
 * row (ignored included), `attention` is the non-ignored, non-deleted subset
 * needing review, and `trash` holds soft-deleted rows. Each bucket is sorted
 * by `date_file_name` descending and carries a `count`.
 */

export interface TxRef {
  forwardedTo: string;
  dateFileName: string;
}

export type CombinedUpdater = (old: CombinedTransactionsResponse) => CombinedTransactionsResponse;

export type CombinedSnapshot = [QueryKey, CombinedTransactionsResponse | undefined][];

type Bucket = CombinedTransactionsResponse["transactions" | "attention" | "trash"];

const COMBINED = queryKeys.prefix("transactions-combined");

export function isTx(t: Transaction, { forwardedTo, dateFileName }: TxRef): boolean {
  return t.forwarded_to === forwardedTo && t.date_file_name === dateFileName;
}

function withRows<B extends Bucket>(bucket: B, rows: Transaction[]): B {
  return { ...bucket, count: rows.length, transactions: rows };
}

function withoutRow<B extends Bucket>(bucket: B, ref: TxRef): B {
  const rows = bucket.transactions.filter((t) => !isTx(t, ref));
  return rows.length === bucket.transactions.length ? bucket : withRows(bucket, rows);
}

/** Insert a row keeping the server's `date_file_name` descending order. */
function withInsertedRow<B extends Bucket>(bucket: B, row: Transaction): B {
  const rows = bucket.transactions.filter((t) => !isTx(t, toRef(row)));
  const idx = rows.findIndex((t) => t.date_file_name < row.date_file_name);
  rows.splice(idx === -1 ? rows.length : idx, 0, row);
  return withRows(bucket, rows);
}

function toRef(t: Transaction): TxRef {
  return { forwardedTo: t.forwarded_to, dateFileName: t.date_file_name };
}

function findRow(old: CombinedTransactionsResponse, ref: TxRef): Transaction | undefined {
  return (
    old.transactions.transactions.find((t) => isTx(t, ref)) ??
    old.attention.transactions.find((t) => isTx(t, ref)) ??
    old.trash.transactions.find((t) => isTx(t, ref))
  );
}

// ---------------------------------------------------------------------------
// Updater builders (pure)
// ---------------------------------------------------------------------------

/** Apply `fn` to the matching row in every bucket (transactions/attention/trash). */
export function mapRow(ref: TxRef, fn: (t: Transaction) => Transaction): CombinedUpdater {
  const mapBucket = <B extends Bucket>(bucket: B): B => ({
    ...bucket,
    transactions: bucket.transactions.map((t) => (isTx(t, ref) ? fn(t) : t)),
  });
  return (old) => ({
    ...old,
    transactions: mapBucket(old.transactions),
    attention: mapBucket(old.attention),
    trash: mapBucket(old.trash),
  });
}

/** Drop the row from the attention bucket (reviewed, ignored, or deleted). */
export function removeFromAttention(ref: TxRef): CombinedUpdater {
  return (old) => ({ ...old, attention: withoutRow(old.attention, ref) });
}

/** Soft delete: leave `transactions` and `attention`, enter `trash` stamped `deleted_at`. */
export function moveToTrash(ref: TxRef, deletedAt: string): CombinedUpdater {
  return (old) => {
    const row = findRow(old, ref);
    return {
      ...old,
      transactions: withoutRow(old.transactions, ref),
      attention: withoutRow(old.attention, ref),
      trash: row ? withInsertedRow(old.trash, { ...row, deleted_at: deletedAt }) : old.trash,
    };
  };
}

/**
 * Restore: leave `trash`, re-enter `transactions` with `deleted_at` cleared.
 * Attention membership depends on server-side audit rules, so it is left for
 * the settle-time refetch to reconcile.
 */
export function restoreFromTrash(ref: TxRef): CombinedUpdater {
  return (old) => {
    const row = old.trash.transactions.find((t) => isTx(t, ref));
    return {
      ...old,
      trash: withoutRow(old.trash, ref),
      transactions: row
        ? withInsertedRow(old.transactions, { ...row, deleted_at: null })
        : old.transactions,
    };
  };
}

export function composeUpdaters(...updaters: CombinedUpdater[]): CombinedUpdater {
  return (old) => updaters.reduce((acc, fn) => fn(acc), old);
}

// ---------------------------------------------------------------------------
// Cache plumbing
// ---------------------------------------------------------------------------

/** Apply `updater` to every month of the combined cache, without snapshotting. */
export function setCombinedTransactions(qc: QueryClient, updater: CombinedUpdater): void {
  qc.setQueriesData<CombinedTransactionsResponse>({ queryKey: COMBINED }, (old) =>
    old ? updater(old) : old
  );
}

/**
 * `onMutate` half: cancel in-flight combined fetches (so they can't clobber the
 * optimistic state), snapshot every month, then apply `updater`. Return the
 * snapshot in the mutation context and hand it to `restoreCombinedTransactions`
 * in `onError`.
 */
export async function optimisticallyUpdateCombined(
  qc: QueryClient,
  updater: CombinedUpdater
): Promise<CombinedSnapshot> {
  await qc.cancelQueries({ queryKey: COMBINED });
  const snapshot = qc.getQueriesData<CombinedTransactionsResponse>({ queryKey: COMBINED });
  setCombinedTransactions(qc, updater);
  return snapshot;
}

/** `onError` half: put every snapshotted month back exactly as it was. */
export function restoreCombinedTransactions(
  qc: QueryClient,
  snapshot: CombinedSnapshot | undefined
): void {
  if (!snapshot) return;
  for (const [queryKey, data] of snapshot) {
    qc.setQueryData(queryKey, data);
  }
}
