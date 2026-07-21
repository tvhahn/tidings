import { create } from "zustand";
// Canonical definition lives with the formatter that consumes it (lib/format).
import type { DateFormat } from "@/lib/format";

export type { DateFormat };

const DATE_FORMAT_IDS = new Set<DateFormat>(["medium", "dmy", "iso", "legacy"]);

export type DateFormatOption = {
  id: DateFormat;
  label: string;
  /** Example of this format rendered for a known date (Apr 22, 2026). */
  sample: string;
};

export const DATE_FORMATS: DateFormatOption[] = [
  { id: "medium", label: "Medium (US)", sample: "Apr 22, 2026" },
  { id: "dmy", label: "Day Month Year", sample: "22 Apr 2026" },
  { id: "iso", label: "ISO", sample: "2026-04-22" },
  { id: "legacy", label: "Slash (legacy)", sample: "04/22/2026" },
];

/** Presentational style of the Journal headline strip. One data payload, two
 *  render treatments — a per-device presentation choice, not a config value. */
export type HeadlineVariant = "standard" | "timeline";

const HEADLINE_VARIANT_IDS = new Set<HeadlineVariant>(["standard", "timeline"]);

export type HeadlineVariantOption = {
  id: HeadlineVariant;
  label: string;
  /** One-line muted description of the treatment for the settings picker. */
  description: string;
};

export const HEADLINE_VARIANTS: HeadlineVariantOption[] = [
  {
    id: "standard",
    label: "Standard",
    description: "A quiet pace strip — the projection marks the bar, committed spend is the hatch.",
  },
  {
    id: "timeline",
    label: "Timeline",
    description:
      "A month line — a dot for each recorded day, penciled circles for the charges still ahead.",
  },
];

interface PreferencesState {
  dateFormat: DateFormat;
  setDateFormat: (fmt: DateFormat) => void;
  headlineVariant: HeadlineVariant;
  setHeadlineVariant: (variant: HeadlineVariant) => void;
}

function loadDateFormat(): DateFormat {
  const raw = localStorage.getItem("pref.dateFormat") as DateFormat | null;
  return raw && DATE_FORMAT_IDS.has(raw) ? raw : "medium";
}

function loadHeadlineVariant(): HeadlineVariant {
  const raw = localStorage.getItem("pref.headlineVariant") as HeadlineVariant | null;
  return raw && HEADLINE_VARIANT_IDS.has(raw) ? raw : "standard";
}

export const usePreferences = create<PreferencesState>((set) => ({
  dateFormat: loadDateFormat(),
  setDateFormat: (fmt) => {
    if (!DATE_FORMAT_IDS.has(fmt)) return;
    localStorage.setItem("pref.dateFormat", fmt);
    set({ dateFormat: fmt });
  },
  headlineVariant: loadHeadlineVariant(),
  setHeadlineVariant: (variant) => {
    if (!HEADLINE_VARIANT_IDS.has(variant)) return;
    localStorage.setItem("pref.headlineVariant", variant);
    set({ headlineVariant: variant });
  },
}));
