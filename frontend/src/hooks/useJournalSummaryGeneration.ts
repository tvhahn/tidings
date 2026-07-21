import { useMutation, useQuery, useQueryClient } from "@tanstack/react-query";
import { mutations, queries } from "@/lib/queryConfigs";

export function useJournalSummaryStatus() {
  return useQuery(queries.journalSummaryStatus());
}

export function useGenerateJournalSummaries() {
  const qc = useQueryClient();
  return useMutation(mutations.generateJournalSummaries(qc));
}
