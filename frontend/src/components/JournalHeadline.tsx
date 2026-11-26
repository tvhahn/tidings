import {
  HeadlineStandard,
  type HeadlineBaseProps,
  type HeadlineVariantProps,
} from "@/components/headline/HeadlineStandard";
import { HeadlineTimeline } from "@/components/headline/HeadlineTimeline";
import { useTimelineHeadline } from "@/hooks/useTimelineHeadline";
import { projectedMonthTotal } from "@/lib/firstScreen";
import { headlineVerdict } from "@/lib/headlineVerdict";
import type { MonthPace } from "@/lib/projectionBreakdown";
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

/** The Journal's spent headline — a thin container. By default it renders the
 *  N8.2 spent hero (with the month-end projection when one is available, and
 *  without it for past and budget-less months). The per-device Timeline
 *  preference swaps in the timeline strip once a breakdown exists. */
export function JournalHeadline(props: JournalHeadlineProps) {
  const { pace, budget, spentPct, onOpenBreakdown } = props;
  const breakdown = pace?.breakdown ?? null;
  const timeline = useTimelineHeadline(props);

  if (timeline && pace != null && breakdown != null && budget != null && spentPct != null) {
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
    return <HeadlineTimeline {...variantProps} />;
  }

  return (
    <HeadlineStandard
      {...props}
      projected={breakdown != null ? projectedMonthTotal(breakdown) : null}
      onOpenBreakdown={breakdown != null ? onOpenBreakdown : null}
    />
  );
}
