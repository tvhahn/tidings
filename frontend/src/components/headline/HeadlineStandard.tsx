import { Loader2, Sparkles } from "lucide-react";
import type { CSSProperties, ReactNode } from "react";
import { closedMonthSentence, paceBarLabel, paceBarWidths, TILE_CARD } from "@/lib/firstScreen";
import { formatCurrencyRounded } from "@/lib/format";
import type { HeadlineVerdict } from "@/lib/headlineVerdict";
import type { MonthPace, MonthPaceBreakdown } from "@/lib/projectionBreakdown";
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

export interface SpentHeroProps extends HeadlineBaseProps {
  /** Month-end projection (commitment-aware), or null when unavailable. */
  projected: number | null;
  /** Opens the projection breakdown sheet; null when there is no breakdown. */
  onOpenBreakdown: (() => void) | null;
}

/** N8.2 — the spent hero, shared by the Journal's phone column and desktop
 *  rail. The figure, one sentence, and a plain pace bar: spent so far over a
 *  pale run to the projection, with the ceiling named beneath. No ticks, no
 *  hatching, no labels on the bar, no month-over-month comparison. */
export function HeadlineStandard({
  monthLabel,
  spent,
  budget,
  asOfDay,
  pacePct,
  projected,
  onOpenBreakdown,
  onSummarizeMonth,
  summarizing,
}: SpentHeroProps) {
  const monthClosed = asOfDay == null && pacePct >= 100;
  const heading = projected != null && !monthClosed;
  const projectedRounded = projected != null ? formatCurrencyRounded(projected) : "";
  const closedSentence = monthClosed ? closedMonthSentence({ spent, budget }) : null;
  const bar =
    budget != null && budget > 0
      ? paceBarWidths({ spent, budget, projected: heading ? projected : null })
      : null;

  return (
    <div className={cn(TILE_CARD, "group/headline col-span-2 px-5 pb-4 pt-5")}>
      <SummarizeAffordance onSummarizeMonth={onSummarizeMonth} summarizing={summarizing} />
      <SpentDisplay spent={spent} asOfDay={asOfDay} monthLabel={monthLabel} />

      {heading && (
        <p className="t-prose mt-2.5 text-balance text-fg-secondary">
          Heading for about{" "}
          {onOpenBreakdown ? (
            <OpenBreakdownButton
              onOpenBreakdown={onOpenBreakdown}
              label={`Heading for about ${projectedRounded} by month end — open the breakdown`}
            >
              {projectedRounded}
            </OpenBreakdownButton>
          ) : (
            projectedRounded
          )}{" "}
          by month end.
        </p>
      )}
      {closedSentence != null && (
        <p className="t-prose mt-2.5 text-balance text-fg-secondary">{closedSentence}</p>
      )}

      {bar != null && budget != null && (
        <>
          <div
            role="img"
            aria-label={paceBarLabel({ spent, budget, projected: heading ? projected : null })}
            className="relative mt-[18px] h-1.5 overflow-hidden rounded-full bg-pace-track"
          >
            {bar.projPct != null && (
              <span
                className="absolute inset-y-0 left-0 rounded-full bg-pace-proj"
                style={{ width: `${bar.projPct}%` }}
              />
            )}
            <span
              className="absolute inset-y-0 left-0 rounded-full bg-pace-fill"
              style={{ width: `${bar.fillPct}%` }}
            />
          </div>
          <div className="mt-2 text-right text-xs text-fg-muted tabular-nums">
            {formatCurrencyRounded(budget)} ceiling
          </div>
        </>
      )}
    </div>
  );
}
