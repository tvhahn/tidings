import { useMutation, useQuery, useQueryClient } from "@tanstack/react-query";
import { mutations, queries } from "@/lib/queryConfigs";

export function useConfig() {
  return useQuery(queries.config());
}

export function useUpdateConfig() {
  const qc = useQueryClient();
  return useMutation(mutations.updateConfig(qc));
}
