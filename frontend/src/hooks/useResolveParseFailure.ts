import { useMutation, useQueryClient } from "@tanstack/react-query";
import { toast } from "sonner";
import { ApiError } from "@/lib/apiError";
import { mutations } from "@/lib/queryConfigs";
import type { ManualResolveResponse } from "@/types/api";

/**
 * Manual entry records a hand-typed transaction for an email the parsers
 * couldn't read and resolves the row in one call. The success toasts are reused
 * verbatim from useRetryParseFailure so both recovery paths read identically;
 * the factory's onSettled owns the queue + transaction-view refresh, so a
 * resolved row leaves the queue on its own after invalidation.
 */
export function useResolveParseFailure() {
  const qc = useQueryClient();
  return useMutation({
    ...mutations.resolveParseFailure(qc),
    onSuccess: (res: ManualResolveResponse) => {
      if (res.status === "duplicate") {
        toast("Already recorded");
      } else {
        toast.success("Recorded — added to your transactions");
      }
    },
    onError: (err: unknown) => {
      // 422 means the store rejected the values — point at the likely culprits
      // instead of a generic failure. Any other error gets the calm fallback.
      if (err instanceof ApiError && err.status === 422) {
        toast.error("Couldn't save those details — check the amount and company");
      } else {
        toast.error("Couldn't save those details — try again");
      }
    },
  });
}
