export type Severity = "neutral" | "warning" | "danger";

export function paceSeverity(pct: number): Severity {
  if (pct > 150) return "danger";
  if (pct >= 100) return "warning";
  return "neutral";
}

export const severityTextClass: Record<Severity, string> = {
  neutral: "",
  warning: "text-status-warning",
  // Calm red, not vibrant: with small category budgets, danger is a common
  // state on journal/budget rows — a wall of vibrant red stops reading as
  // signal and starts reading as alarm (see PaceBar's matching bar decision).
  // The -text variant brightens in dark mode so 12px meta stays AA; the plain
  // fill token is tuned for bars and measures ~2.6:1 as dark-mode text.
  danger: "text-status-danger-calm-text",
};
