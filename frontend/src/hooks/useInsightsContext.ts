import { useQuery } from "@tanstack/react-query";
import { queries } from "@/lib/queryConfigs";

export function useInsightsContext(month: string) {
  return useQuery(queries.insightsContext(month));
}
