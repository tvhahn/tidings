import { useMutation, useQueryClient } from "@tanstack/react-query";
import { mutations } from "@/lib/queryConfigs";

export function useUploadStatement() {
  return useMutation(mutations.uploadStatement());
}

export function useImportStatement() {
  const qc = useQueryClient();
  return useMutation(mutations.importStatement(qc));
}
