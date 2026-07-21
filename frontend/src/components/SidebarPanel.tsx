import { useNavigate, useLocation } from "react-router-dom";
import { PaceBar } from "@/components/PaceBar";
import { Tooltip, TooltipContent, TooltipTrigger } from "@/components/ui/tooltip";
import { useJournal } from "@/hooks/useJournal";
import { useTrend } from "@/hooks/useTrend";
import { formatCurrency, formatMonthLabelLong } from "@/lib/format";

export function SidebarPanel({ month }: { month: string }) {
  const { data: journalData } = useJournal(month);
  // Pass month so the cache key matches SummaryPage's useTrend(6, month) and
  // avoids refetching the same 6-month window under a different key.
  const { data: trendData } = useTrend(6, month);

  const spent = journalData?.month_total ?? 0;
  const ceiling = journalData?.budget_ceiling ?? null;
  const pct = ceiling ? (spent / ceiling) * 100 : null;
  const [yStr, mStr] = month.split("-");
  const monthShort = new Date(Number(yStr), Number(mStr) - 1, 1).toLocaleDateString("en-US", {
    month: "short",
  });

  const navigate = useNavigate();
  const { pathname } = useLocation();

  const trendMonths = trendData?.months ?? [];
  const maxTrend =
    trendMonths.length > 0 ? Math.max(...trendMonths.map((m) => m.total_spending)) : 0;

  return (
    <div className="px-3 py-3 space-y-3 text-xs">
      {/* Current month spend */}
      <div className="rounded-lg border border-border/50 p-3">
        <div className="flex items-baseline justify-between">
          <span className="text-muted-foreground">{monthShort} spend</span>
          {pct != null && (
            <span className="text-muted-foreground tabular-nums">{Math.round(pct)}%</span>
          )}
        </div>
        <div className="mt-0.5 flex items-baseline justify-between gap-2">
          <span className="font-semibold tabular-nums text-sm">{formatCurrency(spent)}</span>
          {ceiling != null && (
            <span className="text-muted-foreground tabular-nums text-[11px]">
              / {formatCurrency(ceiling)}
            </span>
          )}
        </div>
        {pct != null && (
          <div className="mt-1.5">
            <PaceBar pct={pct} size="xs" />
          </div>
        )}
      </div>

      {/* 6-month sparkline */}
      {trendMonths.length > 0 && maxTrend > 0 && (
        <div className="rounded-lg border border-border/50 p-3">
          <div className="text-muted-foreground mb-1.5">Last 6 months</div>
          <div className="flex items-end gap-1 h-10">
            {trendMonths.map((m) => {
              const h = (m.total_spending / maxTrend) * 100;
              const isCurrent = m.year_month === month;
              return (
                <Tooltip key={m.year_month}>
                  <TooltipTrigger asChild>
                    <button
                      type="button"
                      aria-label={`${formatMonthLabelLong(m.year_month)} — ${formatCurrency(m.total_spending)}`}
                      className="flex-1 flex flex-col justify-end h-full cursor-pointer hover:opacity-80 rounded-sm bg-muted/40"
                      onClick={() => navigate(`${pathname}?month=${m.year_month}`)}
                    >
                      <div
                        className={`w-full rounded-sm transition-colors ${
                          isCurrent ? "bg-brand" : "bg-muted-foreground/70"
                        }`}
                        style={{ height: `${h}%` }}
                      />
                    </button>
                  </TooltipTrigger>
                  <TooltipContent side="right">
                    {formatMonthLabelLong(m.year_month)} — {formatCurrency(m.total_spending)}
                  </TooltipContent>
                </Tooltip>
              );
            })}
          </div>
          <div className="mt-1 flex justify-between text-[10px] text-muted-foreground">
            {trendMonths.map((m) => {
              const [ty, tm] = m.year_month.split("-");
              const d = new Date(Number(ty), Number(tm) - 1, 1);
              return (
                <button
                  type="button"
                  key={m.year_month}
                  aria-label={formatMonthLabelLong(m.year_month)}
                  className="flex-1 text-center cursor-pointer hover:opacity-80"
                  onClick={() => navigate(`${pathname}?month=${m.year_month}`)}
                >
                  {d.toLocaleDateString("en-US", { month: "narrow" })}
                </button>
              );
            })}
          </div>
        </div>
      )}
    </div>
  );
}
