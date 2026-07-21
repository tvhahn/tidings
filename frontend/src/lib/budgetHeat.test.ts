import { describe, expect, it } from "vitest";
import type { CategoryPaceDetail } from "@/types/api";
import { groupMonthlyBudget, heatClass } from "./budgetHeat";

function cat(
  category_type: CategoryPaceDetail["category_type"],
  monthly_amount: number
): CategoryPaceDetail {
  return { category_type, monthly_amount } as CategoryPaceDetail;
}

describe("heatClass", () => {
  it("returns no tint below 0.9", () => {
    // ratio 0.89 → 89 spent against 100 budget
    expect(heatClass(89, 100)).toBe("");
  });

  it("returns warning wash from 0.9 up to but not including 1.0", () => {
    expect(heatClass(90, 100)).toBe("bg-status-warning-wash");
    expect(heatClass(99.9, 100)).toBe("bg-status-warning-wash");
  });

  it("returns danger wash at 1.0 and above", () => {
    expect(heatClass(100, 100)).toBe("bg-status-danger-wash");
    expect(heatClass(223, 100)).toBe("bg-status-danger-wash");
  });

  it("never tints when the budget basis is unset or lumpy", () => {
    expect(heatClass(500, 0)).toBe("");
    expect(heatClass(500, -1)).toBe("");
  });

  it("never tints an empty cell even with a budget", () => {
    expect(heatClass(0, 100)).toBe("");
  });
});

describe("groupMonthlyBudget", () => {
  it("sums non-lumpy monthly amounts only", () => {
    const cats = [cat("fixed", 2000), cat("variable", 600), cat("lumpy", 1000)];
    expect(groupMonthlyBudget(cats)).toBe(2600);
  });

  it("returns 0 for an empty group", () => {
    expect(groupMonthlyBudget([])).toBe(0);
  });
});
