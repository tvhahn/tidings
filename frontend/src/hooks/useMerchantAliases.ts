import { useMutation, useQuery, useQueryClient } from "@tanstack/react-query";
import { mutations, queries } from "@/lib/queryConfigs";

export function useMerchantAliases() {
  return useQuery(queries.merchantAliases());
}

export function usePutMerchantAlias() {
  const qc = useQueryClient();
  return useMutation(mutations.putMerchantAlias(qc));
}

export function useDeleteMerchantAlias() {
  const qc = useQueryClient();
  return useMutation(mutations.deleteMerchantAlias(qc));
}
