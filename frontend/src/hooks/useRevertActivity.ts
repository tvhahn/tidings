import { useMutation, useQueryClient } from "@tanstack/react-query";
import { mutations } from "@/lib/queryConfigs";

export function useRevertActivity() {
  const qc = useQueryClient();
  return useMutation(mutations.revertActivity(qc));
}
