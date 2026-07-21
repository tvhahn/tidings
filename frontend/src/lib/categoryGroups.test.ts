import { describe, expect, it } from "vitest";
import {
  groupCategory,
  getGroupColor,
  getPaletteColorByIndex,
  CATEGORY_HUES,
  PALETTE_SIZE,
  DEFAULT_CATEGORY_GROUPS,
} from "./categoryGroups";
import type { ChartTone } from "./categoryGroups";

const COOL_LIGHT: ChartTone = { isDark: false, isWarm: false };
const COOL_DARK: ChartTone = { isDark: true, isWarm: false };
const WARM_LIGHT: ChartTone = { isDark: false, isWarm: true };
const WARM_DARK: ChartTone = { isDark: true, isWarm: true };
const ALL_TONES: [string, ChartTone][] = [
  ["coolLight", COOL_LIGHT],
  ["coolDark", COOL_DARK],
  ["warmLight", WARM_LIGHT],
  ["warmDark", WARM_DARK],
];

describe("groupCategory", () => {
  it("maps groceries to Food & Dining", () => {
    expect(groupCategory("groceries")).toBe("Food & Dining");
  });

  it("maps restaurant/dining to Food & Dining", () => {
    expect(groupCategory("restaurant/dining")).toBe("Food & Dining");
  });

  it("maps rent to Housing", () => {
    expect(groupCategory("rent")).toBe("Housing");
  });

  it("maps gasoline to Transport", () => {
    expect(groupCategory("gasoline")).toBe("Transport");
  });

  it("maps health care to Health & Personal", () => {
    expect(groupCategory("health care")).toBe("Health & Personal");
  });

  it("maps entertainment to Entertainment", () => {
    expect(groupCategory("entertainment")).toBe("Entertainment");
  });

  it("maps clothing to Shopping", () => {
    expect(groupCategory("clothing")).toBe("Shopping");
  });

  it("maps insurance to Bills & Services", () => {
    expect(groupCategory("insurance")).toBe("Bills & Services");
  });

  it("returns Other for unknown category", () => {
    expect(groupCategory("cryptocurrency")).toBe("Other");
  });

  it("returns Other for empty string", () => {
    expect(groupCategory("")).toBe("Other");
  });

  it("is case insensitive", () => {
    expect(groupCategory("GROCERIES")).toBe("Food & Dining");
    expect(groupCategory("Rent")).toBe("Housing");
    expect(groupCategory("Health Care")).toBe("Health & Personal");
  });

  it("accepts custom group list", () => {
    const custom = [{ name: "Custom", categories: ["foo"] }];
    expect(groupCategory("foo", custom)).toBe("Custom");
    expect(groupCategory("bar", custom)).toBe("Other");
  });
});

describe("DEFAULT_CATEGORY_GROUPS coverage", () => {
  it("has no duplicate categories across groups", () => {
    const seen = new Set<string>();
    for (const group of DEFAULT_CATEGORY_GROUPS) {
      for (const cat of group.categories) {
        expect(seen.has(cat), `"${cat}" appears in multiple groups`).toBe(false);
        seen.add(cat);
      }
    }
  });
});

describe("getGroupColor", () => {
  const groups = [
    { name: "Alpha", categories: ["a"] },
    { name: "Beta", categories: ["b"] },
    { name: "Gamma", categories: ["c"] },
  ];

  it.each(ALL_TONES)("returns palette color by group index (%s)", (_, tone) => {
    const key = tone.isDark
      ? tone.isWarm
        ? "warmDark"
        : "coolDark"
      : tone.isWarm
        ? "warmLight"
        : "coolLight";
    expect(getGroupColor("Alpha", groups, tone)).toBe(CATEGORY_HUES[0]![key]);
    expect(getGroupColor("Beta", groups, tone)).toBe(CATEGORY_HUES[1]![key]);
    expect(getGroupColor("Gamma", groups, tone)).toBe(CATEGORY_HUES[2]![key]);
  });

  it("returns neutral tone for Other", () => {
    const seen = new Set<string>();
    for (const [, tone] of ALL_TONES) {
      const c = getGroupColor("Other", groups, tone);
      expect(c).toMatch(/^oklch/);
      seen.add(c);
    }
    // All four surface classes must return distinct "Other" tones.
    expect(seen.size).toBe(4);
  });

  it("returns neutral tone for unknown group", () => {
    expect(getGroupColor("Nonexistent", groups, COOL_LIGHT)).toBe(
      getGroupColor("Other", groups, COOL_LIGHT)
    );
  });

  it("wraps palette for many groups", () => {
    const manyGroups = Array.from({ length: PALETTE_SIZE + 3 }, (_, i) => ({
      name: `Group ${i}`,
      categories: [],
    }));
    // Index PALETTE_SIZE wraps around to 0
    expect(getGroupColor(`Group ${PALETTE_SIZE}`, manyGroups, COOL_LIGHT)).toBe(
      CATEGORY_HUES[0]!.coolLight
    );
    expect(getGroupColor(`Group ${PALETTE_SIZE + 1}`, manyGroups, COOL_LIGHT)).toBe(
      CATEGORY_HUES[1]!.coolLight
    );
  });

  it("returns a distinct color for each surface class", () => {
    const seen = new Set<string>();
    for (const [, tone] of ALL_TONES) {
      seen.add(getGroupColor("Alpha", groups, tone));
    }
    expect(seen.size).toBe(4);
  });
});

describe("getPaletteColorByIndex", () => {
  it("indexes into CATEGORY_HUES with wrap-around", () => {
    expect(getPaletteColorByIndex(0, COOL_LIGHT)).toBe(CATEGORY_HUES[0]!.coolLight);
    expect(getPaletteColorByIndex(PALETTE_SIZE, COOL_LIGHT)).toBe(CATEGORY_HUES[0]!.coolLight);
    expect(getPaletteColorByIndex(1, COOL_DARK)).toBe(CATEGORY_HUES[1]!.coolDark);
  });
});
