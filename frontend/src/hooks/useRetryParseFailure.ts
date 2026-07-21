import { useMutation, useQueryClient } from "@tanstack/react-query";
import { toast } from "sonner";
import { mutations } from "@/lib/queryConfigs";
import type { RetryResponse } from "@/types/api";

/**
 * Retry re-runs the deterministic parsers (no AI). The three outcomes each get
 * distinct, calm copy; the factory's onSettled owns the list refresh, so a
 * `created` row leaves the queue on its own after invalidation.
 */
export function useRetryParseFailure() {
  const qc = useQueryClient();
  return useMutation({
    ...mutations.retryParseFailure(qc),
    onSuccess: (res: RetryResponse) => {
      if (res.status === "created") {
        toast.success("Recorded — added to your transactions");
      } else if (res.status === "duplicate") {
        toast("Already recorded");
      } else {
        // still_failing — parser still can't read it (or the DB rejected the
        // parsed row). One calm message covers both; never imply user error.
        toast("Still can't read this one — try again after a parser update");
      }
    },
    onError: () => {
      toast.error("Couldn't retry — try again");
    },
  });
}
