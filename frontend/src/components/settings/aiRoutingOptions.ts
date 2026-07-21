/**
 * Curated option lists for the Intelligence tab's task-routing selects.
 *
 * The provider / model / reasoning-effort choices are verified against the
 * live OpenAI and Anthropic surfaces and change rarely; keeping them in one
 * module lets the four routing rows share a single source of truth. Purely
 * static data + small pure helpers — no React, no data fetching — so it lives
 * beside the section components rather than under `src/lib` (which carries a
 * coverage floor these constants would only dilute).
 */
import type { AiProvider, CategorizationProvider, ReasoningEffort } from "@/types/api";

/**
 * Sentinel Select value that maps to an explicit `null` at the mutate boundary.
 * shadcn/Radix `SelectItem` forbids empty-string values, so "provider default"
 * needs a real, non-empty token that we translate back to `null` on change.
 */
export const DEFAULT_VALUE = "__default__";

export type SelectableOption = { value: string; label: string };

/** Full provider column (daily summaries, insights, document parsing). */
export const PROVIDER_OPTIONS: { value: AiProvider; label: string }[] = [
  { value: "disabled", label: "Disabled" },
  { value: "openai", label: "OpenAI API" },
  { value: "claude_cli", label: "Claude Code" },
  { value: "codex", label: "OpenAI Codex" },
  { value: "gemini_cli", label: "Google Gemini" },
];

/** Categorization column — OpenAI-family providers only. */
export const CATEGORIZATION_PROVIDER_OPTIONS: { value: CategorizationProvider; label: string }[] = [
  { value: "disabled", label: "Disabled" },
  { value: "openai", label: "OpenAI API" },
  { value: "codex", label: "OpenAI Codex" },
];

// Model lists per provider. The first entry is always the provider default,
// carrying the sentinel value so selecting it clears the stored model to null.
const OPENAI_MODELS: SelectableOption[] = [
  { value: DEFAULT_VALUE, label: "Default (gpt-5.4-nano)" },
  { value: "gpt-5.6-sol", label: "gpt-5.6-sol — flagship" },
  { value: "gpt-5.6-terra", label: "gpt-5.6-terra — balanced" },
  { value: "gpt-5.6-luna", label: "gpt-5.6-luna — fast" },
  { value: "gpt-5.5", label: "gpt-5.5" },
  { value: "gpt-5.4", label: "gpt-5.4" },
  { value: "gpt-5.4-mini", label: "gpt-5.4-mini" },
  { value: "gpt-5.4-nano", label: "gpt-5.4-nano — cheapest" },
];

const CODEX_MODELS: SelectableOption[] = [
  { value: DEFAULT_VALUE, label: "Default (CLI default)" },
  { value: "gpt-5.6-sol", label: "gpt-5.6-sol — flagship" },
  { value: "gpt-5.6-terra", label: "gpt-5.6-terra — balanced" },
  { value: "gpt-5.6-luna", label: "gpt-5.6-luna — fast" },
  { value: "gpt-5.5", label: "gpt-5.5" },
  { value: "gpt-5.4", label: "gpt-5.4" },
  { value: "gpt-5.4-mini", label: "gpt-5.4-mini" },
];

const CLAUDE_MODELS: SelectableOption[] = [
  { value: DEFAULT_VALUE, label: "Default (sonnet)" },
  { value: "sonnet", label: "Sonnet" },
  { value: "haiku", label: "Haiku" },
  { value: "opus", label: "Opus" },
];

// Reasoning-effort tokens per provider. gemini_cli / disabled expose none.
const OPENAI_EFFORTS: ReasoningEffort[] = ["none", "low", "medium", "high", "xhigh"];
const CODEX_EFFORTS: ReasoningEffort[] = ["low", "medium", "high", "xhigh"];
const CLAUDE_EFFORTS: ReasoningEffort[] = ["low", "medium", "high", "xhigh", "max"];

const EFFORT_LABELS: Record<ReasoningEffort, string> = {
  none: "None",
  minimal: "Minimal",
  low: "Low",
  medium: "Medium",
  high: "High",
  xhigh: "Extra high",
  max: "Maximum",
};

/**
 * Append the persisted value as its own item when a hand-edited `config.json`
 * carries a model/effort outside the curated list, so the Select renders the
 * real value instead of going blank.
 */
function withPersisted(items: SelectableOption[], current: string | null): SelectableOption[] {
  if (current == null || current === DEFAULT_VALUE) return items;
  if (items.some((item) => item.value === current)) return items;
  return [...items, { value: current, label: current }];
}

/**
 * Model items for a provider, or `null` when the provider has no model choice
 * (gemini_cli, disabled) and the Select should be hidden entirely. `current`
 * is the persisted model so an off-list value is preserved as a selectable item.
 */
export function modelItemsFor(provider: string, current: string | null): SelectableOption[] | null {
  const base =
    provider === "openai"
      ? OPENAI_MODELS
      : provider === "codex"
        ? CODEX_MODELS
        : provider === "claude_cli"
          ? CLAUDE_MODELS
          : null;
  return base ? withPersisted(base, current) : null;
}

/**
 * Reasoning-effort items for a provider, or `null` when the provider exposes no
 * effort control (gemini_cli, disabled). Always leads with the default sentinel.
 */
export function effortItemsFor(
  provider: string,
  current: string | null
): SelectableOption[] | null {
  const efforts =
    provider === "openai"
      ? OPENAI_EFFORTS
      : provider === "codex"
        ? CODEX_EFFORTS
        : provider === "claude_cli"
          ? CLAUDE_EFFORTS
          : null;
  if (!efforts) return null;
  const items: SelectableOption[] = [
    { value: DEFAULT_VALUE, label: "Default" },
    ...efforts.map((effort) => ({ value: effort, label: EFFORT_LABELS[effort] })),
  ];
  return withPersisted(items, current);
}

/** Select value for a nullable stored field: the sentinel stands in for null. */
export function selectValue(stored: string | null): string {
  return stored ?? DEFAULT_VALUE;
}

/** Translate a Select value back to the stored representation (sentinel → null). */
export function storedValue(selected: string): string | null {
  return selected === DEFAULT_VALUE ? null : selected;
}
