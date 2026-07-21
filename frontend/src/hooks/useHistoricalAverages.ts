import { useQuery } from "@tanstack/react-query";
import { queries } from "@/lib/queryConfigs";

export function useHistoricalAverages(months: number = 6, enabled: boolean = false) {
  return useQuery({ ...queries.historicalAverages(months), enabled });
}
