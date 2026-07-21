import { useMutation, useQuery, useQueryClient } from "@tanstack/react-query";
import { mutations, queries } from "@/lib/queryConfigs";

export function useStatement(id: string | null) {
  return useQuery(queries.statement(id));
}

export function useUpdateTransactionAction(statementId: string | null) {
  const qc = useQueryClient();
  return useMutation(mutations.updateTransactionAction(statementId, qc));
}

export function useReparseStatement() {
  const qc = useQueryClient();
  return useMutation(mutations.reparseStatement(qc));
}
