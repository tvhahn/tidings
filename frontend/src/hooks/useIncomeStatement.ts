import { useQuery } from "@tanstack/react-query";
import { queries } from "@/lib/queryConfigs";

export function useIncomeStatement(year: number) {
  return useQuery(queries.incomeStatement(year));
}
