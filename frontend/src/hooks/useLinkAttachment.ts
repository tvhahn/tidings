import { useMutation, useQueryClient } from "@tanstack/react-query";
import { mutations } from "@/lib/queryConfigs";

/** Link an attachment to a transaction, or unlink it with `txId: null`. */
export function useLinkAttachment() {
  const qc = useQueryClient();
  return useMutation(mutations.linkAttachment(qc));
}
