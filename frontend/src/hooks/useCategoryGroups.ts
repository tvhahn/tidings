import { useMutation, useQuery, useQueryClient } from "@tanstack/react-query";
import { DEFAULT_CATEGORY_GROUPS } from "@/lib/categoryGroups";
import type { CategoryGroup } from "@/lib/categoryGroups";
import { mutations, queries } from "@/lib/queryConfigs";

const CURRENT_YEAR = new Date().getFullYear();

export function useCategoryGroups(year: number = CURRENT_YEAR) {
  const query = useQuery(queries.categoryGroups(year));

  // Always return groups (fallback to defaults while loading/on error)
  const groups: CategoryGroup[] = query.data?.groups ?? DEFAULT_CATEGORY_GROUPS;
  const version = query.data?.version ?? 0;

  return { ...query, groups, version };
}

export function useUpdateGroups(year: number = CURRENT_YEAR) {
  const qc = useQueryClient();
  return useMutation(mutations.updateGroups(year, qc));
}
