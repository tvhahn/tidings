import {
  HeadlineStandard,
  type HeadlineBaseProps,
  type HeadlineVariantProps,
  SpentDisplay,
  SummarizeAffordance,
} from "@/components/headline/HeadlineStandard";
import { HeadlineTimeline } from "@/components/headline/HeadlineTimeline";
import { formatCurrency } from "@/lib/format";
import { headlineVerdict } from "@/lib/headlineVerdict";
import {
  BAR_TICK,
  BAR_TRACK,
  HEADLINE_WRAPPER,
  type MonthPace,
  TONE_BAR,
} from "@/lib/projectionBreakdown";
import { cn } from "@/lib/utils";
import { usePreferences } from "@/stores/preferences";
import type { JournalDay } from "@/types/api";

export interface JournalHeadlineProps extends HeadlineBaseProps {
  /** Current-month commitment-aware pace (with `breakdown`), or null. */
  pace: MonthPace | null;
  /** Recorded days for the current month — the timeline variant's ink dots. */
  days: JournalDay[];
  /** Opens the shared breakdown sheet (rendered at page level). */
  onOpenBreakdown: () => void;
  /** Scrolls the feed to a recorded day's card (timeline dot click). */
  onScrollToDay: (date: string) => void;
}

/** The shipped strip verbatim — shown for past months, budget-less months, and
 *  whenever the commitment-aware projection is unavailable (fail-open). DOM and
 *  classes match the pre-projection component exactly. */
function LegacyStrip({
  monthLabel,
  prevMonthLabel,
  spent,
  budget,
  monthDelta,
  prevMonthSpent,
  spentPct,
  pacePct,
  daysRemaining,
  asOfDay,
  onSummarizeMonth,
  summarizing,
}: HeadlineBaseProps) {
  const remaining = budget != null ? budget - spent : null;
  const dailyLeft = remaining != null && daysRemaining > 0 ? remaining / daysRemaining : null;
  const deltaUnder = monthDelta != null && monthDelta < 0;
  const verdict =
    spentPct != null ? headlineVerdict({ spentPct, pacePct, projectedPct: null }) : null;

  return (
    <div className={HEADLINE_WRAPPER}>
      <SummarizeAffordance onSummarizeMonth={onSummarizeMonth} summarizing={summarizing} />

      <div>
        <SpentDisplay spent={spent} asOfDay={asOfDay} monthLabel={monthLabel} />
        {budget != null && (
          <div className="mt-2 text-small text-fg-secondary">
            of <span className="font-medium text-fg-2">{formatCurrency(budget)}</span> monthly
            budget
            {dailyLeft != null && dailyLeft > 0 && daysRemaining > 0 && (
              <>
                {" · "}
                <span className="font-medium text-status-success">
                  {formatCurrency(dailyLeft)}/day
                </span>{" "}
                left for {daysRemaining} days
              </>
            )}
          </div>
        )}
      </div>

      {monthDelta != null && (
        <div className="text-left sm:text-right">
          <div className="mb-2 text-meta font-medium text-fg-muted">vs. {prevMonthLabel}</div>
          <div
            className={cn(
              "text-xl font-medium tabular-nums leading-none",
              deltaUnder ? "text-status-success" : "text-fg-2"
            )}
          >
            {deltaUnder ? "−" : "+"}
            {formatCurrency(Math.abs(monthDelta))}
          </div>
          {prevMonthSpent != null && (
            <div className="mt-1 text-small text-fg-secondary">
              {asOfDay != null
                ? `spent ${formatCurrency(prevMonthSpent)} by this point in ${prevMonthLabel}`
                : `spent ${formatCurrency(prevMonthSpent)} in ${prevMonthLabel}`}
            </div>
          )}
        </div>
      )}

      {spentPct != null && budget != null && verdict != null && (
        <div className="sm:col-span-2 mt-2 sm:mt-3">
          <div className={cn("relative h-2 overflow-hidden rounded-full", BAR_TRACK)}>
            <div
              className={cn("h-full rounded-full", TONE_BAR[verdict.tone])}
              style={{ width: `${Math.min(100, spentPct)}%` }}
            />
            <div
              className={cn("absolute -top-[3px] h-[14px] w-[1.5px] rounded-full", BAR_TICK)}
              style={{ left: `${Math.min(100, pacePct)}%` }}
              title="Today's pace"
            />
          </div>
          <div className="mt-2 text-meta tabular-nums text-fg-muted">
            <span className="font-medium text-fg-2">{verdict.label}</span>
            {" · "}
            {spentPct.toFixed(0)}% of budget used, {pacePct.toFixed(0)}% of month elapsed
          </div>
        </div>
      )}
    </div>
  );
}

/** Editorial Tidings headline strip — the thin variant container (L8). Reads the
 *  per-device `headlineVariant` preference and dispatches to Standard (V7) or
 *  Timeline (V6) once a commitment-aware projection is available; otherwise it
 *  degrades to the shipped strip, unchanged, for every variant. */
export function JournalHeadline(props: JournalHeadlineProps) {
  const variant = usePreferences((s) => s.headlineVariant);
  const { pace, budget, spentPct } = props;
  const breakdown = pace?.breakdown ?? null;

  // The projection treatment needs a breakdown, a budget to scale the bar, and
  // a spent share. Any gap → the shipped strip (fail-open, matches past months).
  if (pace == null || breakdown == null || budget == null || spentPct == null) {
    return <LegacyStrip {...props} />;
  }

  const projectedPct =
    pace.projected_month_total != null ? (pace.projected_month_total / budget) * 100 : spentPct;
  const verdict = headlineVerdict({ spentPct, pacePct: props.pacePct, projectedPct });

  const variantProps: HeadlineVariantProps = {
    ...props,
    budget,
    spentPct,
    pace,
    breakdown,
    verdict,
    projectedPct,
  };

  return variant === "timeline" ? (
    <HeadlineTimeline {...variantProps} />
  ) : (
    <HeadlineStandard {...variantProps} />
  );
}
