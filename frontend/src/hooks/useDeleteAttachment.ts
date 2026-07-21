import { useMutation, useQueryClient } from "@tanstack/react-query";
import { mutations } from "@/lib/queryConfigs";

/** Delete an attachment and its file from disk. */
export function useDeleteAttachment() {
  const qc = useQueryClient();
  return useMutation(mutations.deleteAttachment(qc));
}
