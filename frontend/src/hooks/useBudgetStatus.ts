import { useQuery } from "@tanstack/react-query";
import { queries } from "@/lib/queryConfigs";

export function useBudgetStatus(year: number, enabled: boolean = true, compareYear?: number) {
  return useQuery({ ...queries.budgetStatus(year, compareYear), enabled });
}
