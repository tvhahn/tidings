// @vitest-environment jsdom
import { describe, expect, it, beforeEach } from "vitest";
import {
  readOverlay,
  writeOverlay,
  deleteOverlay,
  listByPrefix,
  categoryOverrideKey,
  budgetOverrideKey,
} from "./demoOverlay";

describe("demoOverlay", () => {
  beforeEach(() => {
    sessionStorage.clear();
  });

  it("writes and reads a category override", () => {
    const key = categoryOverrideKey("user@example.com", "2026.03.14_10.30_file.eml");
    writeOverlay(key, "Groceries");
    expect(readOverlay(key)).toBe("Groceries");
  });

  it("returns undefined for missing key", () => {
    expect(readOverlay(categoryOverrideKey("a", "b"))).toBeUndefined();
  });

  it("overwrites existing value", () => {
    const key = categoryOverrideKey("u", "f");
    writeOverlay(key, "A");
    writeOverlay(key, "B");
    expect(readOverlay(key)).toBe("B");
  });

  it("deletes a key", () => {
    const key = categoryOverrideKey("u", "f");
    writeOverlay(key, "A");
    deleteOverlay(key);
    expect(readOverlay(key)).toBeUndefined();
  });

  it("lists by prefix", () => {
    writeOverlay(categoryOverrideKey("u1", "f1"), "X");
    writeOverlay(categoryOverrideKey("u2", "f2"), "Y");
    writeOverlay(budgetOverrideKey(2026), {
      spending_ceiling: 50000,
      categories: {},
      groups: [],
      targets_version: null,
      groups_version: null,
    });
    const cats = listByPrefix<string>("category-override:");
    expect(cats).toHaveLength(2);
    expect(cats.map((e) => e.value).sort()).toEqual(["X", "Y"]);
    const budgets = listByPrefix("budget:");
    expect(budgets).toHaveLength(1);
  });

  it("ignores malformed entries", () => {
    sessionStorage.setItem("demo-overlay:category-override:a:b", "not-json");
    const results = listByPrefix<string>("category-override:");
    expect(results).toHaveLength(0);
  });

  it("writes and reads a budget overlay with typed payload", () => {
    const payload = {
      spending_ceiling: 60000,
      categories: {
        Groceries: {
          target: 500,
          input_mode: "monthly" as const,
          category_type: "variable" as const,
        },
      },
      groups: [],
      targets_version: 3,
      groups_version: 1,
    };
    writeOverlay(budgetOverrideKey(2026), payload);
    expect(readOverlay(budgetOverrideKey(2026))).toEqual(payload);
  });
});
