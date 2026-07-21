import type {
  BudgetStatusResponse,
  CategoryPaceDetail,
  HistoricalAveragesResponse,
} from "@/types/api";

/** Whole-dollar currency for forecast figures — cents would be false precision. */
export function formatForecastCurrency(amount: number | null): string {
  if (amount == null) return "—";
  return new Intl.NumberFormat("en-CA", {
    style: "currency",
    currency: "CAD",
    maximumFractionDigits: 0,
  }).format(amount);
}

export interface CategoryFormEntry {
  key: string;
  target: number;
  inputMode: "monthly" | "yearly";
  categoryType: "fixed" | "variable" | "lumpy";
  displayAmount: string;
}

/**
 * Recalculate a budget entry when the user changes a field.
 * Handles monthly↔yearly conversion and target derivation from display amount.
 */
export function recalculateEntry(
  entry: CategoryFormEntry,
  patch: Partial<CategoryFormEntry>
): CategoryFormEntry {
  const updated = { ...entry, ...patch };

  // Recalculate when inputMode changes
  if (patch.inputMode && patch.inputMode !== entry.inputMode) {
    if (patch.inputMode === "yearly") {
      updated.displayAmount = String(entry.target);
    } else {
      updated.displayAmount = String(Math.round((entry.target / 12) * 100) / 100);
    }
  }

  // Recalculate target from displayAmount
  if (patch.displayAmount !== undefined) {
    const val = parseFloat(patch.displayAmount) || 0;
    updated.target = updated.inputMode === "monthly" ? val * 12 : val;
  }

  return updated;
}

/**
 * Build the prefill entry set + spending ceiling from 12-month history.
 *
 * Mirrors the "Pre-fill History" affordance exactly: keep only categories with
 * at least 3 active months, seed each as a monthly-input entry from its
 * suggested figures, and round the summed annual target to the nearest $1000
 * for the ceiling. The returned `entries`/`ceiling` feed a mutation payload, so
 * ordering, key shapes, and the rounding must stay byte-for-byte identical.
 */
export function buildPrefillEntries(hist: HistoricalAveragesResponse): {
  entries: CategoryFormEntry[];
  ceiling: string;
} {
  const entries: CategoryFormEntry[] = Object.entries(hist.categories)
    .filter(([, info]) => info.months_active >= 3)
    .map(([key, info]) => ({
      key,
      target: info.suggested_annual,
      inputMode: "monthly" as const,
      categoryType: info.suggested_type as "fixed" | "variable" | "lumpy",
      displayAmount: String(info.suggested_monthly),
    }));
  const totalAnnual = entries.reduce((s, e) => s + e.target, 0);
  const ceiling = String(Math.round(totalAnnual / 1000) * 1000);
  return { entries, ceiling };
}

/** Key → monthly average, for the 3mo/12mo average columns. */
export type AvgMap = Record<string, number>;

/** Key → per-category current-month and YTD spend. */
export type SpendingMap = Record<string, { currentMonth: number; ytd: number }>;

/** Key → suggested monthly amount + suggested category type (from history). */
export type SuggestedMap = Record<string, { suggestedMonthly: number; suggestedType: string }>;

/** One display group: a name and the form entries that belong to it. */
export interface GroupedEntries {
  name: string;
  entries: CategoryFormEntry[];
}

/** Subtotal figures rendered on a group's subtotal row. */
export interface GroupSubtotals {
  avg3: number;
  avg12: number;
  currentMonth: number;
  ytd: number;
  monthly: number;
  annual: number;
}

/** Structural shape shared by BudgetGroupConfig and the dynamic CategoryGroup. */
export interface BudgetGroupLike {
  name: string;
  categories: string[];
}

/** Flatten a historical-averages response into a key → monthly_avg lookup. */
export function buildAvgMap(data: HistoricalAveragesResponse | undefined): AvgMap {
  const map: AvgMap = {};
  if (data) {
    for (const [key, info] of Object.entries(data.categories)) {
      map[key] = info.monthly_avg;
    }
  }
  return map;
}

/**
 * Flatten budget status into a key → {currentMonth, ytd} spend lookup,
 * covering both grouped/budgeted categories and unbudgeted ones.
 */
export function buildSpendingMap(status: BudgetStatusResponse | undefined): SpendingMap {
  const map: SpendingMap = {};
  if (status) {
    for (const group of status.groups) {
      for (const cat of group.categories) {
        map[cat.category] = { currentMonth: cat.current_month_spent, ytd: cat.ytd_spent };
      }
    }
    for (const cat of status.unbudgeted) {
      map[cat.category] = { currentMonth: cat.current_month_spent, ytd: cat.ytd_spent };
    }
  }
  return map;
}

/** Flatten history into a key → suggested monthly/type lookup for placeholders. */
export function buildSuggestedMap(hist: HistoricalAveragesResponse | undefined): SuggestedMap {
  const map: SuggestedMap = {};
  if (hist) {
    for (const [key, info] of Object.entries(hist.categories)) {
      map[key] = { suggestedMonthly: info.suggested_monthly, suggestedType: info.suggested_type };
    }
  }
  return map;
}

/**
 * Partition form entries into display groups following the configured group
 * order. Entries not claimed by any group fall into a trailing "Other" group.
 * Empty groups are dropped. Entry ordering within a group follows the group's
 * category order; the "Other" group preserves the original entry order.
 */
export function groupEntries(
  entries: CategoryFormEntry[],
  groups: readonly BudgetGroupLike[]
): GroupedEntries[] {
  const entryMap = new Map(entries.map((e) => [e.key, e]));
  const usedKeys = new Set<string>();
  const result: GroupedEntries[] = [];

  for (const group of groups) {
    const groupEntries: CategoryFormEntry[] = [];
    for (const cat of group.categories) {
      const entry = entryMap.get(cat);
      if (entry) {
        groupEntries.push(entry);
        usedKeys.add(cat);
      }
    }
    if (groupEntries.length > 0) {
      result.push({ name: group.name, entries: groupEntries });
    }
  }

  const ungrouped = entries.filter((e) => !usedKeys.has(e.key));
  if (ungrouped.length > 0) {
    result.push({ name: "Other", entries: ungrouped });
  }

  return result;
}

/**
 * Per-group subtotals. `monthly` sums each entry's monthly figure (annual/12
 * rounded to cents) so it matches the displayed monthly column; `annual` sums
 * raw targets. Missing map entries count as zero.
 */
export function computeGroupSubtotals(
  entries: CategoryFormEntry[],
  avg3Map: AvgMap,
  avg12Map: AvgMap,
  spendingMap: SpendingMap
): GroupSubtotals {
  return {
    avg3: entries.reduce((s, e) => s + (avg3Map[e.key] ?? 0), 0),
    avg12: entries.reduce((s, e) => s + (avg12Map[e.key] ?? 0), 0),
    currentMonth: entries.reduce((s, e) => s + (spendingMap[e.key]?.currentMonth ?? 0), 0),
    ytd: entries.reduce((s, e) => s + (spendingMap[e.key]?.ytd ?? 0), 0),
    monthly: entries.reduce((s, e) => s + Math.round((e.target / 12) * 100) / 100, 0),
    annual: entries.reduce((s, e) => s + e.target, 0),
  };
}

/**
 * Position (0–100) on a category's YTD pace bar where the fill will sit at
 * month end: YTD spend with the current month replaced by its projection.
 * Null when there is no projection or no yearly target.
 */
export function projectedYtdPct(cat: CategoryPaceDetail): number | null {
  if (cat.forecast_month_total == null || cat.target <= 0) return null;
  const projectedYtd = cat.ytd_spent - cat.current_month_spent + cat.forecast_month_total;
  return (projectedYtd / cat.target) * 100;
}

/**
 * Position (0–100) on the overall headline bar at projected month end.
 * The backend projection covers budgeted non-lumpy categories, so only that
 * basket's current-month spend is replaced; lumpy and unbudgeted spending
 * stays at its actual YTD value.
 */
export function projectedOverallYtdPct(status: BudgetStatusResponse): number | null {
  const projected = status.overall.projected_month_total;
  if (projected == null || status.overall.spending_ceiling <= 0) return null;
  const basketCurrentMonth = status.groups
    .flatMap((g) => g.categories)
    .filter((c) => c.category_type !== "lumpy")
    .reduce((s, c) => s + c.current_month_spent, 0);
  const projectedYtd = status.overall.ytd_spent - basketCurrentMonth + projected;
  return (projectedYtd / status.overall.spending_ceiling) * 100;
}

/** True when the category is projected to end the month over its monthly budget. */
export function forecastOverBudget(cat: CategoryPaceDetail): boolean {
  return (
    cat.forecast_month_total != null &&
    cat.monthly_amount > 0 &&
    cat.forecast_month_total > cat.monthly_amount
  );
}

/** Confidence range for the forecast tooltip, e.g. "Expected range $360–$410". */
export function forecastRangeLabel(cat: CategoryPaceDetail): string | null {
  if (cat.forecast_lower == null || cat.forecast_upper == null) return null;
  if (cat.forecast_lower === cat.forecast_upper) return null;
  return `Expected range ${formatForecastCurrency(cat.forecast_lower)}–${formatForecastCurrency(cat.forecast_upper)}`;
}
