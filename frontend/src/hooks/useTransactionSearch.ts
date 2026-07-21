import { useQuery } from "@tanstack/react-query";
import { queries } from "@/lib/queryConfigs";
import type { SearchParams } from "@/types/api";

export function useTransactionSearch(params: SearchParams | null) {
  return useQuery(queries.transactionSearch(params));
}
