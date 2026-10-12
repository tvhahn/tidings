import { useMutation, useQueryClient } from "@tanstack/react-query";
import { toast } from "sonner";
import {
  composeUpdaters,
  mapRow,
  optimisticallyUpdateCombined,
  removeFromAttention,
  restoreCombinedTransactions,
} from "@/lib/optimisticTransactions";
import { mutations, queryKeys } from "@/lib/queryConfigs";
import type { AttentionListResponse } from "@/types/api";

export function useMarkReviewed() {
  const qc = useQueryClient();

  return useMutation({
    ...mutations.markReviewed(qc),

    onMutate: async ({ forwardedTo, dateFileName }) => {
      // Combined cache: drop the row from attention and stamp the manual review
      // audit the server writes, which clears the row's inline confirm action.
      const ref = { forwardedTo, dateFileName };
      const previousCombined = await optimisticallyUpdateCombined(
        qc,
        composeUpdaters(
          removeFromAttention(ref),
          mapRow(ref, (t) => ({
            ...t,
            category_audit: { source: "manual", reviewed_at: new Date().toISOString() },
          }))
        )
      );
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

      return { previousCombined, previousAttention };
    },

    onError: (_err, _vars, context) => {
      restoreCombinedTransactions(qc, context?.previousCombined);
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
