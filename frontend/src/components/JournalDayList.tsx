import { memo } from "react";
import { DayCard } from "@/components/DayCard";
import type { JournalDay, JournalSummariesResponse } from "@/types/api";

interface JournalDayListProps {
  days: JournalDay[];
  budgetCeiling: number | null;
  summaries: JournalSummariesResponse | undefined;
  aiEnabled: boolean;
  isGenerating: boolean;
  regenerating: Set<string>;
  /** Stable callback (keyed to the displayed month); only wired to cards when
   *  aiEnabled. Accepting the date keeps it a single reference across days. */
  onRegenerate: (date: string) => void;
  todayLocal: string;
  daysInMonth: number;
  demo: boolean;
}

/**
 * The heavy day-card list, extracted and memoized so JournalPage's *urgent*
 * render — the month-header flip on a Prev/Next click — can skip re-rendering
 * it. On a month change `month` updates urgently (header flips instantly) while
 * every prop here stays pinned to `deferredMonth`, so this subtree's props are
 * referentially stable in that urgent pass and `memo` bails out. The heavy
 * re-render happens afterward at low priority, when `deferredMonth` catches up.
 * See JournalPage's useDeferredValue wiring.
 */
export const JournalDayList = memo(function JournalDayList({
  days,
  budgetCeiling,
  summaries,
  aiEnabled,
  isGenerating,
  regenerating,
  onRegenerate,
  todayLocal,
  daysInMonth,
  demo,
}: JournalDayListProps) {
  return (
    <div className="space-y-4 month-transition">
      {days.map((day, idx) => {
        // In demo mode aiEnabled is false (no generation possible), but we
        // still surface fixture-baked summaries so visitors see the feature.
        const daySummary = summaries?.summaries[day.date] ?? null;
        const isRegenerating = regenerating.has(day.date);
        const dayIsGenerating = aiEnabled && (isGenerating || isRegenerating) && !daySummary;
        return (
          <DayCard
            key={day.date}
            day={day}
            budgetCeiling={budgetCeiling}
            summary={daySummary}
            summaryLoading={dayIsGenerating}
            regenerating={isRegenerating}
            onRegenerateSummary={aiEnabled ? onRegenerate : undefined}
            isToday={day.date === todayLocal}
            daysInMonth={daysInMonth}
            isFirstDay={demo && idx === 0}
          />
        );
      })}
      {days.length === 0 && (
        <div className="rounded-[var(--radius-tidings-md)] border border-border/50 bg-card px-5 py-8">
          {/* Sentence-case heading, not an uppercase eyebrow — data eyebrows are
              reserved for labels over display amounts (docs/brand/voice.md). */}
          <p className="text-sm font-medium text-fg">No transactions</p>
          <p className="mt-1.5 text-sm text-fg-secondary">
            Nothing recorded for this month yet. Forwarded transaction emails appear here as they
            arrive.
          </p>
        </div>
      )}
    </div>
  );
});
