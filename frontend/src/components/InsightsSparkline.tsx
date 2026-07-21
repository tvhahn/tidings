import { useMemo } from "react";
import { useJournal } from "@/hooks/useJournal";
import { formatCurrency } from "@/lib/format";

interface InsightsSparklineProps {
  month: string;
}

/** A calm daily-spend sparkline header for the Insights page.
 *  Reuses Journal's day-by-day data; renders as a thin row of bars (one per
 *  day of month) with the current/last day brand-tinted. Mirrors the
 *  calendar-strip vibe but at smaller scale. */
export function InsightsSparkline({ month }: InsightsSparklineProps) {
  const { data } = useJournal(month);
  const daysInMonth = useMemo(() => {
    const [y, m] = month.split("-").map(Number);
    if (!y || !m) return 30;
    return new Date(y, m, 0).getDate();
  }, [month]);

  const dailyTotals = useMemo<number[]>(() => {
    if (!data) return Array.from({ length: daysInMonth }, () => 0);
    const map = new Map<number, number>();
    for (const d of data.days) {
      const day = parseInt(d.date.slice(-2), 10);
      if (Number.isFinite(day)) map.set(day, d.day_total);
    }
    return Array.from({ length: daysInMonth }, (_, i) => map.get(i + 1) ?? 0);
  }, [data, daysInMonth]);

  const max = Math.max(1, ...dailyTotals);
  const totalSpend = dailyTotals.reduce((s, v) => s + v, 0);
  const avg = totalSpend > 0 ? totalSpend / dailyTotals.filter((v) => v > 0).length : 0;
  const lastDayWithSpend = (() => {
    for (let i = dailyTotals.length - 1; i >= 0; i--) {
      if (dailyTotals[i] && (dailyTotals[i] ?? 0) > 0) return i;
    }
    return -1;
  })();

  return (
    <div className="rounded-[14px] border border-border bg-card px-5 py-4">
      <div className="flex items-baseline justify-between gap-3">
        <div>
          <div className="text-[10.5px] font-medium uppercase tracking-[0.08em] text-fg-muted">
            Daily spending
          </div>
          <div className="mt-1 text-[20px] font-semibold leading-tight tracking-[-0.01em] text-fg tabular-nums">
            {formatCurrency(totalSpend)}
          </div>
        </div>
        {avg > 0 && (
          <div className="text-right text-[11.5px] text-fg-muted tabular-nums">
            avg {formatCurrency(avg)}/day
          </div>
        )}
      </div>
      <div className="mt-3 flex h-12 items-end gap-[2px]" aria-hidden>
        {dailyTotals.map((v, i) => {
          const height = max > 0 ? (v / max) * 100 : 0;
          const isLatest = i === lastDayWithSpend;
          return (
            <div
              key={i}
              className={`flex-1 rounded-t-[2px] ${
                isLatest
                  ? "bg-brand"
                  : v > 0
                    ? "bg-[color-mix(in_oklch,var(--fg-muted)_50%,transparent)]"
                    : "bg-[color-mix(in_oklch,var(--fg-muted)_15%,transparent)]"
              }`}
              style={{ minHeight: v > 0 ? 2 : 1, height: `${Math.max(height, v > 0 ? 4 : 1)}%` }}
            />
          );
        })}
      </div>
    </div>
  );
}
