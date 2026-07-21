import type { CategoryPaceDetail } from "@/types/api";

/**
 * L11 — whisper heat map. Returns the wash class for a monthly-matrix cell.
 *
 * `""` when the budget basis is unset/lumpy (`monthlyBudget <= 0`) or the cell
 * is empty (`spent <= 0`) — an empty cell is never tinted. Danger wash at ratio
 * ≥ 1.0, warning wash at ≥ 0.9, otherwise no tint.
 */
export function heatClass(
  spent: number,
  monthlyBudget: number
): "" | "bg-status-warning-wash" | "bg-status-danger-wash" {
  if (monthlyBudget <= 0 || spent <= 0) return "";
  const ratio = spent / monthlyBudget;
  if (ratio >= 1.0) return "bg-status-danger-wash";
  if (ratio >= 0.9) return "bg-status-warning-wash";
  return "";
}

/**
 * Budget basis for a group row: the sum of member non-lumpy monthly amounts
 * (lumpy categories have no steady monthly budget to tint against).
 */
export function groupMonthlyBudget(categories: CategoryPaceDetail[]): number {
  return categories
    .filter((c) => c.category_type !== "lumpy")
    .reduce((s, c) => s + c.monthly_amount, 0);
}
