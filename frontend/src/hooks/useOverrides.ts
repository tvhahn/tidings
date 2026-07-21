import { useMutation, useQuery, useQueryClient } from "@tanstack/react-query";
import { mutations, queries } from "@/lib/queryConfigs";

export function useOverrides() {
  return useQuery(queries.overrides());
}

export function useOverrideMatch(company: string) {
  return useQuery(queries.overrideMatch(company));
}

export function useOverrideDuplicates() {
  return useQuery(queries.overrideDuplicates());
}

export function useConsolidateOverrides() {
  const qc = useQueryClient();
  return useMutation(mutations.consolidateOverrides(qc));
}

export function usePutOverride() {
  const qc = useQueryClient();
  return useMutation(mutations.putOverride(qc));
}

export function useDeleteOverride() {
  const qc = useQueryClient();
  return useMutation(mutations.deleteOverride(qc));
}
