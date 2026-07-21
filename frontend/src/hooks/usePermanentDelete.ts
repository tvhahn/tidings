import { useMutation, useQueryClient } from "@tanstack/react-query";
import { toast } from "sonner";
import { mutations } from "@/lib/queryConfigs";

export function usePermanentDelete() {
  const qc = useQueryClient();
  return useMutation({
    ...mutations.permanentDelete(qc),
    onError: () => {
      toast.error("Failed to permanently delete transaction");
    },
    onSuccess: () => {
      toast("Transaction permanently deleted");
    },
  });
}
