import type { CategoryGroup } from "@/lib/categoryGroups";
import { groupCategory } from "@/lib/categoryGroups";
import type { Transaction } from "@/types/api";

export interface Filters {
  category: string;
  categoryGroup?: string | undefined;
  institution: string;
  search: string;
  hideDeposits: boolean;
  hideIgnored: boolean;
}

export const DEFAULT_FILTERS: Filters = {
  category: "all",
  categoryGroup: undefined,
  institution: "all",
  search: "",
  hideDeposits: false,
  hideIgnored: false,
};

export function hasActiveFilters(filters: Filters): boolean {
  return (
    filters.category !== DEFAULT_FILTERS.category ||
    filters.categoryGroup !== DEFAULT_FILTERS.categoryGroup ||
    filters.institution !== DEFAULT_FILTERS.institution ||
    filters.search !== DEFAULT_FILTERS.search ||
    filters.hideDeposits !== DEFAULT_FILTERS.hideDeposits ||
    filters.hideIgnored !== DEFAULT_FILTERS.hideIgnored
  );
}

export function applyFilters(
  transactions: Transaction[],
  filters: Filters,
  groups?: CategoryGroup[]
): Transaction[] {
  let result = transactions;
  if (filters.hideDeposits) {
    result = result.filter((t) => t.transaction_type !== "deposit");
  }
  if (filters.hideIgnored) {
    result = result.filter((t) => !t.ignored);
  }
  if (filters.categoryGroup) {
    result = result.filter(
      (t) => groupCategory(t.category ?? "", groups) === filters.categoryGroup
    );
  } else if (filters.category && filters.category !== "all") {
    result = result.filter((t) => t.category?.toLowerCase() === filters.category.toLowerCase());
  }
  if (filters.institution && filters.institution !== "all") {
    result = result.filter(
      (t) => t.institution?.toLowerCase() === filters.institution.toLowerCase()
    );
  }
  if (filters.search) {
    const needle = filters.search.toLowerCase();
    result = result.filter((t) =>
      [t.company, t.comment, t.category].some((f) => f?.toLowerCase().includes(needle))
    );
  }
  return result;
}
