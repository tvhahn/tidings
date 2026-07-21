import { useQuery, useQueryClient } from "@tanstack/react-query";
import { useCallback, useEffect, useMemo, useRef, useState } from "react";
import { toast } from "sonner";
import { DemoSelfHostedCallout } from "@/components/DemoSelfHostedCallout";
import { JournalDayList } from "@/components/JournalDayList";
import { JournalHeadline } from "@/components/JournalHeadline";
import { MonthPicker } from "@/components/MonthPicker";
import { PageHeader } from "@/components/PageHeader";
import { ProjectionBreakdownSheet } from "@/components/ProjectionBreakdownSheet";
import { QueryErrorNotice } from "@/components/QueryErrorNotice";
import { Skeleton } from "@/components/ui/skeleton";
import { useConfig } from "@/hooks/useConfig";
import { useDemoMode } from "@/hooks/useDemoMode";
import { useJournal } from "@/hooks/useJournal";
import { useJournalSummariesOrchestrator } from "@/hooks/useJournalSummariesOrchestrator";
import { useMonthParam } from "@/hooks/useMonthParam";
import { prefetchJournalMonth, usePrefetchJournalMonth } from "@/hooks/usePrefetchJournalMonth";
import { generateJournalSummaries } from "@/lib/api";
import {
  currentMonth,
  formatMonthLabelLong,
  parseYearMonth,
  shiftMonth,
  todayLocalISO,
} from "@/lib/format";
import { queries, queryKeys } from "@/lib/queryConfigs";

function prevMonthLabel(month: string): string {
  const [y, m] = parseYearMonth(month);
  const d = new Date(y, m - 2, 1);
  return d.toLocaleDateString("en-US", { month: "long" });
}

function daysInMonthOf(month: string): number {
  const [y, m] = parseYearMonth(month);
  return new Date(y, m, 0).getDate();
}

export function JournalPage() {
  // The URL month drives all data-bound work. React Router v7 wraps navigations
  // (setSearchParams) in a startTransition, so `month` updates at *low* priority
  // — which is what we want for the heavy day-list re-render. The catch: a header
  // reading `month` would lag with it. So we keep a separate, *urgent*
  // `displayMonth` for the header + MonthPicker. setDisplayMonth is a plain
  // event-handler state update (urgent), so the header flips on the click's first
  // frame while the transition-wrapped data subtree catches up a beat later.
  // (useDeferredValue can't help here — `month` is already a transition value, so
  // there is no urgent copy for it to lag behind.)
  const [month, setMonth] = useMonthParam();
  const [displayMonth, setDisplayMonth] = useState(month);
  // Reconcile when the URL month changes from elsewhere (back/forward, the month
  // grid, a drill-down link) so the header never drifts from the actual route.
  useEffect(() => {
    setDisplayMonth(month);
  }, [month]);
  const changeMonth = useCallback(
    (next: string) => {
      setDisplayMonth(next); // urgent → header + picker flip immediately
      setMonth(next); // RR transition → data-bound subtree follows at low priority
    },
    [setMonth]
  );

  const { data, isLoading, isFetching, isError, error, refetch } = useJournal(month);
  const { data: prevData } = useJournal(shiftMonth(month, -1));
  const { data: config } = useConfig();
  const demo = useDemoMode();
  const queryClient = useQueryClient();

  // Commitment-aware pace/breakdown is only meaningful for the current month, so
  // the summary query is enabled only there (L7 — one source of truth, the
  // existing factory; no mirror field on /journal). `currentMonth()` respects
  // the demo-pinned clock; never `new Date()`.
  const isCurrentMonth = month === currentMonth();
  const { data: summaryData } = useQuery({ ...queries.summary(month), enabled: isCurrentMonth });
  const pace = summaryData?.pace ?? null;

  // The shared projection breakdown sheet, opened from either headline variant.
  const [breakdownOpen, setBreakdownOpen] = useState(false);
  const openBreakdown = useCallback(() => setBreakdownOpen(true), []);
  // Timeline ink-dot click → scroll the feed to that day's card. The rendered
  // day cards are the direct children of the `.month-transition` list, in the
  // same order as `data.days`, so index into that container (no per-card id).
  const scrollToDay = useCallback(
    (date: string) => {
      const idx = data?.days.findIndex((d) => d.date === date) ?? -1;
      if (idx < 0) return;
      const card = document.querySelector(".month-transition")?.children[idx];
      try {
        card?.scrollIntoView({ block: "center", behavior: "smooth" });
      } catch {
        card?.scrollIntoView();
      }
    },
    [data]
  );
  const { summaries, genStatus } = useJournalSummariesOrchestrator(month);
  // Warm the ±1 months' journal + summaries so a follow-up Prev/Next fills the
  // day list from cache; `handlePrefetch` warms the hovered month via the picker.
  usePrefetchJournalMonth(month);
  const handlePrefetch = useCallback(
    (target: string) => prefetchJournalMonth(queryClient, target),
    [queryClient]
  );
  const isGenerating = genStatus?.status === "running";
  const aiEnabled =
    !demo && !!config?.daily_summary_provider && config.daily_summary_provider !== "disabled";
  // Transient nav signal: the header has flipped to `displayMonth` but the
  // data-bound subtree is still catching up to it (or a background refetch is in
  // flight). Feeds the MonthPicker spinner — replaces the removed subtree dim.
  const isNavPending = displayMonth !== month || isFetching;

  // Per-date "regenerating" flags so a DayCard whose summary already exists can
  // show a spinner on its refresh button — otherwise the old summary just sits
  // there through the polling window and the click feels inert.
  const [regenerating, setRegenerating] = useState<Set<string>>(new Set());
  const prevGenStatusRef = useRef(genStatus?.status);
  useEffect(() => {
    const prev = prevGenStatusRef.current;
    const curr = genStatus?.status;
    prevGenStatusRef.current = curr;
    if (prev === "running" && (curr === "idle" || curr === "error")) {
      setRegenerating(new Set());
    }
  }, [genStatus?.status]);

  const handleRegenerate = useCallback(
    async (date: string) => {
      // Flip regenerating before awaiting the 202 so the skeleton / spinner
      // shows instantly — otherwise there's a ~2s dead window until the
      // 2000ms status poll flips genStatus to "running" and the card
      // briefly re-renders the "Summarize" button with nothing happening.
      setRegenerating((s) => {
        const n = new Set(s);
        n.add(date);
        return n;
      });
      try {
        await generateJournalSummaries(month, [date], true);
      } catch (err: unknown) {
        setRegenerating((s) => {
          const n = new Set(s);
          n.delete(date);
          return n;
        });
        const e = err as { status?: number; message?: string };
        if (e.status === 409) {
          toast.error("Another generation is running — try again shortly");
        } else {
          toast.error(e.message || "Failed to regenerate summary");
        }
        return;
      }
      // Kick status polling; the orchestrator hook owns the summaries refetch
      // on running → idle. Invalidating journal-summaries here too would race
      // the backend and produce a double-fetch / flicker.
      queryClient.invalidateQueries({ queryKey: queryKeys.journalSummaryStatus() });
    },
    [month, queryClient]
  );

  // Days in the current month that don't yet have a summary. `summaries` may be
  // undefined while the query loads; with noUncheckedIndexedAccess an absent
  // date reads as undefined, so `!summaries?.summaries[date]` covers both the
  // still-loading and settled-but-missing cases.
  const missingDates = useMemo(
    () => (data ? data.days.map((d) => d.date).filter((date) => !summaries?.summaries[date]) : []),
    [data, summaries]
  );

  const handleGenerateMonth = useCallback(async () => {
    if (missingDates.length === 0) return;
    try {
      await generateJournalSummaries(month, missingDates, false);
    } catch (err: unknown) {
      const e = err as { status?: number; message?: string };
      if (e.status === 409) {
        toast.error("Another generation is running — try again shortly");
      } else {
        toast.error(e.message || "Failed to generate summaries");
      }
      return;
    }
    queryClient.invalidateQueries({ queryKey: queryKeys.journalSummaryStatus() });
  }, [month, missingDates, queryClient]);

  const pct =
    data?.budget_ceiling && data.month_total
      ? (data.month_total / data.budget_ceiling) * 100
      : null;

  const todayLocal = todayLocalISO(config?.timezone);

  // Month elapsed as 0–100. For the current month this is today's day
  // divided by days in month; historical months are fully elapsed (100).
  const monthElapsedPct: number = (() => {
    const daysInMonth = daysInMonthOf(month);
    const todayMonth = todayLocal.slice(0, 7);
    if (todayMonth === month) {
      const todayDay = parseInt(todayLocal.slice(-2), 10);
      return (todayDay / daysInMonth) * 100;
    }
    // Future month or historical month — if historical, full; if future, 0.
    return todayMonth > month ? 100 : 0;
  })();

  // Month-over-month delta: compare current month's spend against the prior
  // month's spend up to the same day-of-month. For historical (complete) months
  // this naturally compares against the full prior month.
  const { monthDelta, prevMonthSpent } = ((): {
    monthDelta: number | null;
    prevMonthSpent: number | null;
  } => {
    if (!data || !prevData || data.days.length === 0 || !data.days[0])
      return { monthDelta: null, prevMonthSpent: null };
    const latestDay = parseInt(data.days[0].date.slice(-2), 10);
    if (!Number.isFinite(latestDay)) return { monthDelta: null, prevMonthSpent: null };
    const prevMtd = prevData.days
      .filter((d) => parseInt(d.date.slice(-2), 10) <= latestDay)
      .reduce((sum, d) => sum + d.day_total, 0);
    if (prevMtd === 0) return { monthDelta: null, prevMonthSpent: null };
    return { monthDelta: data.month_total - prevMtd, prevMonthSpent: prevMtd };
  })();

  const daysInMonth = daysInMonthOf(month);
  const todayMonth = todayLocal.slice(0, 7);
  const daysIntoMonth =
    todayMonth === month
      ? parseInt(todayLocal.slice(-2), 10)
      : todayMonth > month
        ? daysInMonth
        : 0;

  return (
    <div className="space-y-4">
      <PageHeader
        title={`Your ${formatMonthLabelLong(displayMonth).split(" ")[0]} journal`}
        actions={
          <MonthPicker
            month={displayMonth}
            onChange={changeMonth}
            loading={isNavPending && !!data}
            onPrefetch={handlePrefetch}
          />
        }
      />

      {/* Editorial Tidings headline — replaces the legacy spent Card. */}
      {data && (
        <JournalHeadline
          monthLabel={formatMonthLabelLong(month)}
          prevMonthLabel={prevMonthLabel(month)}
          spent={data.month_total}
          budget={data.budget_ceiling ?? null}
          monthDelta={monthDelta}
          prevMonthSpent={prevMonthSpent}
          spentPct={pct}
          pacePct={monthElapsedPct}
          daysRemaining={Math.max(0, daysInMonth - daysIntoMonth)}
          asOfDay={todayMonth === month ? daysIntoMonth : null}
          pace={pace}
          days={data.days}
          onOpenBreakdown={openBreakdown}
          onScrollToDay={scrollToDay}
          onSummarizeMonth={
            aiEnabled && (missingDates.length > 0 || isGenerating)
              ? () => void handleGenerateMonth()
              : null
          }
          summarizing={isGenerating}
        />
      )}

      {/* Shared projection breakdown — the single detail surface for both
          headline variants. Mounted only when a commitment-aware pace exists. */}
      {pace && (
        <ProjectionBreakdownSheet
          open={breakdownOpen}
          onOpenChange={setBreakdownOpen}
          pace={pace}
          budget={data?.budget_ceiling ?? null}
          monthLabel={formatMonthLabelLong(month)}
        />
      )}

      {/* Loading skeleton */}
      {isLoading && !data && (
        <div className="space-y-4">
          {Array.from({ length: 3 }).map((_, i) => (
            <Skeleton key={i} className="h-48 w-full rounded-xl" />
          ))}
        </div>
      )}

      {/* Error state — without it a failed fetch rendered a header and
          nothing else, indistinguishable from an empty month. */}
      {isError && !data && <QueryErrorNotice error={error} onRetry={() => void refetch()} />}

      {/* Day cards — extracted + memoized so the urgent header-flip render
          (displayMonth changed, URL `month` not yet) skips this heavy subtree:
          every prop is derived from the unchanged `month`/`data`, so they stay
          referentially stable and memo bails. The list re-renders a beat later
          in the transition pass, once the URL `month` catches up. */}
      {data && (
        <JournalDayList
          days={data.days}
          budgetCeiling={data.budget_ceiling}
          summaries={summaries}
          aiEnabled={aiEnabled}
          isGenerating={isGenerating}
          regenerating={regenerating}
          onRegenerate={handleRegenerate}
          todayLocal={todayLocal}
          daysInMonth={daysInMonth}
          demo={demo}
        />
      )}

      {demo && <DemoSelfHostedCallout />}
    </div>
  );
}
