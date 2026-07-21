import { useMutation, useQuery, useQueryClient } from "@tanstack/react-query";
import { mutations, queries } from "@/lib/queryConfigs";

export function useManagedCategories() {
  return useQuery(queries.managedCategories());
}

export function useAddCategory() {
  const qc = useQueryClient();
  return useMutation(mutations.addCategory(qc));
}

export function useRenameCategory() {
  const qc = useQueryClient();
  return useMutation(mutations.renameCategory(qc));
}

export function useDeleteCategory() {
  const qc = useQueryClient();
  return useMutation(mutations.deleteCategory(qc));
}

export function useUpdateCategoryGroup() {
  const qc = useQueryClient();
  return useMutation(mutations.updateCategoryGroup(qc));
}

export function useCategoryUsage(name: string | null) {
  return useQuery(queries.categoryUsage(name));
}

export function useCategoryIcons() {
  return useQuery(queries.categoryIcons());
}

export function useSetCategoryIcon() {
  const qc = useQueryClient();
  return useMutation(mutations.setCategoryIcon(qc));
}

export function useClearCategoryIcon() {
  const qc = useQueryClient();
  return useMutation(mutations.clearCategoryIcon(qc));
}
