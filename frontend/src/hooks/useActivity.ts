import { useQuery } from "@tanstack/react-query";
import type { ActivityFilters } from "@/lib/api";
import { queries } from "@/lib/queryConfigs";

export function useActivity(filters: ActivityFilters = {}) {
  return useQuery(queries.activity(filters));
}
