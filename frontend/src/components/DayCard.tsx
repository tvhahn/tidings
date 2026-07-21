import { Loader2, RefreshCw, Sparkles } from "lucide-react";
import { memo, useCallback } from "react";
import Markdown from "react-markdown";
import remarkGfm from "remark-gfm";
import { JournalTransactionRow } from "@/components/JournalTransactionRow";
import { Card, CardContent } from "@/components/ui/card";
import { Skeleton } from "@/components/ui/skeleton";
import { Tooltip, TooltipContent, TooltipTrigger } from "@/components/ui/tooltip";
import { formatCurrency } from "@/lib/format";
import { titleCaseAllCapsRuns } from "@/lib/summaryText";
import { cn } from "@/lib/utils";
import type { JournalDay } from "@/types/api";

interface Props {
  day: JournalDay;
  budgetCeiling: number | null;
  summary?: string | null | undefined;
  summaryLoading?: boolean | undefined;
  regenerating?: boolean | undefined;
  /** Called with the day's date. Accepting the date here lets the parent pass a
   *  single stable callback — critical for memoization since a per-day closure
   *  would otherwise reset on every parent render. */
  onRegenerateSummary?: ((date: string) => void) | undefined;
  isToday?: boolean | undefined;
  daysInMonth?: number | undefined;
  /** Whether this is the first (top) day of the month listing — used to hint
   *  the first transaction that row actions are editable (see JournalTransactionRow). */
  isFirstDay?: boolean | undefined;
}

// 1-3 sentence summaries shouldn't produce headers or lists, but coerce them
// to inline text as a safety net so a stray `## header` or `- bullet` from the
// model never blows up the card layout.
const INLINE_MARKDOWN_COMPONENTS = {
  h1: ({ children }: { children?: React.ReactNode }) => (
    <span className="font-medium">{children}</span>
  ),
  h2: ({ children }: { children?: React.ReactNode }) => (
    <span className="font-medium">{children}</span>
  ),
  h3: ({ children }: { children?: React.ReactNode }) => (
    <span className="font-medium">{children}</span>
  ),
  h4: ({ children }: { children?: React.ReactNode }) => (
    <span className="font-medium">{children}</span>
  ),
  h5: ({ children }: { children?: React.ReactNode }) => (
    <span className="font-medium">{children}</span>
  ),
  h6: ({ children }: { children?: React.ReactNode }) => (
    <span className="font-medium">{children}</span>
  ),
  ul: ({ children }: { children?: React.ReactNode }) => <span>{children}</span>,
  ol: ({ children }: { children?: React.ReactNode }) => <span>{children}</span>,
  li: ({ children }: { children?: React.ReactNode }) => <span>{children} </span>,
};

type PaceTone = "success" | "warning" | "danger";

// Severity signal for the day's pace dot — green under 80% of expected daily
// budget, warning 80–100%, danger over. Thresholds match how people actually
// read a budget indicator, not the cumulative-MTD framing.
function paceTone(pct: number | null): PaceTone {
  if (pct == null) return "success";
  if (pct > 100) return "danger";
  if (pct >= 80) return "warning";
  return "success";
}

const PACE_BG: Record<PaceTone, string> = {
  success: "bg-status-success",
  warning: "bg-status-warning",
  // Calm over-budget red — matches PaceBar's `over` tone; the saturated
  // --status-danger reads as an alarm wall when a day crosses 100%.
  danger: "bg-status-danger-calm",
};

function formatDayHeader(dateStr: string): string {
  const [y, m, d] = dateStr.split("-").map(Number);
  if (y === undefined || m === undefined || d === undefined) return dateStr;
  const date = new Date(y, m - 1, d);
  return date.toLocaleDateString("en-US", {
    weekday: "short",
    month: "long",
    day: "numeric",
  });
}

function DayCardImpl({
  day,
  budgetCeiling,
  summary,
  summaryLoading,
  regenerating,
  onRegenerateSummary,
  isToday,
  daysInMonth,
  isFirstDay,
}: Props) {
  const handleRegenerate = useCallback(() => {
    onRegenerateSummary?.(day.date);
  }, [onRegenerateSummary, day.date]);
  // Per-day pace: day spend vs. expected daily budget (not cumulative MTD).
  // Makes every day's dot vary meaningfully — no more "wall of identical red"
  // in over-budget months.
  const expectedDaily = budgetCeiling && daysInMonth ? budgetCeiling / daysInMonth : null;
  const pct = expectedDaily ? (day.day_total / expectedDaily) * 100 : null;
  const hasSummary = !!summary && !summaryLoading;

  const tone = paceTone(pct);

  // Today gets a brand tint; every other day is a plain calm card — the pace
  // dot now carries severity, so no per-day tint.
  const cardTint = isToday ? "border-brand/40 bg-brand/[0.03]" : "border-border/50";

  return (
    <Card className={cn("group/card cv-auto", cardTint)}>
      <CardContent className="p-4 sm:p-5">
        {/* Day header */}
        <div className="flex items-baseline justify-between gap-2 w-full">
          <div className="flex items-baseline gap-1.5 min-w-0 flex-1">
            <h2 className="text-base font-medium truncate">{formatDayHeader(day.date)}</h2>
            {isToday && (
              <span className="inline-flex items-center rounded-full bg-brand/10 text-brand-text px-2 py-0.5 text-meta font-medium">
                Today
              </span>
            )}
            {/* Quiet ghost affordance for days without a summary. Lives in the
                header row so it reserves no vertical space at rest; revealed on
                card hover (always on coarse pointers / keyboard focus). */}
            {!summary && !summaryLoading && onRegenerateSummary && (
              <button
                onClick={handleRegenerate}
                className="inline-flex items-center gap-1 rounded-md px-1.5 py-0.5 text-xs text-fg-muted opacity-0 transition-opacity hover:text-fg-secondary group-hover/card:opacity-100 focus-visible:opacity-100 focus-visible:outline-none focus-visible:ring-1 focus-visible:ring-border-strong pointer-coarse:opacity-100"
              >
                <Sparkles className="h-3 w-3" />
                <span>Summarize</span>
              </button>
            )}
          </div>
          <div className="flex items-baseline gap-2 shrink-0">
            <span className="text-base font-semibold tabular-nums">
              {formatCurrency(day.day_total)}
            </span>
            <span className="text-xs text-fg-secondary whitespace-nowrap">
              {/* Keep the unit at every width — a bare "1" next to the amount
                  reads as a stray number; the day header truncates instead. */}
              {day.count} txn{day.count !== 1 ? "s" : ""}
            </span>
            {pct != null && (
              <Tooltip>
                <TooltipTrigger asChild>
                  <span
                    tabIndex={-1}
                    className={cn(
                      "inline-block h-2 w-2 rounded-full shrink-0 self-center",
                      PACE_BG[tone]
                    )}
                    aria-hidden
                  />
                </TooltipTrigger>
                <TooltipContent>{Math.round(pct)}% of a typical day's budget</TooltipContent>
              </Tooltip>
            )}
          </div>
        </div>

        {/* AI summary lede — promoted from a collapsed footnote to a visible
            italic lede directly under the day header. */}
        {summaryLoading && (
          <div className="mt-1.5 space-y-1.5">
            <Skeleton className="h-3 w-full" />
            <Skeleton className="h-3 w-4/5" />
          </div>
        )}

        {hasSummary && (
          <div className="group/lede mt-1.5 flex items-start gap-1.5">
            <div
              className={cn(
                "flex-1 prose prose-sm dark:prose-invert max-w-none text-sm italic text-fg-secondary leading-relaxed [&>p]:m-0 [&_strong]:font-medium transition-opacity",
                regenerating && "opacity-50"
              )}
            >
              <Markdown remarkPlugins={[remarkGfm]} components={INLINE_MARKDOWN_COMPONENTS}>
                {titleCaseAllCapsRuns(summary as string)}
              </Markdown>
            </div>
            {onRegenerateSummary && (
              <button
                onClick={handleRegenerate}
                disabled={regenerating}
                aria-busy={regenerating}
                className="shrink-0 mt-0.5 p-1 rounded-md text-muted-foreground hover:text-foreground hover:bg-muted opacity-0 group-hover/lede:opacity-100 focus-visible:opacity-100 pointer-coarse:opacity-100 transition-opacity disabled:cursor-not-allowed focus-visible:outline-none focus-visible:ring-1 focus-visible:ring-border-strong"
                aria-label={regenerating ? "Regenerating summary" : "Regenerate summary"}
                title={regenerating ? "Regenerating…" : "Regenerate summary"}
              >
                {regenerating ? (
                  <Loader2 className="h-3 w-3 animate-spin" />
                ) : (
                  <RefreshCw className="h-3 w-3" />
                )}
              </button>
            )}
          </div>
        )}

        {/* Transaction list */}
        <div className="mt-3 divide-y divide-border/50">
          {day.transactions.map((txn, idx) => (
            <JournalTransactionRow
              key={`${txn.forwarded_to}|${txn.date_file_name}`}
              transaction={txn}
              anchorsDemoTour={isFirstDay && idx === 0}
            />
          ))}
        </div>
      </CardContent>
    </Card>
  );
}

export const DayCard = memo(DayCardImpl);
