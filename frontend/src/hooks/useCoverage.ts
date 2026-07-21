import { useQuery } from "@tanstack/react-query";
import { queries } from "@/lib/queryConfigs";

export function useCoverage() {
  return useQuery(queries.coverage());
}
