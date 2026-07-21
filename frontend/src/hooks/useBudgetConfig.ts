import { useQuery } from "@tanstack/react-query";
import { queries } from "@/lib/queryConfigs";

export function useBudgetConfig(year: number) {
  return useQuery(queries.budgetConfig(year));
}
