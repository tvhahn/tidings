import { useQuery } from "@tanstack/react-query";
import { queries } from "@/lib/queryConfigs";

/** Receipts uploaded but not yet filed against a transaction. */
export function useUnlinkedAttachments() {
  return useQuery(queries.unlinkedAttachments());
}
