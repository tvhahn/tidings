import { useQuery } from "@tanstack/react-query";
import { queries } from "@/lib/queryConfigs";

/**
 * Ranked transactions a parsed receipt might explain. Pass `enabled` false until
 * the attachment has been parsed — the endpoint 409s on unparsed rows.
 */
export function useReceiptCandidates(id: string, enabled: boolean) {
  return useQuery({ ...queries.receiptCandidates(id), enabled });
}
