import { useQuery } from "@tanstack/react-query";
import { queries } from "@/lib/queryConfigs";

/**
 * A transaction's linked receipts/documents. `enabled` gates the fetch so it
 * only runs once the row's action cluster is revealed — never a bulk per-row
 * sweep across the whole table.
 */
export function useTransactionAttachments(txId: string, enabled: boolean) {
  return useQuery({ ...queries.attachments(txId), enabled: enabled && !!txId });
}
