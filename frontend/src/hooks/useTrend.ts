import { useQuery } from "@tanstack/react-query";
import { queries } from "@/lib/queryConfigs";

export function useTrend(months: number = 6, endMonth?: string) {
  return useQuery(queries.trend(months, endMonth));
}
