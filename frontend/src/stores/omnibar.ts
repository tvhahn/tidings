import { create } from "zustand";

/**
 * One remembered Omnibar interaction, shown in the empty-input "Recent" group.
 * `kind` distinguishes a computed answer the user ran (`query` — label is the
 * original input the user typed) from a plain navigation (`destination` — label
 * is the page/action/month row's own text). `to` is the route that selecting
 * the recent re-navigates to, and is the dedupe key.
 */
export interface OmniRecent {
  kind: "query" | "destination";
  label: string;
  to: string;
  at: number;
}

const RECENTS_KEY = "omnibar.recents";
const MAX_RECENTS = 8;

function isRecent(value: unknown): value is OmniRecent {
  if (typeof value !== "object" || value === null) return false;
  const v = value as Record<string, unknown>;
  return (
    (v.kind === "query" || v.kind === "destination") &&
    typeof v.label === "string" &&
    typeof v.to === "string" &&
    typeof v.at === "number"
  );
}

function loadRecents(): OmniRecent[] {
  const raw = localStorage.getItem(RECENTS_KEY);
  if (!raw) return [];
  try {
    const parsed = JSON.parse(raw);
    if (!Array.isArray(parsed)) return [];
    return parsed.filter(isRecent).slice(0, MAX_RECENTS);
  } catch {
    return [];
  }
}

function persistRecents(recents: OmniRecent[]) {
  localStorage.setItem(RECENTS_KEY, JSON.stringify(recents));
}

interface OmnibarState {
  recents: OmniRecent[];
  addRecent: (entry: OmniRecent) => void;
  clearRecents: () => void;
}

export const useOmnibarStore = create<OmnibarState>((set, get) => ({
  recents: loadRecents(),
  addRecent: (entry) => {
    // Dedupe by `to`: an existing entry for the same destination is dropped so
    // the new one moves to the front. Cap at the most recent MAX_RECENTS.
    const deduped = get().recents.filter((r) => r.to !== entry.to);
    const next = [entry, ...deduped].slice(0, MAX_RECENTS);
    persistRecents(next);
    set({ recents: next });
  },
  clearRecents: () => {
    localStorage.removeItem(RECENTS_KEY);
    set({ recents: [] });
  },
}));
