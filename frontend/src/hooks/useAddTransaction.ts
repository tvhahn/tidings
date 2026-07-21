import { useMutation, useQueryClient } from "@tanstack/react-query";
import { mutations } from "@/lib/queryConfigs";

export function useAddTransaction() {
  const qc = useQueryClient();
  return useMutation(mutations.addTransaction(qc));
}
