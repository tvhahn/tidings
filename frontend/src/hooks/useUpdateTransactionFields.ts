import { useMutation, useQueryClient } from "@tanstack/react-query";
import { toast } from "sonner";
import { updateTransactionFields } from "@/lib/api";
import { invalidateTransactionDependents, mutations, queryKeys } from "@/lib/queryConfigs";
import type {
  TransactionListResponse,
  TransactionFieldsUpdateResponse,
  SearchResponse,
} from "@/types/api";

export function useUpdateTransactionFields() {
  const qc = useQueryClient();

  return useMutation({
    ...mutations.updateTransactionFields(qc),

    onMutate: async ({ forwardedTo, dateFileName, fields }) => {
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
              ? {
                  ...t,
                  ...(fields.company !== undefined && { company: fields.company }),
                  ...(fields.amount !== undefined && { amount: fields.amount }),
                  ...(fields.transaction_type !== undefined && {
                    transaction_type: fields.transaction_type,
                  }),
                }
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

    onSuccess: (data: TransactionFieldsUpdateResponse, { forwardedTo, dateFileName }) => {
      // If category was auto-updated via override, apply it to the cache
      if (data.category) {
        const categoryUpdater = <
          T extends { transactions: { forwarded_to: string; date_file_name: string }[] },
        >(
          old: T | undefined
        ): T | undefined => {
          if (!old) return old;
          return {
            ...old,
            transactions: old.transactions.map((t) =>
              t.forwarded_to === forwardedTo && t.date_file_name === dateFileName
                ? { ...t, category: data.category }
                : t
            ),
          };
        };

        qc.setQueriesData<TransactionListResponse>(
          { queryKey: queryKeys.prefix("transactions") },
          categoryUpdater
        );
        qc.setQueriesData<SearchResponse>(
          { queryKey: queryKeys.prefix("transaction-search") },
          categoryUpdater
        );
      }

      toast("Transaction updated", {
        action: {
          label: "Undo",
          onClick: () => {
            const oldFields: { company?: string; amount?: number; transaction_type?: string } = {};
            if (data.old_values.company !== null) oldFields.company = data.old_values.company;
            if (data.old_values.amount !== null) oldFields.amount = data.old_values.amount;
            if (data.old_values.transaction_type !== null)
              oldFields.transaction_type = data.old_values.transaction_type;

            if (Object.keys(oldFields).length > 0) {
              updateTransactionFields(forwardedTo, dateFileName, oldFields).then(() => {
                invalidateTransactionDependents(qc);
              });
            }
          },
        },
      });
    },
  });
}
