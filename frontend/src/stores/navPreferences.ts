import { create } from "zustand";
import { CUSTOMIZABLE_TABS, DEFAULT_ORDER, SETTINGS_HREF, sortBySection } from "@/config/navTabs";

const ORDER_KEY = "nav.tabOrder";
const HIDDEN_KEY = "nav.hiddenTabs";

const VALID_HREFS = new Set(CUSTOMIZABLE_TABS.map((t) => t.href));

function parseArray(raw: string | null): string[] {
  if (!raw) return [];
  try {
    const parsed = JSON.parse(raw);
    return Array.isArray(parsed) ? parsed.filter((x): x is string => typeof x === "string") : [];
  } catch {
    return [];
  }
}

function loadOrder(): string[] {
  const saved = parseArray(localStorage.getItem(ORDER_KEY)).filter(
    (h) => VALID_HREFS.has(h) && h !== SETTINGS_HREF
  );
  // Dedupe while preserving order
  const seen = new Set<string>();
  const ordered = saved.filter((h) => {
    if (seen.has(h)) return false;
    seen.add(h);
    return true;
  });
  // Migration: append any tabs present in defaults but missing from saved
  const missing = DEFAULT_ORDER.filter((h) => !seen.has(h));
  // Always group main items before workspace items, preserving intra-section order
  return sortBySection([...ordered, ...missing]);
}

function loadHidden(): string[] {
  return parseArray(localStorage.getItem(HIDDEN_KEY)).filter(
    (h) => VALID_HREFS.has(h) && h !== SETTINGS_HREF
  );
}

function persistOrder(order: string[]) {
  localStorage.setItem(ORDER_KEY, JSON.stringify(order));
}

function persistHidden(hidden: string[]) {
  localStorage.setItem(HIDDEN_KEY, JSON.stringify(hidden));
}

interface NavPrefsState {
  tabOrder: string[];
  hiddenTabs: string[];
  setOrder: (hrefs: string[]) => void;
  toggleHidden: (href: string) => void;
  reset: () => void;
}

export const useNavPreferences = create<NavPrefsState>((set, get) => ({
  tabOrder: loadOrder(),
  hiddenTabs: loadHidden(),
  setOrder: (hrefs) => {
    const seen = new Set<string>();
    const cleaned = hrefs.filter((h) => {
      if (!VALID_HREFS.has(h) || h === SETTINGS_HREF) return false;
      if (seen.has(h)) return false;
      seen.add(h);
      return true;
    });
    const missing = DEFAULT_ORDER.filter((h) => !seen.has(h));
    const next = sortBySection([...cleaned, ...missing]);
    persistOrder(next);
    set({ tabOrder: next });
  },
  toggleHidden: (href) => {
    if (href === SETTINGS_HREF || !VALID_HREFS.has(href)) return;
    const curr = get().hiddenTabs;
    const next = curr.includes(href) ? curr.filter((h) => h !== href) : [...curr, href];
    persistHidden(next);
    set({ hiddenTabs: next });
  },
  reset: () => {
    localStorage.removeItem(ORDER_KEY);
    localStorage.removeItem(HIDDEN_KEY);
    set({ tabOrder: sortBySection([...DEFAULT_ORDER]), hiddenTabs: [] });
  },
}));
