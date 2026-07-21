import { useMutation, useQueryClient } from "@tanstack/react-query";
import { toast } from "sonner";
import { mutations, queryKeys } from "@/lib/queryConfigs";
import type { AttentionListResponse } from "@/types/api";

export function useMarkReviewed() {
  const qc = useQueryClient();

  return useMutation({
    ...mutations.markReviewed(qc),

    onMutate: async ({ forwardedTo, dateFileName }) => {
      await qc.cancelQueries({ queryKey: queryKeys.prefix("attention") });

      const previousAttention = qc.getQueriesData<AttentionListResponse>({
        queryKey: ["attention"],
      });

      qc.setQueriesData<AttentionListResponse>(
        { queryKey: queryKeys.prefix("attention") },
        (old) => {
          if (!old) return old;
          const filtered = old.transactions.filter(
            (t) => !(t.forwarded_to === forwardedTo && t.date_file_name === dateFileName)
          );
          return { ...old, count: filtered.length, transactions: filtered };
        }
      );

      return { previousAttention };
    },

    onError: (_err, _vars, context) => {
      if (context?.previousAttention) {
        for (const [queryKey, data] of context.previousAttention) {
          qc.setQueryData(queryKey, data);
        }
      }
      toast.error("Failed to confirm category");
    },

    onSuccess: () => {
      toast("Category confirmed");
    },
  });
}
