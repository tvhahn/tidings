import { useMutation, useQueryClient } from "@tanstack/react-query";
import { mutations, queryKeys } from "@/lib/queryConfigs";
import { useEditedTransactions, makeKey } from "@/stores/editedTransactions";
import type {
  CombinedTransactionsResponse,
  JournalResponse,
  SearchResponse,
  TransactionListResponse,
} from "@/types/api";

export function useUpdateCategory() {
  const qc = useQueryClient();
  const markEdited = useEditedTransactions((s) => s.markEdited);

  return useMutation({
    ...mutations.updateCategory(qc),

    onMutate: async ({ forwardedTo, dateFileName, category, oldCategory }) => {
      // Cancel in-flight queries
      await qc.cancelQueries({ queryKey: queryKeys.prefix("transactions-combined") });
      await qc.cancelQueries({ queryKey: queryKeys.prefix("transactions") });
      await qc.cancelQueries({ queryKey: queryKeys.prefix("transaction-search") });
      await qc.cancelQueries({ queryKey: queryKeys.prefix("attention") });
      await qc.cancelQueries({ queryKey: queryKeys.prefix("journal") });

      // Snapshot for rollback
      const previousCombined = qc.getQueriesData<CombinedTransactionsResponse>({
        queryKey: ["transactions-combined"],
      });
      const previousQueries = qc.getQueriesData<TransactionListResponse>({
        queryKey: ["transactions"],
      });
      const previousSearch = qc.getQueriesData<SearchResponse>({
        queryKey: ["transaction-search"],
      });
      const previousJournal = qc.getQueriesData<JournalResponse>({
        queryKey: ["journal"],
      });

      // Optimistic update — flat transaction lists
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
              ? { ...t, category: category.toLowerCase() }
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

      // Optimistic update — combined (backs /transactions via useTransactions).
      // Nested shape: { transactions, attention, trash } each wrap a flat list,
      // so apply `updater` to all three buckets.
      qc.setQueriesData<CombinedTransactionsResponse>(
        { queryKey: queryKeys.prefix("transactions-combined") },
        (old) => {
          if (!old) return old;
          return {
            ...old,
            transactions: updater(old.transactions) ?? old.transactions,
            attention: updater(old.attention) ?? old.attention,
            trash: updater(old.trash) ?? old.trash,
          };
        }
      );

      // Optimistic update — journal (nested days → transactions)
      qc.setQueriesData<JournalResponse>({ queryKey: queryKeys.prefix("journal") }, (old) => {
        if (!old) return old;
        return {
          ...old,
          days: old.days.map((day) => ({
            ...day,
            transactions: day.transactions.map((t) =>
              t.forwarded_to === forwardedTo && t.date_file_name === dateFileName
                ? { ...t, category: category.toLowerCase() }
                : t
            ),
          })),
        };
      });

      // Track in Zustand
      const key = makeKey(forwardedTo, dateFileName);
      markEdited(key, oldCategory, category.toLowerCase());

      return { previousCombined, previousQueries, previousSearch, previousJournal };
    },

    onError: (_err, _vars, context) => {
      // Rollback
      if (context?.previousCombined) {
        for (const [queryKey, data] of context.previousCombined) {
          qc.setQueryData(queryKey, data);
        }
      }
      if (context?.previousQueries) {
        for (const [queryKey, data] of context.previousQueries) {
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
    },

    onSuccess: (_data, { forwardedTo, dateFileName, category }) => {
      // Re-apply the category change against whatever any in-flight refetch
      // installed. Guards against the window where the mutation's own
      // invalidate + the freshness probe can leave a pre-commit read as the
      // final state of the cache, clobbering the optimistic pill.
      const newCategory = category.toLowerCase();
      const flatUpdater = <
        T extends { transactions: { forwarded_to: string; date_file_name: string }[] },
      >(
        old: T | undefined
      ): T | undefined => {
        if (!old) return old;
        return {
          ...old,
          transactions: old.transactions.map((t) =>
            t.forwarded_to === forwardedTo && t.date_file_name === dateFileName
              ? { ...t, category: newCategory }
              : t
          ),
        };
      };
      qc.setQueriesData<TransactionListResponse>(
        { queryKey: queryKeys.prefix("transactions") },
        flatUpdater
      );
      qc.setQueriesData<SearchResponse>(
        { queryKey: queryKeys.prefix("transaction-search") },
        flatUpdater
      );
      qc.setQueriesData<CombinedTransactionsResponse>(
        { queryKey: queryKeys.prefix("transactions-combined") },
        (old) => {
          if (!old) return old;
          return {
            ...old,
            transactions: flatUpdater(old.transactions) ?? old.transactions,
            attention: flatUpdater(old.attention) ?? old.attention,
            trash: flatUpdater(old.trash) ?? old.trash,
          };
        }
      );
      qc.setQueriesData<JournalResponse>({ queryKey: queryKeys.prefix("journal") }, (old) => {
        if (!old) return old;
        return {
          ...old,
          days: old.days.map((day) => ({
            ...day,
            transactions: day.transactions.map((t) =>
              t.forwarded_to === forwardedTo && t.date_file_name === dateFileName
                ? { ...t, category: newCategory }
                : t
            ),
          })),
        };
      });
    },
  });
}
