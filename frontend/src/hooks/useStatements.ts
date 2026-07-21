import { useMutation, useQuery, useQueryClient } from "@tanstack/react-query";
import { mutations, queries } from "@/lib/queryConfigs";

export function useStatements() {
  return useQuery(queries.statements());
}

export function useDeleteStatement() {
  const qc = useQueryClient();
  return useMutation(mutations.deleteStatement(qc));
}
