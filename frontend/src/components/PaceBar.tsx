type PaceTone = "under" | "on_track" | "warning" | "over" | "auto";

interface PaceBarProps {
  /** Ratio as percent (0–∞). Fill visually clamps to 100%. */
  pct: number;
  /** Optional vertical tick position (0–100). Omit for no tick. */
  benchmark?: number | null;
  /** Explicit tone override. Default "auto" uses 70/90 thresholds on pct. */
  tone?: PaceTone;
  /** Track height. Default "md". */
  size?: "xs" | "sm" | "md";
  /** Optional projected-endpoint diamond: position (0–100) and over-budget tone. */
  forecast?: { pct: number; over: boolean } | null;
}

const toneClasses: Record<Exclude<PaceTone, "auto">, string> = {
  under: "bg-status-success",
  on_track: "bg-status-info",
  warning: "bg-status-warning",
  // Calm over-budget red: a wall of bars at ≥90% stops reading as alarm.
  // Per-row text severity matches (severityTextClass in lib/severity.ts).
  over: "bg-status-danger-calm",
};

const sizeClasses: Record<NonNullable<PaceBarProps["size"]>, string> = {
  xs: "h-1",
  sm: "h-2",
  md: "h-3",
};

function autoTone(pct: number): Exclude<PaceTone, "auto"> {
  if (pct >= 90) return "over";
  if (pct >= 70) return "warning";
  return "under";
}

export function PaceBar({ pct, benchmark, tone = "auto", size = "md", forecast }: PaceBarProps) {
  const resolvedTone: Exclude<PaceTone, "auto"> = tone === "auto" ? autoTone(pct) : tone;
  const fillPct = Math.min(Math.max(pct, 0), 100);
  const height = sizeClasses[size];

  return (
    // The track clips its fill, but the wrapper doesn't — the forecast
    // diamond can sit just past the right edge when projected over budget.
    <div className={`relative w-full ${height}`}>
      <div className={`absolute inset-0 overflow-hidden rounded-full bg-muted-foreground/15`}>
        <div
          className={`absolute left-0 top-0 rounded-full ${height} ${toneClasses[resolvedTone]}`}
          style={{ width: `${fillPct}%` }}
        />
        {benchmark != null && (
          <div
            className={`absolute top-0 w-px ${height} bg-foreground/40`}
            style={{ left: `${Math.min(Math.max(benchmark, 0), 100)}%` }}
          />
        )}
      </div>
      {forecast != null && (
        <div
          aria-hidden="true"
          className={`absolute top-1/2 h-2.5 w-2.5 -translate-x-1/2 -translate-y-1/2 rotate-45 rounded-[1px] border bg-background ${
            forecast.over ? "border-status-danger-calm" : "border-muted-foreground/60"
          }`}
          style={{ left: `${Math.min(Math.max(forecast.pct, 0), 102)}%` }}
        />
      )}
    </div>
  );
}
