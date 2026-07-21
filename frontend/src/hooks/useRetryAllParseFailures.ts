import { useMutation, useQueryClient } from "@tanstack/react-query";
import { mutations } from "@/lib/queryConfigs";

/**
 * Bulk retry a filtered set of quarantined emails through the deterministic
 * parsers (no AI). The factory owns the queue + transaction-view refresh; the
 * caller supplies the counts toast via `mutate`'s per-call `onSuccess`.
 */
export function useRetryAllParseFailures() {
  const qc = useQueryClient();
  return useMutation(mutations.retryAllParseFailures(qc));
}
