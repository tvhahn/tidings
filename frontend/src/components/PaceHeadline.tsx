import { PaceBar } from "@/components/PaceBar";
import { Card, CardContent } from "@/components/ui/card";
import { formatForecastCurrency, projectedOverallYtdPct } from "@/lib/budgetCalc";
import { formatCurrency } from "@/lib/format";
import type { BudgetStatusResponse } from "@/types/api";

interface PaceHeadlineProps {
  status: BudgetStatusResponse;
}

/** Keep the absolute bar labels off the clipped edges (L10). */
function clampPos(pct: number): number {
  return Math.min(Math.max(pct, 2), 98);
}

export function PaceHeadline({ status }: PaceHeadlineProps) {
  const { overall } = status;
  const isGood = overall.status === "under" || overall.status === "on_track";
  const forecastPos = projectedOverallYtdPct(status);
  const projectedOver = overall.projected_month_status === "over";
  const benchmark = status.elapsed_year_fraction * 100;

  // Find most off-pace categories (over status, sorted by most negative variance)
  const offPace = status.groups
    .flatMap((g) => g.categories)
    .filter((c) => c.status === "over")
    .sort((a, b) => a.variance - b.variance)
    .slice(0, 4);

  return (
    <Card
      className={`${
        isGood
          ? "border-status-success/25 bg-status-success/[0.03]"
          : "border-status-danger-calm/30 bg-status-danger-calm/[0.025]"
      }`}
    >
      <CardContent className="py-4">
        <div className="grid gap-4 md:grid-cols-2 md:divide-x md:divide-border">
          {/* Left — the state, the ceiling, and the page's only bar */}
          <div className="md:pr-6">
            <p
              className={`t-h2 tabular-nums ${
                isGood ? "text-status-success" : "text-status-danger-calm-text"
              }`}
            >
              {overall.headline}
            </p>
            <p className="mt-1.5 text-[12.5px] text-fg-muted">
              {formatCurrency(overall.ytd_spent)} spent of{" "}
              {formatCurrency(overall.spending_ceiling)} ceiling ·{" "}
              {(status.elapsed_year_fraction * 100).toFixed(1)}% through year
            </p>
            <div className="mt-2.5">
              <PaceBar
                pct={
                  overall.spending_ceiling > 0
                    ? (overall.ytd_spent / overall.spending_ceiling) * 100
                    : 0
                }
                benchmark={benchmark}
                tone={overall.status}
                forecast={forecastPos != null ? { pct: forecastPos, over: projectedOver } : null}
              />
              {/* When the two labels would sit within 12 points of each other,
                  stack them on two rows so they never render on top of each
                  other; otherwise share a single row. */}
              {(() => {
                const stacked =
                  forecastPos != null && Math.abs(clampPos(benchmark) - clampPos(forecastPos)) < 12;
                return (
                  <>
                    <div className="relative mt-1 h-3.5">
                      <span
                        className="absolute -translate-x-1/2 text-[11px] text-fg-muted"
                        style={{ left: `${clampPos(benchmark)}%` }}
                      >
                        today
                      </span>
                      {forecastPos != null && !stacked && (
                        <span
                          className="absolute -translate-x-1/2 text-[11px] text-fg-muted"
                          style={{ left: `${clampPos(forecastPos)}%` }}
                        >
                          projected
                        </span>
                      )}
                    </div>
                    {forecastPos != null && stacked && (
                      <div className="relative h-3.5">
                        <span
                          className="absolute -translate-x-1/2 text-[11px] text-fg-muted"
                          style={{ left: `${clampPos(forecastPos)}%` }}
                        >
                          projected
                        </span>
                      </div>
                    )}
                  </>
                );
              })()}
            </div>
          </div>

          {/* Right — projected month end + the off-pace chips */}
          <div className="md:pl-6">
            {overall.projected_month_total != null && (
              <>
                <p className="text-[11.5px] text-fg-muted">Projected month end</p>
                <p
                  className={`t-h2 tabular-nums ${
                    projectedOver ? "text-status-danger-calm-text" : "text-fg"
                  }`}
                >
                  {formatForecastCurrency(overall.projected_month_total)}
                </p>
                <p className="text-[12.5px] text-fg-muted">based on typical spending</p>
              </>
            )}
            {offPace.length > 0 && (
              <div className="mt-3 flex flex-wrap gap-1.5">
                {offPace.map((c) => (
                  <span
                    key={c.category}
                    className="inline-flex items-center rounded-full bg-status-danger-muted px-2.5 py-0.5 text-[11.5px] font-medium text-status-danger-accent"
                  >
                    {c.category}
                    <span className="ml-1 tabular-nums">{formatCurrency(c.variance)}</span>
                  </span>
                ))}
              </div>
            )}
          </div>
        </div>
      </CardContent>
    </Card>
  );
}
