import { useMutation, useQueryClient } from "@tanstack/react-query";
import { mutations } from "@/lib/queryConfigs";

/** Force a transaction onto ("include") or off ("exclude") a CRA claim line. */
export function useSetTaxOverride() {
  const qc = useQueryClient();
  return useMutation(mutations.setTaxOverride(qc));
}
