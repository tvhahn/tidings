import { useMutation, useQueryClient } from "@tanstack/react-query";
import { toast } from "sonner";
import { mutations } from "@/lib/queryConfigs";

/**
 * Set aside marks a quarantined row dismissed. There is no un-dismiss endpoint,
 * so there's no honest Undo — the row moves to the "Set aside" view rather than
 * disappearing, which is the recoverable path. (Spec D5 / GOAL: never ship a
 * non-functional Undo.)
 */
export function useDismissParseFailure() {
  const qc = useQueryClient();
  return useMutation({
    ...mutations.dismissParseFailure(qc),
    onSuccess: () => {
      toast("Email set aside");
    },
    onError: () => {
      toast.error("Couldn't set this aside — try again");
    },
  });
}
