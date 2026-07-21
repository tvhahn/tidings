import { useQuery } from "@tanstack/react-query";
import { queries } from "@/lib/queryConfigs";

export function useSummary(month: string) {
  return useQuery(queries.summary(month));
}
