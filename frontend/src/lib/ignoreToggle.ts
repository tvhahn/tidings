import type { Transaction } from "@/types/api";

/**
 * Tooltip for the ignore/restore toggle on a transaction row.
 *
 * A row ingestion stored as a repeat of an alert already on file (a bank
 * re-send, or one email delivered twice — `duplicate_of_tx_id` is set) arrives
 * ignored; its tooltip says why, so restoring a genuine second purchase is a
 * deliberate choice rather than a guess.
 */
export function ignoreToggleTooltip(
  txn: Pick<Transaction, "ignored" | "duplicate_of_tx_id">
): string {
  if (!txn.ignored) return "Ignore transaction";
  if (txn.duplicate_of_tx_id)
    return "Repeat of an earlier bank alert. Restore if it was a separate purchase";
  return "Restore transaction";
}
