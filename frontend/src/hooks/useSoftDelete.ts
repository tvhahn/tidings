import { useMutation, useQueryClient } from "@tanstack/react-query";
import { toast } from "sonner";
import { softDeleteTransaction } from "@/lib/api";
import {
  moveToTrash,
  optimisticallyUpdateCombined,
  restoreCombinedTransactions,
} from "@/lib/optimisticTransactions";
import { invalidateTransactionDependents, mutations, queryKeys } from "@/lib/queryConfigs";
import type { TransactionListResponse, SearchResponse } from "@/types/api";

export function useSoftDelete() {
  const qc = useQueryClient();

  return useMutation({
    ...mutations.softDelete(qc),

    onMutate: async ({ forwardedTo, dateFileName }) => {
      // Combined cache backs the Transactions page (via useTransactions): the
      // row leaves transactions/attention and lands in trash, as on refetch.
      const previousCombined = await optimisticallyUpdateCombined(
        qc,
        moveToTrash({ forwardedTo, dateFileName }, new Date().toISOString())
      );
      await qc.cancelQueries({ queryKey: queryKeys.prefix("transactions") });
      await qc.cancelQueries({ queryKey: queryKeys.prefix("transaction-search") });

      const previousTransactions = qc.getQueriesData<TransactionListResponse>({
        queryKey: ["transactions"],
      });
      const previousSearch = qc.getQueriesData<SearchResponse>({
        queryKey: ["transaction-search"],
      });

      qc.setQueriesData<TransactionListResponse>(
        { queryKey: queryKeys.prefix("transactions") },
        (old) => {
          if (!old) return old;
          const filtered = old.transactions.filter(
            (t) => !(t.forwarded_to === forwardedTo && t.date_file_name === dateFileName)
          );
          return { ...old, count: filtered.length, transactions: filtered };
        }
      );

      qc.setQueriesData<SearchResponse>(
        { queryKey: queryKeys.prefix("transaction-search") },
        (old) => {
          if (!old) return old;
          const filtered = old.transactions.filter(
            (t) => !(t.forwarded_to === forwardedTo && t.date_file_name === dateFileName)
          );
          return {
            ...old,
            total_matching: old.total_matching - (old.transactions.length - filtered.length),
            transactions: filtered,
          };
        }
      );

      return { previousCombined, previousTransactions, previousSearch };
    },

    onError: (_err, _vars, context) => {
      restoreCombinedTransactions(qc, context?.previousCombined);
      if (context?.previousTransactions) {
        for (const [queryKey, data] of context.previousTransactions) {
          qc.setQueryData(queryKey, data);
        }
      }
      if (context?.previousSearch) {
        for (const [queryKey, data] of context.previousSearch) {
          qc.setQueryData(queryKey, data);
        }
      }
      toast.error("Failed to delete transaction");
    },

    onSuccess: (_data, { forwardedTo, dateFileName }) => {
      toast("Transaction deleted", {
        action: {
          label: "Undo",
          onClick: () => {
            softDeleteTransaction(forwardedTo, dateFileName, false).then(() => {
              invalidateTransactionDependents(qc, { includeTrash: true });
            });
          },
        },
      });
    },
  });
}
