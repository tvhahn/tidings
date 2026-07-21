import { useQuery } from "@tanstack/react-query";
import { queries } from "@/lib/queryConfigs";

/** The selectable CRA claim lines (seven seed lines plus "other"). */
export function useTaxLines() {
  return useQuery(queries.taxLines());
}
