import { useMutation, useQuery, useQueryClient } from "@tanstack/react-query";
import { toast } from "sonner";
import { undismissIgnoreRuleSuggestion } from "@/lib/api";
import { mutations, queries, queryKeys } from "@/lib/queryConfigs";

export function useIgnoreRules() {
  return useQuery(queries.ignoreRules());
}

export function useIgnoreRuleSuggestions() {
  return useQuery(queries.ignoreRuleSuggestions());
}

export function useIgnoreRuleDismissedSuggestions() {
  return useQuery(queries.ignoreRuleDismissed());
}

export function useUndismissIgnoreRuleSuggestion() {
  const qc = useQueryClient();
  return useMutation(mutations.undismissIgnoreRuleSuggestion(qc));
}

export function useAddIgnoreRule() {
  const qc = useQueryClient();
  return useMutation(mutations.addIgnoreRule(qc));
}

export function useDeleteIgnoreRule() {
  const qc = useQueryClient();
  return useMutation(mutations.deleteIgnoreRule(qc));
}

export function useApplyIgnoreRules() {
  const qc = useQueryClient();
  return useMutation(mutations.applyIgnoreRules(qc));
}

export function useDismissIgnoreRuleSuggestion() {
  const qc = useQueryClient();
  return useMutation({
    ...mutations.dismissIgnoreRuleSuggestion(qc),
    // The factory's onSettled refetches the suggestion list; here we overlay a
    // quiet confirmation with Undo, which reverses the dismissal server-side.
    onSuccess: (_data, merchant: string) => {
      toast("Suggestion dismissed", {
        action: {
          label: "Undo",
          onClick: () => {
            undismissIgnoreRuleSuggestion(merchant).then(() => {
              qc.invalidateQueries({ queryKey: queryKeys.ignoreRuleSuggestions() });
              qc.invalidateQueries({ queryKey: queryKeys.ignoreRuleDismissed() });
            });
          },
        },
      });
    },
  });
}
