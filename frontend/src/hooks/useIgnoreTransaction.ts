import { useMutation, useQueryClient } from "@tanstack/react-query";
import { toast } from "sonner";
import { setIgnored } from "@/lib/api";
import { invalidateTransactionDependents, mutations, queryKeys } from "@/lib/queryConfigs";
import type { TransactionListResponse, SearchResponse } from "@/types/api";

export function useIgnoreTransaction() {
  const qc = useQueryClient();

  return useMutation({
    ...mutations.ignoreTransaction(qc),

    onMutate: async ({ forwardedTo, dateFileName, ignored }) => {
      await qc.cancelQueries({ queryKey: queryKeys.prefix("transactions") });
      await qc.cancelQueries({ queryKey: queryKeys.prefix("transaction-search") });

      const previousTransactions = qc.getQueriesData<TransactionListResponse>({
        queryKey: ["transactions"],
      });
      const previousSearch = qc.getQueriesData<SearchResponse>({
        queryKey: ["transaction-search"],
      });

      const updater = <
        T extends { transactions: { forwarded_to: string; date_file_name: string }[] },
      >(
        old: T | undefined
      ): T | undefined => {
        if (!old) return old;
        return {
          ...old,
          transactions: old.transactions.map((t) =>
            t.forwarded_to === forwardedTo && t.date_file_name === dateFileName
              ? { ...t, ignored }
              : t
          ),
        };
      };

      qc.setQueriesData<TransactionListResponse>(
        { queryKey: queryKeys.prefix("transactions") },
        updater
      );
      qc.setQueriesData<SearchResponse>(
        { queryKey: queryKeys.prefix("transaction-search") },
        updater
      );

      return { previousTransactions, previousSearch };
    },

    onError: (_err, _vars, context) => {
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
      toast.error("Failed to update transaction");
    },

    onSuccess: (_data, { forwardedTo, dateFileName, ignored }) => {
      const label = ignored ? "Transaction ignored" : "Transaction restored";
      toast(label, {
        action: {
          label: "Undo",
          onClick: () => {
            setIgnored(forwardedTo, dateFileName, !ignored).then(() => {
              invalidateTransactionDependents(qc);
            });
          },
        },
      });
    },
  });
}
