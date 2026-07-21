import { create } from "zustand";

type ThemeMode = "light" | "dark" | "system";
export type Palette = "default" | "warm-paper" | "nord" | "midnight" | "solarized" | "gruvbox";

// SSR-safety (L3/C2): the marketing tree imports this store during the
// prerender (entry-server.tsx), where window/localStorage/matchMedia are
// absent. Guard the three module-scope reads; setters (applyTheme) only run
// on user events, so they stay unguarded.
const canUseDom = typeof window !== "undefined";

export type PaletteOption = {
  id: Palette;
  label: string;
  /** [background, card, primary] — hardcoded OKLch for swatch previews */
  chips: [string, string, string];
};

/** Source of truth for available palettes. AppearanceSection maps over this. */
export const PALETTES: PaletteOption[] = [
  {
    id: "warm-paper",
    label: "Warm Paper",
    chips: ["oklch(0.975 0.015 75)", "oklch(0.945 0.02 75)", "oklch(0.45 0.12 40)"],
  },
  {
    id: "default",
    label: "Plain",
    chips: ["oklch(1 0 0)", "oklch(0.965 0 0)", "oklch(0.205 0 0)"],
  },
  {
    id: "nord",
    label: "Nord",
    chips: ["oklch(0.96 0.012 240)", "oklch(0.93 0.015 240)", "oklch(0.55 0.09 230)"],
  },
  {
    id: "midnight",
    label: "Midnight",
    chips: ["oklch(0.18 0.02 265)", "oklch(0.24 0.025 265)", "oklch(0.75 0.17 275)"],
  },
  {
    id: "solarized",
    label: "Solarized",
    chips: ["oklch(0.96 0.02 90)", "oklch(0.92 0.03 90)", "oklch(0.55 0.14 200)"],
  },
  {
    id: "gruvbox",
    label: "Gruvbox",
    chips: ["oklch(0.93 0.04 85)", "oklch(0.88 0.05 85)", "oklch(0.5 0.15 40)"],
  },
];

const PALETTE_IDS = new Set(PALETTES.map((p) => p.id));

/** Palettes whose light + dark surfaces are warm (cream/ochre/brown) rather
 *  than cool/achromatic. Chart tones pick earthier variants on these to
 *  maintain contrast and avoid the Tailwind-on-cream-kraft clash. Update
 *  this when adding a palette — it pairs with CATEGORY_HUES in
 *  lib/categoryGroups.ts. */
const WARM_PALETTES = new Set<Palette>(["warm-paper", "gruvbox"]);
export function isWarmPalette(palette: Palette): boolean {
  return WARM_PALETTES.has(palette);
}

interface ThemeState {
  mode: ThemeMode;
  palette: Palette;
  setMode: (mode: ThemeMode) => void;
  setPalette: (palette: Palette) => void;
}

function applyTheme(mode: ThemeMode, palette: Palette) {
  const isDark =
    mode === "dark" || (mode === "system" && matchMedia("(prefers-color-scheme:dark)").matches);
  document.documentElement.classList.toggle("dark", isDark);
  if (palette === "default") {
    delete document.documentElement.dataset.palette;
  } else {
    document.documentElement.dataset.palette = palette;
  }
  localStorage.setItem("theme", mode);
  localStorage.setItem("theme.palette", palette);
}

/** New users start on the Warm Paper palette. A stored choice always wins —
 *  including an explicit "default" (the base "Plain" palette) — so anyone who
 *  ever touched appearance keeps exactly what they picked. Mirrors the FOWC
 *  inline scripts in index.html / demo/index.html. */
const DEFAULT_PALETTE: Palette = "warm-paper";

function loadPalette(): Palette {
  const raw = canUseDom ? (localStorage.getItem("theme.palette") as Palette | null) : null;
  return raw && PALETTE_IDS.has(raw) ? raw : DEFAULT_PALETTE;
}

/** Every surface — real app, marketing landing, demo SPA — defaults new users to
 *  light mode. The FOWC inline scripts in index.html / demo/index.html mirror
 *  this default. A stored choice always wins. */
function defaultMode(): ThemeMode {
  return "light";
}

export const useTheme = create<ThemeState>((set, get) => ({
  mode: (canUseDom ? (localStorage.getItem("theme") as ThemeMode) : null) || defaultMode(),
  palette: loadPalette(),
  setMode: (mode) => {
    applyTheme(mode, get().palette);
    set({ mode });
  },
  setPalette: (palette) => {
    if (!PALETTE_IDS.has(palette)) return;
    applyTheme(get().mode, palette);
    set({ palette });
  },
}));

// Listen for OS theme changes when mode is "system"
if (canUseDom) {
  matchMedia("(prefers-color-scheme:dark)").addEventListener("change", () => {
    const { mode, palette } = useTheme.getState();
    if (mode === "system") {
      applyTheme("system", palette);
    }
  });
}
