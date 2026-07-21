import { useQuery } from "@tanstack/react-query";
import { queries } from "@/lib/queryConfigs";

export function useJournalSummaries(month: string) {
  return useQuery(queries.journalSummaries(month));
}
