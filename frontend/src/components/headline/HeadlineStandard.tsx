import { Loader2, Sparkles } from "lucide-react";
import { useId } from "react";
import type { CSSProperties, ReactNode } from "react";
import { Tooltip, TooltipContent, TooltipProvider, TooltipTrigger } from "@/components/ui/tooltip";
import { formatCurrency, formatCurrencyRounded } from "@/lib/format";
import type { HeadlineVerdict, VerdictTone } from "@/lib/headlineVerdict";
import {
  approxAmount,
  BAR_TICK,
  BAR_TRACK,
  clampPct,
  HEADLINE_WRAPPER,
  type MonthPace,
  type MonthPaceBreakdown,
  TONE_BAR,
  vsPrevDelta,
} from "@/lib/projectionBreakdown";
import { cn } from "@/lib/utils";
import type { JournalDay } from "@/types/api";

/* ---------------------------------------------------------------------------
 * Shared headline strip primitives.
 *
 * The JSX primitives and prop types below are hosted here — in the default
 * variant — rather than in the JournalHeadline container, because the container
 * imports both variants; a variant importing runtime values back from the
 * container would form a module cycle (`import/no-cycle`). The Timeline variant
 * and the container both import from this file, which imports neither of them,
 * so the graph stays acyclic. Shared non-component constants live in
 * `lib/projectionBreakdown.ts` (react-refresh forbids mixing them here).
 * ------------------------------------------------------------------------- */

/** Verdict tone → the CSS custom property backing the committed hatch. */
const TONE_VAR: Record<VerdictTone, string> = {
  success: "--status-success",
  warning: "--status-warning",
  danger: "--status-danger-calm",
};

export interface HeadlineBaseProps {
  /** "April 2026" — already formatted. */
  monthLabel: string;
  /** "March" — for the vs-prev label. */
  prevMonthLabel: string;
  spent: number;
  budget: number | null;
  /** Spend − prev-month MTD spend; negative is good. Null when no comparable history. */
  monthDelta: number | null;
  prevMonthSpent: number | null;
  /** 0–100, spent-share of budget. Null when no budget. */
  spentPct: number | null;
  /** 0–100, today's elapsed-month position (where the tick goes). */
  pacePct: number;
  /** Days remaining in the month from today. */
  daysRemaining: number;
  /** Day-of-month for the current month (1–31). Null for historical/future months. */
  asOfDay: number | null;
  /** Present while the month still has days without AI summaries (or a run is
   *  in flight) — renders the quiet summarize-month affordance in the corner. */
  onSummarizeMonth?: (() => void) | null | undefined;
  /** True while a generation run is in flight — pins the affordance visible. */
  summarizing?: boolean | undefined;
}

/** Props passed to a projection variant. `breakdown`/`budget`/`spentPct` are
 *  narrowed non-null because the container only mounts a variant once the
 *  commitment-aware projection is available. */
export interface HeadlineVariantProps extends HeadlineBaseProps {
  budget: number;
  spentPct: number;
  pace: MonthPace;
  breakdown: MonthPaceBreakdown;
  verdict: HeadlineVerdict;
  /** 0–100+, projected month-end share of budget. */
  projectedPct: number;
  days: JournalDay[];
  onOpenBreakdown: () => void;
  onScrollToDay: (date: string) => void;
}

/** Month-scoped summarize affordance — identical across all treatments. */
export function SummarizeAffordance({
  onSummarizeMonth,
  summarizing,
}: Pick<HeadlineBaseProps, "onSummarizeMonth" | "summarizing">) {
  if (!onSummarizeMonth) return null;
  return (
    <button
      onClick={onSummarizeMonth}
      disabled={summarizing}
      aria-busy={summarizing}
      className={cn(
        "absolute right-3 top-3 inline-flex items-center gap-1 rounded-md px-1.5 py-0.5 text-xs text-fg-muted transition-opacity hover:text-fg-secondary focus-visible:opacity-100 focus-visible:outline-none focus-visible:ring-1 focus-visible:ring-border-strong pointer-coarse:opacity-100",
        summarizing ? "opacity-100 cursor-default" : "opacity-0 group-hover/headline:opacity-100"
      )}
    >
      {summarizing ? (
        <Loader2 className="h-3 w-3 animate-spin" />
      ) : (
        <Sparkles className="h-3 w-3" />
      )}
      <span>{summarizing ? "Summarizing…" : "Summarize month"}</span>
    </button>
  );
}

/** Eyebrow + big serif spent figure — the hero, unchanged across treatments. */
export function SpentDisplay({
  spent,
  asOfDay,
  monthLabel,
}: Pick<HeadlineBaseProps, "spent" | "asOfDay" | "monthLabel">) {
  const wholeAmount = Math.floor(spent);
  const cents = Math.abs(spent - Math.floor(spent))
    .toFixed(2)
    .slice(2);
  const shortMonth = monthLabel.split(" ")[0]?.slice(0, 3) ?? "";
  const eyebrow =
    asOfDay != null ? `Spent · as of ${shortMonth} ${asOfDay}` : `Spent · ${monthLabel}`;
  return (
    <>
      <div className="mb-2 text-meta font-medium text-fg-muted">{eyebrow}</div>
      <div className="t-display leading-none text-fg tabular-nums">
        ${wholeAmount.toLocaleString()}
        <span className="text-[0.65em] font-medium text-fg-muted">.{cents}</span>
      </div>
    </>
  );
}

/** Dotted-underline text button that opens the breakdown sheet. A real button,
 *  so Enter/Space work and jsx-a11y is satisfied. */
export function OpenBreakdownButton({
  onOpenBreakdown,
  label,
  children,
  className,
  style,
}: {
  onOpenBreakdown: () => void;
  label: string;
  children: ReactNode;
  className?: string;
  style?: CSSProperties;
}) {
  return (
    <button
      type="button"
      onClick={onOpenBreakdown}
      aria-label={label}
      style={style}
      className={cn(
        "rounded-sm underline decoration-dotted decoration-fg-muted/60 underline-offset-[3px] transition-colors hover:text-fg-2 focus-visible:outline-none focus-visible:ring-1 focus-visible:ring-border-strong",
        className
      )}
    >
      {children}
    </button>
  );
}

/** Diagonal-stripe hatch for the committed segment — an SVG pattern (the same
 *  device SpendingChart's projected segment uses), tinted to the verdict tone
 *  via currentColor on the wrapper. */
function CommittedHatch({ tone }: { tone: VerdictTone }) {
  const patternId = useId();
  const v = TONE_VAR[tone];
  return (
    <svg
      className="h-full w-full"
      style={{ color: `color-mix(in oklch, var(${v}) 55%, transparent)` }}
      aria-hidden="true"
    >
      <defs>
        <pattern
          id={patternId}
          width="6.5"
          height="6.5"
          patternUnits="userSpaceOnUse"
          patternTransform="rotate(-55)"
        >
          <rect width="3" height="6.5" fill="currentColor" />
        </pattern>
      </defs>
      <rect width="100%" height="100%" fill={`url(#${patternId})`} />
    </svg>
  );
}

/** V7 — the de-worded Standard strip (default). Hero spent figure unchanged;
 *  subline cut to fragments; the vs-prev explainer demoted to a tooltip; the
 *  pace bar gains a hatched committed segment and a hollow forecast diamond
 *  whose value labels it directly and opens the breakdown sheet. ~10 words. */
export function HeadlineStandard({
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
  breakdown,
  verdict,
  projectedPct,
  onSummarizeMonth,
  summarizing,
  onOpenBreakdown,
}: HeadlineVariantProps) {
  const spentLeft = clampPct(spentPct);
  const committedTotal = breakdown.upcoming_committed + breakdown.assumed_committed;
  const committedPct = (committedTotal / budget) * 100;
  const committedWidth = clampPct(Math.min(committedPct, 100 - spentLeft));
  const diamondLeft = clampPct(projectedPct);
  const projectedTotal =
    breakdown.observed_mtd +
    breakdown.assumed_committed +
    breakdown.upcoming_committed +
    breakdown.everyday_remainder;
  // Data surfaces (diamond aria-label + tooltip, hatch tooltip) keep the tilde;
  // the prose sentence hedges with the word "about" instead.
  const projectedAmount = approxAmount(projectedTotal);
  const projectedRounded = formatCurrencyRounded(projectedTotal);

  // Like-for-like comparison — folds statement-assumed spend into the current
  // side so a statement-lag month isn't flattered against a fully-imported one.
  const delta =
    monthDelta != null && prevMonthSpent != null
      ? vsPrevDelta({ monthDelta, prevMonthSpent, breakdown })
      : null;
  const deltaUnder = delta != null && delta.delta < 0;
  const explainer =
    prevMonthSpent != null && delta != null
      ? delta.likeForLike
        ? `like for like · statement charges counted in both months · spent ${formatCurrency(prevMonthSpent)} by this point in ${prevMonthLabel}`
        : `spent ${formatCurrency(prevMonthSpent)} by this point in ${prevMonthLabel}`
      : null;

  return (
    <TooltipProvider delayDuration={150}>
      <div className={HEADLINE_WRAPPER}>
        <SummarizeAffordance onSummarizeMonth={onSummarizeMonth} summarizing={summarizing} />

        <div>
          <SpentDisplay spent={spent} asOfDay={asOfDay} monthLabel={monthLabel} />
          <p className="t-prose mt-2.5 max-w-[44ch] text-fg-secondary">
            Heading for about{" "}
            <OpenBreakdownButton
              onOpenBreakdown={onOpenBreakdown}
              label={`Heading for about ${projectedRounded} by month end — open the breakdown`}
              className="font-medium text-fg-2"
            >
              {projectedRounded}
            </OpenBreakdownButton>{" "}
            of the {formatCurrencyRounded(budget)} ceiling.
          </p>
        </div>

        {delta != null && (
          <div className="text-left sm:text-right">
            <div className="mb-2 text-meta font-medium text-fg-muted">vs. {prevMonthLabel}</div>
            {explainer != null ? (
              <Tooltip>
                <TooltipTrigger asChild>
                  <button
                    type="button"
                    aria-label={explainer}
                    className={cn(
                      "cursor-help rounded-sm text-xl font-medium leading-none tabular-nums focus-visible:outline-none focus-visible:ring-1 focus-visible:ring-border-strong",
                      deltaUnder ? "text-status-success" : "text-fg-2"
                    )}
                  >
                    {deltaUnder ? "−" : "+"}
                    {formatCurrencyRounded(Math.abs(delta.delta))}
                  </button>
                </TooltipTrigger>
                <TooltipContent>{explainer}</TooltipContent>
              </Tooltip>
            ) : (
              <div
                className={cn(
                  "text-xl font-medium leading-none tabular-nums",
                  deltaUnder ? "text-status-success" : "text-fg-2"
                )}
              >
                {deltaUnder ? "−" : "+"}
                {formatCurrencyRounded(Math.abs(delta.delta))}
              </div>
            )}
          </div>
        )}

        {/* Pace bar with hatch + forecast diamond. Amounts live in tooltips —
            the strip itself stays wordless. */}
        <div className="sm:col-span-2 mt-5">
          <div className={cn("relative h-2 rounded-full", BAR_TRACK)}>
            <Tooltip>
              <TooltipTrigger asChild>
                <div
                  className={cn("absolute inset-y-0 left-0 rounded-full", TONE_BAR[verdict.tone])}
                  style={{ width: `${spentLeft}%` }}
                />
              </TooltipTrigger>
              <TooltipContent>
                spent {formatCurrency(spent)} · {Math.round(spentPct)}% of budget
              </TooltipContent>
            </Tooltip>
            {committedWidth > 0 && (
              <Tooltip>
                <TooltipTrigger asChild>
                  <div
                    className="absolute inset-y-0 overflow-hidden rounded-r-full"
                    style={{ left: `${spentLeft}%`, width: `${committedWidth}%` }}
                  >
                    <CommittedHatch tone={verdict.tone} />
                  </div>
                </TooltipTrigger>
                <TooltipContent>
                  {approxAmount(committedTotal)} committed, still to come
                </TooltipContent>
              </Tooltip>
            )}
            <Tooltip>
              <TooltipTrigger asChild>
                <div
                  className={cn("absolute -top-[3px] h-[14px] w-[1.5px] rounded-full", BAR_TICK)}
                  style={{ left: `${clampPct(pacePct)}%` }}
                />
              </TooltipTrigger>
              <TooltipContent>today</TooltipContent>
            </Tooltip>
            <Tooltip>
              <TooltipTrigger asChild>
                <button
                  type="button"
                  onClick={onOpenBreakdown}
                  aria-label={`Projected ${projectedAmount} by month end — open the breakdown`}
                  className="absolute top-1/2 h-[7px] w-[7px] -translate-x-1/2 -translate-y-1/2 rotate-45 rounded-[1px] border-[1.5px] border-fg-secondary bg-card focus-visible:outline-none focus-visible:ring-1 focus-visible:ring-border-strong"
                  style={{ left: `${diamondLeft}%` }}
                />
              </TooltipTrigger>
              <TooltipContent>projected {projectedAmount} by month end</TooltipContent>
            </Tooltip>
          </div>
          <div className="mt-2 flex justify-between gap-3 text-meta tabular-nums text-fg-muted">
            <span className="font-medium text-fg-2">{verdict.label}</span>
            <span>{daysRemaining} days left</span>
          </div>
        </div>
      </div>
    </TooltipProvider>
  );
}
