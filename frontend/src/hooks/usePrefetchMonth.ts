import { useQueryClient } from "@tanstack/react-query";
import { useEffect, useRef } from "react";
import { fetchAllTransactions, fetchBulkTransactions } from "@/lib/api";
import { shiftMonth } from "@/lib/format";
import type { TransactionListResponse, AttentionListResponse } from "@/types/api";

/**
 * Seed individual query caches (transactions, attention, trash) from a combined response.
 */
function seedCaches(
  queryClient: ReturnType<typeof useQueryClient>,
  month: string,
  data: {
    transactions: TransactionListResponse;
    attention: AttentionListResponse;
    trash: TransactionListResponse;
  }
) {
  queryClient.setQueryData<TransactionListResponse>(["transactions", month], data.transactions);
  queryClient.setQueryData<AttentionListResponse>(["attention", month], data.attention);
  queryClient.setQueryData<TransactionListResponse>(["trash", month], data.trash);
}

export function usePrefetchMonth(month: string) {
  const queryClient = useQueryClient();
  const bulkLoaded = useRef(false);

  // Adjacent-month prefetch — fires immediately on month change.
  // React Query deduplicates in-flight requests for the same queryKey,
  // so rapid clicking won't cause duplicate requests.
  useEffect(() => {
    const prev = shiftMonth(month, -1);
    const next = shiftMonth(month, 1);

    for (const m of [prev, next]) {
      queryClient
        .fetchQuery({
          queryKey: ["transactions-combined", m],
          queryFn: () => fetchAllTransactions(m),
          staleTime: 30 * 60 * 1000,
        })
        .then((data) => {
          if (data) seedCaches(queryClient, m, data);
        })
        .catch(() => {});
    }
  }, [month, queryClient]);

  // One-time bulk preload of ±3 months on mount
  useEffect(() => {
    if (bulkLoaded.current) return;
    bulkLoaded.current = true;

    const months: string[] = [];
    for (let i = -3; i <= 3; i++) {
      if (i === 0) continue;
      const m = shiftMonth(month, i);
      // Skip months already in cache
      if (queryClient.getQueryData(["transactions-combined", m])) continue;
      months.push(m);
    }

    if (months.length === 0) return;

    fetchBulkTransactions(months)
      .then((results) => {
        for (const [m, data] of Object.entries(results)) {
          queryClient.setQueryData(["transactions-combined", m], data);
          seedCaches(queryClient, m, data);
        }
      })
      .catch(() => {
        // Silently fail — bulk preload is best-effort
      });
    // eslint-disable-next-line react-hooks/exhaustive-deps
  }, []);
}
