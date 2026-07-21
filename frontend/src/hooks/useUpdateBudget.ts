import { useMutation, useQueryClient } from "@tanstack/react-query";
import { mutations } from "@/lib/queryConfigs";

export function useUpdateBudget(year: number) {
  const qc = useQueryClient();
  return useMutation(mutations.updateBudget(year, qc));
}
