import { useMutation, useQueryClient } from "@tanstack/react-query";
import { toast } from "sonner";
import { mutations, queryKeys } from "@/lib/queryConfigs";
import type { JournalResponse, TransactionListResponse, SearchResponse } from "@/types/api";

export function useUpdateComment() {
  const qc = useQueryClient();

  return useMutation({
    ...mutations.updateComment(qc),

    onMutate: async ({ forwardedTo, dateFileName, comment }) => {
      await qc.cancelQueries({ queryKey: queryKeys.prefix("transactions") });
      await qc.cancelQueries({ queryKey: queryKeys.prefix("transaction-search") });
      await qc.cancelQueries({ queryKey: queryKeys.prefix("journal") });

      const previousTransactions = qc.getQueriesData<TransactionListResponse>({
        queryKey: ["transactions"],
      });
      const previousSearch = qc.getQueriesData<SearchResponse>({
        queryKey: ["transaction-search"],
      });
      const previousJournal = qc.getQueriesData<JournalResponse>({
        queryKey: ["journal"],
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
              ? { ...t, comment }
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
      qc.setQueriesData<JournalResponse>({ queryKey: queryKeys.prefix("journal") }, (old) => {
        if (!old) return old;
        return {
          ...old,
          days: old.days.map((day) => ({
            ...day,
            transactions: day.transactions.map((t) =>
              t.forwarded_to === forwardedTo && t.date_file_name === dateFileName
                ? { ...t, comment }
                : t
            ),
          })),
        };
      });

      return { previousTransactions, previousSearch, previousJournal };
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
      if (context?.previousJournal) {
        for (const [queryKey, data] of context.previousJournal) {
          qc.setQueryData(queryKey, data);
        }
      }
      toast.error("Failed to save note");
    },

    onSuccess: (_data, { comment }) => {
      toast(comment ? "Note saved" : "Note cleared");
    },
  });
}
