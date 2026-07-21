import { useMutation, useQuery, useQueryClient } from "@tanstack/react-query";
import { mutations, queries } from "@/lib/queryConfigs";

export function useInsightsStatus() {
  return useQuery(queries.insightsStatus());
}

export function useGenerateInsights() {
  const qc = useQueryClient();
  return useMutation(mutations.generateInsights(qc));
}
