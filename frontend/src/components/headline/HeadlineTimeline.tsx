import {
  type HeadlineVariantProps,
  OpenBreakdownButton,
  SpentDisplay,
  SummarizeAffordance,
} from "@/components/headline/HeadlineStandard";
import { Tooltip, TooltipContent, TooltipProvider, TooltipTrigger } from "@/components/ui/tooltip";
import { formatCurrency } from "@/lib/format";
import {
  approxAmount,
  BAR_TICK,
  clampPct,
  type ExpectedCharge,
  HEADLINE_WRAPPER,
  vsPrevDelta,
} from "@/lib/projectionBreakdown";
import { cn } from "@/lib/utils";

const INK_DOT = "bg-[color-mix(in_oklch,var(--fg)_78%,transparent)]";
const PENCIL_BORDER = "border-[color-mix(in_oklch,var(--fg-muted)_80%,transparent)]";

/** V6 — the month-as-a-line treatment. The bare pace bar becomes a timeline:
 *  ink dots for each recorded day (hover = day total, click = scroll to its
 *  card), dashed pencil circles for charges still committed (upcoming ahead of
 *  today, assumed behind it), and a hollow diamond at month end. Pencils, the
 *  diamond, and the caption phrase all open the shared breakdown sheet. */
export function HeadlineTimeline({
  monthLabel,
  prevMonthLabel,
  spent,
  budget,
  monthDelta,
  prevMonthSpent,
  pacePct,
  asOfDay,
  pace,
  breakdown,
  verdict,
  days,
  onSummarizeMonth,
  summarizing,
  onOpenBreakdown,
  onScrollToDay,
}: HeadlineVariantProps) {
  const daysInMonth = pace.days_in_month;
  const shortMonth = monthLabel.split(" ")[0]?.slice(0, 3) ?? "";
  const monthEndLabel = `${shortMonth} ${daysInMonth}`;

  // Like-for-like comparison — folds statement-assumed spend into the current
  // side so a statement-lag month isn't flattered against a fully-imported one.
  const delta =
    monthDelta != null && prevMonthSpent != null
      ? vsPrevDelta({ monthDelta, prevMonthSpent, breakdown })
      : null;
  const deltaUnder = delta != null && delta.delta < 0;

  const projectedAmount = approxAmount(
    breakdown.observed_mtd +
      breakdown.assumed_committed +
      breakdown.upcoming_committed +
      breakdown.everyday_remainder
  );

  // Ink dots — recorded days scaled 4–9px by day total.
  const maxTotal = days.reduce((m, d) => Math.max(m, d.day_total), 0);
  const dotDiameter = (total: number): number => {
    if (maxTotal <= 0) return 4;
    return 4 + (Math.max(0, total) / maxTotal) * 5;
  };
  const dayOfMonth = (date: string): number => Number(date.slice(8, 10));
  const dayLeft = (day: number): number => clampPct((day / daysInMonth) * 100);

  // Penciled charges — committed but not arrived. Upcoming sit ahead of today,
  // assumed (statement-observed) sit behind it. The circles stay wordless;
  // merchant and amount live in each pencil's tooltip (and the sheet).
  const penciled = breakdown.charges.filter(
    (c) => c.status === "upcoming" || c.status === "assumed"
  );

  const pencilTitle = (c: ExpectedCharge): string =>
    c.status === "assumed"
      ? `${c.display_name} ${approxAmount(c.amount_estimate)} · awaiting statement`
      : `${c.display_name} ${approxAmount(c.amount_estimate)}`;

  return (
    <TooltipProvider delayDuration={150}>
      <div className={HEADLINE_WRAPPER}>
        <SummarizeAffordance onSummarizeMonth={onSummarizeMonth} summarizing={summarizing} />

        <div>
          <SpentDisplay spent={spent} asOfDay={asOfDay} monthLabel={monthLabel} />
          <div className="mt-2 text-small text-fg-secondary">
            of <span className="font-medium text-fg-2">{formatCurrency(budget)}</span>
          </div>
        </div>

        {delta != null && (
          <div className="text-left sm:text-right">
            <div className="mb-2 text-meta font-medium text-fg-muted">vs. {prevMonthLabel}</div>
            <div
              className={cn(
                "text-xl font-medium leading-none tabular-nums",
                deltaUnder ? "text-status-success" : "text-fg-2"
              )}
            >
              {deltaUnder ? "−" : "+"}
              {formatCurrency(Math.abs(delta.delta))}
            </div>
            {prevMonthSpent != null && (
              <div className="mt-1 text-small text-fg-secondary">
                {delta.likeForLike && (
                  <div>like for like · statement charges counted in both months</div>
                )}
                spent {formatCurrency(prevMonthSpent)} by this point in {prevMonthLabel}
              </div>
            )}
          </div>
        )}

        {/* Month timeline */}
        <div className="sm:col-span-2 mt-3">
          <div className="relative h-[56px]">
            {/* Date labels */}
            <div className="absolute left-0 top-2 text-meta tabular-nums text-fg-muted">
              {shortMonth} 1
            </div>
            <div
              className="absolute top-2 -translate-x-1/2 text-meta tabular-nums text-fg-muted"
              style={{ left: `${clampPct(pacePct)}%` }}
            >
              today
            </div>
            <div className="absolute right-0 top-2 text-right text-meta tabular-nums text-fg-muted">
              {monthEndLabel}
              {/* On phones the suffix collides with the today marker; the
                  caption below carries the same figure. */}
              <span className="hidden sm:inline"> · expected {projectedAmount}</span>
            </div>

            {/* Axis */}
            <div className="absolute inset-x-0 top-10 border-t border-[color-mix(in_oklch,var(--fg)_18%,transparent)]" />

            {/* Ink dots — recorded days */}
            {days.map((d) => {
              const size = dotDiameter(d.day_total);
              const dnum = dayOfMonth(d.date);
              return (
                <Tooltip key={d.date}>
                  <TooltipTrigger asChild>
                    <button
                      type="button"
                      onClick={() => onScrollToDay(d.date)}
                      aria-label={`${shortMonth} ${dnum} — jump to this day`}
                      className={cn(
                        "absolute top-10 -translate-x-1/2 -translate-y-1/2 rounded-full focus-visible:outline-none focus-visible:ring-1 focus-visible:ring-border-strong",
                        INK_DOT
                      )}
                      style={{ left: `${dayLeft(dnum)}%`, width: `${size}px`, height: `${size}px` }}
                    />
                  </TooltipTrigger>
                  <TooltipContent>{formatCurrency(d.day_total)}</TooltipContent>
                </Tooltip>
              );
            })}

            {/* Today marker */}
            <div
              className={cn(
                "absolute top-[26px] h-7 w-[1.5px] -translate-x-1/2 rounded-full",
                BAR_TICK
              )}
              style={{ left: `${clampPct(pacePct)}%` }}
              title="Today"
            />

            {/* Penciled charges — dashed circles, assumed drawn larger */}
            {penciled.map((c) => {
              const big = c.status === "assumed";
              const px = big ? 14 : 11;
              return (
                <Tooltip key={`${c.merchant}:${c.status}`}>
                  <TooltipTrigger asChild>
                    <button
                      type="button"
                      onClick={onOpenBreakdown}
                      aria-label={`${pencilTitle(c)} — open the breakdown`}
                      className={cn(
                        "absolute top-10 -translate-x-1/2 -translate-y-1/2 rounded-full border-[1.5px] border-dashed bg-card focus-visible:outline-none focus-visible:ring-1 focus-visible:ring-border-strong",
                        PENCIL_BORDER
                      )}
                      style={{
                        left: `${dayLeft(c.expected_day)}%`,
                        width: `${px}px`,
                        height: `${px}px`,
                      }}
                    />
                  </TooltipTrigger>
                  <TooltipContent>{pencilTitle(c)}</TooltipContent>
                </Tooltip>
              );
            })}

            {/* Month-end forecast diamond */}
            <Tooltip>
              <TooltipTrigger asChild>
                <button
                  type="button"
                  onClick={onOpenBreakdown}
                  aria-label={`Projected ${projectedAmount} by ${monthEndLabel} — open the breakdown`}
                  className="absolute top-10 left-full h-[7px] w-[7px] -translate-x-1/2 -translate-y-1/2 rotate-45 rounded-[1px] border-[1.5px] border-fg-secondary bg-card focus-visible:outline-none focus-visible:ring-1 focus-visible:ring-border-strong"
                />
              </TooltipTrigger>
              <TooltipContent>
                projected {projectedAmount} by {monthEndLabel}
              </TooltipContent>
            </Tooltip>
          </div>

          <div className="mt-2 text-meta tabular-nums text-fg-muted">
            <span className="font-medium text-fg-2">{verdict.label}</span>
            {" · heading for about "}
            <span className="font-medium text-fg-2">{projectedAmount}</span> of{" "}
            {formatCurrency(budget)} by {monthEndLabel} ·{" "}
            <OpenBreakdownButton
              onOpenBreakdown={onOpenBreakdown}
              label="Open the projection breakdown"
              className="text-fg-muted"
            >
              how it adds up
            </OpenBreakdownButton>
          </div>
        </div>
      </div>
    </TooltipProvider>
  );
}
