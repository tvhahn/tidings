import { useQuery } from "@tanstack/react-query";
import { queries } from "@/lib/queryConfigs";

export function useJournal(month: string) {
  return useQuery(queries.journal(month));
}
