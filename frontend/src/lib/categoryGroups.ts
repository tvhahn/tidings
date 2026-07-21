/**
 * Category grouping for charts and summary views.
 * Groups are loaded from the API (DynamoDB); DEFAULT_CATEGORY_GROUPS is the fallback.
 */

export interface CategoryGroup {
  name: string;
  categories: string[];
}

export const DEFAULT_CATEGORY_GROUPS: CategoryGroup[] = [
  {
    name: "Food & Dining",
    categories: ["groceries", "restaurant/dining", "liquor/beer/wine"],
  },
  {
    name: "Housing",
    categories: [
      "rent",
      "utilities",
      "house maintenance",
      "major property upgrades",
      "furniture",
      "household items",
    ],
  },
  {
    name: "Transport",
    categories: [
      "gasoline",
      "automotive maintenance",
      "misc. car expense",
      "car payment",
      "general transportation",
    ],
  },
  {
    name: "Health & Personal",
    categories: ["health care", "hygiene/personal care", "counselling", "sports and recreation"],
  },
  {
    name: "Entertainment",
    categories: ["entertainment", "hobbies", "subscriptions", "travel", "vacation"],
  },
  {
    name: "Shopping",
    categories: ["clothing", "technology", "computer", "gifts", "baby items"],
  },
  {
    name: "Bills & Services",
    categories: [
      "insurance",
      "communication/cell",
      "internet",
      "service charges/fees",
      "professional membership",
      "professional services",
      "accounting services",
      "education",
      "tuition",
      "taxes",
    ],
  },
];

const OTHER_GROUP = "Other";

/** Map a category name to its group name (or "Other"). */
export function groupCategory(
  category: string,
  groups: CategoryGroup[] = DEFAULT_CATEGORY_GROUPS
): string {
  const lower = category.toLowerCase();
  for (const g of groups) {
    if (g.categories.includes(lower)) return g.name;
  }
  return OTHER_GROUP;
}

/** Surface class that determines which tone of a hue to pick.
 *  - isDark: the `.dark` class is on <html>
 *  - isWarm: the active data-palette is a warm-surface palette (warm-paper, gruvbox)
 *
 *  Sourced at the call site via `useChartTone()` so components rerender on
 *  theme toggle. Pass-through, pure — do not read DOM state inside this file.
 */
export interface ChartTone {
  isDark: boolean;
  isWarm: boolean;
}

type HueTones = {
  coolLight: string;
  coolDark: string;
  warmLight: string;
  warmDark: string;
};

/** 12-hue palette — assigned to groups by index, tone picked per surface.
 *
 *  Design: hue is STABLE across every theme ("Food = orange" is a learned
 *  navigation aid that must survive palette switches). Tone is ADAPTIVE —
 *  every hue has four OKLch variants tuned to land in the ~3.5–5:1 contrast
 *  band against the representative `--card` surface of each class:
 *
 *    coolLight → default/nord/midnight/solarized (light)
 *    coolDark  → default/nord/midnight/solarized (dark)
 *    warmLight → warm-paper/gruvbox (light, cream/ochre cards)
 *    warmDark  → warm-paper/gruvbox (dark, warm-brown cards)
 *
 *  Tidings recalibration: chroma is intentionally low (~0.05–0.08, was
 *  0.10–0.18). The chart should feel like newsprint, not Recharts default.
 *  Hue identity preserved so "Food = orange" still reads — just calmer.
 *  Lightness shifted slightly to compensate for the reduced chroma so each
 *  hue still distinguishes from its neighbours.
 *
 *  When adding a new palette, update `isWarmPalette()` in stores/theme.ts
 *  to include it in the correct family. Add new hues at the end of this
 *  array; existing group→color assignments depend on index order. */
export const CATEGORY_HUES: HueTones[] = [
  {
    // orange — Food & Dining
    coolLight: "oklch(0.62 0.07 45)",
    coolDark: "oklch(0.74 0.07 50)",
    warmLight: "oklch(0.58 0.06 40)",
    warmDark: "oklch(0.74 0.07 55)",
  },
  {
    // blue — Housing
    coolLight: "oklch(0.60 0.07 255)",
    coolDark: "oklch(0.72 0.07 250)",
    warmLight: "oklch(0.56 0.06 250)",
    warmDark: "oklch(0.72 0.06 248)",
  },
  {
    // amber — Transport
    coolLight: "oklch(0.66 0.07 75)",
    coolDark: "oklch(0.78 0.07 80)",
    warmLight: "oklch(0.63 0.06 70)",
    warmDark: "oklch(0.78 0.07 75)",
  },
  {
    // pink — Health & Personal
    coolLight: "oklch(0.66 0.08 355)",
    coolDark: "oklch(0.74 0.07 350)",
    warmLight: "oklch(0.60 0.07 355)",
    warmDark: "oklch(0.72 0.07 350)",
  },
  {
    // purple — Entertainment
    coolLight: "oklch(0.62 0.08 295)",
    coolDark: "oklch(0.72 0.07 290)",
    warmLight: "oklch(0.56 0.06 285)",
    warmDark: "oklch(0.70 0.06 288)",
  },
  {
    // teal — Shopping
    coolLight: "oklch(0.64 0.06 185)",
    coolDark: "oklch(0.74 0.06 185)",
    warmLight: "oklch(0.58 0.05 190)",
    warmDark: "oklch(0.72 0.05 185)",
  },
  {
    // slate — Bills & Services
    coolLight: "oklch(0.55 0.025 240)",
    coolDark: "oklch(0.68 0.02 240)",
    warmLight: "oklch(0.50 0.02 55)",
    warmDark: "oklch(0.68 0.02 55)",
  },
  {
    // red — Charitable Giving
    coolLight: "oklch(0.62 0.08 25)",
    coolDark: "oklch(0.70 0.07 25)",
    warmLight: "oklch(0.58 0.07 25)",
    warmDark: "oklch(0.70 0.07 30)",
  },
  {
    // emerald
    coolLight: "oklch(0.62 0.07 155)",
    coolDark: "oklch(0.74 0.06 155)",
    warmLight: "oklch(0.58 0.06 150)",
    warmDark: "oklch(0.72 0.06 155)",
  },
  {
    // mustard
    coolLight: "oklch(0.66 0.07 95)",
    coolDark: "oklch(0.78 0.07 95)",
    warmLight: "oklch(0.60 0.06 85)",
    warmDark: "oklch(0.74 0.06 88)",
  },
  {
    // indigo
    coolLight: "oklch(0.58 0.07 275)",
    coolDark: "oklch(0.72 0.06 270)",
    warmLight: "oklch(0.54 0.06 270)",
    warmDark: "oklch(0.70 0.06 270)",
  },
  {
    // cyan
    coolLight: "oklch(0.66 0.06 215)",
    coolDark: "oklch(0.78 0.06 210)",
    warmLight: "oklch(0.60 0.05 215)",
    warmDark: "oklch(0.74 0.05 215)",
  },
];

const OTHER_TONES: HueTones = {
  coolLight: "oklch(0.62 0 0)",
  coolDark: "oklch(0.66 0 0)",
  warmLight: "oklch(0.56 0.012 60)",
  warmDark: "oklch(0.66 0.012 60)",
};

function pickTone(tones: HueTones, tone: ChartTone): string {
  if (tone.isDark) return tone.isWarm ? tones.warmDark : tones.coolDark;
  return tone.isWarm ? tones.warmLight : tones.coolLight;
}

/** Get the color for a group by its position in the groups list.
 *  "Other" always gets a neutral tone for the active surface. */
export function getGroupColor(groupName: string, groups: CategoryGroup[], tone: ChartTone): string {
  if (groupName === OTHER_GROUP) return pickTone(OTHER_TONES, tone);
  const idx = groups.findIndex((g) => g.name === groupName);
  if (idx < 0) return pickTone(OTHER_TONES, tone);
  return pickTone(CATEGORY_HUES[idx % CATEGORY_HUES.length] ?? OTHER_TONES, tone);
}

/** Return the palette color at a given index, surface-adapted.
 *  Used by GroupEditorDialog to preview the color a new group will receive. */
export function getPaletteColorByIndex(idx: number, tone: ChartTone): string {
  return pickTone(CATEGORY_HUES[idx % CATEGORY_HUES.length] ?? OTHER_TONES, tone);
}

/** Number of distinct hues in the palette (for wrap-around math). */
export const PALETTE_SIZE = CATEGORY_HUES.length;
