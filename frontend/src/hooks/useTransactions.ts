import { useQuery, useQueryClient } from "@tanstack/react-query";
import { useEffect } from "react";
import { queries, queryKeys } from "@/lib/queryConfigs";
import type { TransactionListResponse, AttentionListResponse } from "@/types/api";

export function useTransactions(month: string) {
  const queryClient = useQueryClient();

  const query = useQuery(queries.transactionsCombined(month));

  // Seed individual caches from the combined response
  useEffect(() => {
    if (!query.data) return;
    const { transactions, attention, trash } = query.data;
    queryClient.setQueryData<TransactionListResponse>(queryKeys.transactions(month), transactions);
    queryClient.setQueryData<AttentionListResponse>(queryKeys.attention(month), attention);
    queryClient.setQueryData<TransactionListResponse>(queryKeys.trash(month), trash);
  }, [query.data, month, queryClient]);

  // Preserve the existing interface: return data shaped like TransactionListResponse
  return {
    ...query,
    data: query.data?.transactions,
    trashCount: query.data?.trash?.count ?? 0,
  };
}
