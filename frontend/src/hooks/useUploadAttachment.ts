import { useMutation, useQueryClient } from "@tanstack/react-query";
import { mutations } from "@/lib/queryConfigs";

/** Upload a receipt/document, optionally pre-linked to a transaction. */
export function useUploadAttachment() {
  const qc = useQueryClient();
  return useMutation(mutations.uploadAttachment(qc));
}
