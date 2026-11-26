import { useQuery } from "@tanstack/react-query";
import { useLocation, useNavigate } from "react-router-dom";
import { Tooltip, TooltipContent, TooltipTrigger } from "@/components/ui/tooltip";
import { useJournal } from "@/hooks/useJournal";
import { useTrend } from "@/hooks/useTrend";
import { monthBars, projectedMonthTotal } from "@/lib/firstScreen";
import {
  currentMonth,
  formatCurrency,
  formatCurrencyRounded,
  formatMonthLabelLong,
} from "@/lib/format";
import { queries } from "@/lib/queryConfigs";
import { cn } from "@/lib/utils";

/** The sidebar's foot: the last six months against the monthly ceiling. N8.2
 *  drops the month figure that used to sit above it — the Journal already
 *  leads with that number. The current month shows its projected total as a
 *  pale bar behind what is spent. */
export function SidebarPanel({ month }: { month: string }) {
  const { data: journalData } = useJournal(month);
  // Pass month so the cache key matches SummaryPage's useTrend(6, month) and
  // avoids refetching the same 6-month window under a different key.
  const { data: trendData } = useTrend(6, month);
  // Same factory and key the Journal uses, so this reads its cache.
  const isCurrentMonth = month === currentMonth();
  const { data: summaryData } = useQuery({ ...queries.summary(month), enabled: isCurrentMonth });
  const breakdown = isCurrentMonth ? (summaryData?.pace?.breakdown ?? null) : null;

  const navigate = useNavigate();
  const { pathname } = useLocation();

  const ceiling = journalData?.budget_ceiling ?? null;
  const model = monthBars({
    months: trendData?.months ?? [],
    currentMonth: month,
    ceiling,
    projected: breakdown ? projectedMonthTotal(breakdown) : null,
  });
  if (!model) return null;

  const months = trendData?.months ?? [];
  const goTo = (ym: string) => navigate(`${pathname}?month=${ym}`);

  return (
    <div className="px-[22px] pb-5 pt-3">
      <div className="flex justify-between text-xs text-fg-muted">
        <span>Last {months.length} months</span>
        {ceiling != null && <span className="tabular-nums">{formatCurrencyRounded(ceiling)}</span>}
      </div>
      <p className="sr-only">{model.ariaLabel}</p>
      <div className="relative mt-1 h-9 border-b border-border/80">
        {model.ceilingPct != null && (
          <div
            aria-hidden="true"
            className="absolute inset-x-0 border-t border-dashed border-fg-muted/55"
            style={{ bottom: `${model.ceilingPct}%` }}
          />
        )}
        <div className="absolute inset-0 flex gap-x-2.5">
          {model.bars.map((b, i) => {
            const m = months[i];
            if (!m) return null;
            return (
              <Tooltip key={b.month}>
                <TooltipTrigger asChild>
                  <button
                    type="button"
                    aria-label={`${formatMonthLabelLong(b.month)}: ${formatCurrency(m.total_spending)}`}
                    onClick={() => goTo(b.month)}
                    className="relative flex flex-1 flex-col justify-end rounded-t-[2px] focus-visible:outline-none focus-visible:ring-1 focus-visible:ring-ring"
                  >
                    {b.projPct != null && (
                      <span
                        className="absolute inset-x-0 bottom-0 rounded-t-[2px] bg-pace-proj"
                        style={{ height: `${b.projPct}%` }}
                      />
                    )}
                    <span
                      className={cn(
                        "relative w-full",
                        b.current
                          ? cn("bg-pace-fill", b.projPct == null && "rounded-t-[2px]")
                          : "rounded-t-[2px] bg-[color-mix(in_oklab,var(--muted-foreground)_26%,var(--background))] hover:bg-[color-mix(in_oklab,var(--muted-foreground)_40%,var(--background))] dark:bg-[color-mix(in_oklab,var(--muted-foreground)_30%,var(--background))]"
                      )}
                      style={{ height: `${b.spentPct}%` }}
                    />
                  </button>
                </TooltipTrigger>
                <TooltipContent side="right">
                  {formatMonthLabelLong(b.month)} — {formatCurrency(m.total_spending)}
                </TooltipContent>
              </Tooltip>
            );
          })}
        </div>
      </div>
      <div className="mt-1 flex gap-x-2.5 text-center text-xs text-fg-muted" aria-hidden="true">
        {model.bars.map((b) => {
          const [ty, tm] = b.month.split("-");
          const d = new Date(Number(ty), Number(tm) - 1, 1);
          return (
            <span key={b.month} className={cn("flex-1", b.current && "font-medium text-fg")}>
              {d.toLocaleDateString("en-US", { month: "narrow" })}
            </span>
          );
        })}
      </div>
    </div>
  );
}
