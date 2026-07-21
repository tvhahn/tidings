import { useQuery } from "@tanstack/react-query";
import { queries } from "@/lib/queryConfigs";

export function useSavedInsights(month: string) {
  return useQuery(queries.savedInsightsList(month));
}

export function useSavedInsight(id: string | null, month: string) {
  return useQuery({
    ...queries.savedInsight(id ?? "", month),
    enabled: !!id,
  });
}
