import { useMutation, useQuery, useQueryClient } from "@tanstack/react-query";
import { mutations, queries } from "@/lib/queryConfigs";

export function useOverrideSuggestions() {
  return useQuery(queries.overrideSuggestions());
}

export function useDismissSuggestion() {
  const qc = useQueryClient();
  return useMutation(mutations.dismissSuggestion(qc));
}
