import { useMutation, useQueryClient } from "@tanstack/react-query";
import { mutations } from "@/lib/queryConfigs";

/** Parse a receipt through the configured AI provider (consent-gated server-side). */
export function useParseReceipt() {
  const qc = useQueryClient();
  return useMutation(mutations.parseReceipt(qc));
}
