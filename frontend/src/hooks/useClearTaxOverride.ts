import { useMutation, useQueryClient } from "@tanstack/react-query";
import { mutations } from "@/lib/queryConfigs";

/** Remove a prior tax override, reverting the row to its auto-classified state. */
export function useClearTaxOverride() {
  const qc = useQueryClient();
  return useMutation(mutations.clearTaxOverride(qc));
}
