import { useMutation, useQueryClient } from "@tanstack/react-query";
import { toast } from "sonner";
import { mutations, queryKeys } from "@/lib/queryConfigs";
import type { TransactionListResponse } from "@/types/api";

export function useRestoreTransaction() {
  const qc = useQueryClient();

  return useMutation({
    ...mutations.restoreTransaction(qc),

    onMutate: async ({ forwardedTo, dateFileName }) => {
      await qc.cancelQueries({ queryKey: queryKeys.prefix("trash") });

      const previousTrash = qc.getQueriesData<TransactionListResponse>({
        queryKey: ["trash"],
      });

      qc.setQueriesData<TransactionListResponse>({ queryKey: queryKeys.prefix("trash") }, (old) => {
        if (!old) return old;
        const filtered = old.transactions.filter(
          (t) => !(t.forwarded_to === forwardedTo && t.date_file_name === dateFileName)
        );
        return { ...old, count: filtered.length, transactions: filtered };
      });

      return { previousTrash };
    },

    onError: (_err, _vars, context) => {
      if (context?.previousTrash) {
        for (const [queryKey, data] of context.previousTrash) {
          qc.setQueryData(queryKey, data);
        }
      }
      toast.error("Failed to restore transaction");
    },

    onSuccess: () => {
      toast("Transaction restored");
    },
  });
}
