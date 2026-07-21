import { useQueryClient } from "@tanstack/react-query";
import { useEffect, useState } from "react";
import { useSearchParams } from "react-router-dom";
import { CategoryTable } from "@/components/CategoryTable";
import { GroupEditorDialog } from "@/components/GroupEditorDialog";
import { MonthPicker } from "@/components/MonthPicker";
import { PageHeader } from "@/components/PageHeader";
import { ProjectionBreakdownSheet } from "@/components/ProjectionBreakdownSheet";
import { SankeyCashFlow } from "@/components/SankeyCashFlow";
import { SegmentedControl } from "@/components/SegmentedControl";
import { SpendingChart } from "@/components/SpendingChart";
import { SummaryCards } from "@/components/SummaryCards";
import { Skeleton } from "@/components/ui/skeleton";
import { useCashFlow } from "@/hooks/useCashFlow";
import { useCategoryGroups } from "@/hooks/useCategoryGroups";
import { isDemoPrefetchable } from "@/hooks/useDemoMode";
import { useMonthParam } from "@/hooks/useMonthParam";
import { useSummary } from "@/hooks/useSummary";
import { useTrend } from "@/hooks/useTrend";
import { formatMonthLabelLong, shiftMonth } from "@/lib/format";
import { queries } from "@/lib/queryConfigs";
import { buildHeadline } from "@/lib/summaryPace";

type SpendingView = "trend" | "flow";

function isSpendingView(v: string | null): v is SpendingView {
  return v === "trend" || v === "flow";
}

const VIEW_OPTIONS: { value: SpendingView; label: string }[] = [
  { value: "trend", label: "Trend" },
  { value: "flow", label: "Flow" },
];

export function SummaryPage() {
  const [month, setMonth] = useMonthParam();
  const [searchParams, setSearchParams] = useSearchParams();
  const viewParam = searchParams.get("view");
  const view: SpendingView = isSpendingView(viewParam) ? viewParam : "trend";
  const queryClient = useQueryClient();
  const { groups } = useCategoryGroups();
  const [groupEditorOpen, setGroupEditorOpen] = useState(false);
  // The shared projection breakdown sheet — third entry point (L12), opened
  // from the "Projected month end" card. Same sheet as the Journal headline.
  const [breakdownOpen, setBreakdownOpen] = useState(false);

  const { data: summary, isPlaceholderData: summaryStale } = useSummary(month);
  const { data: trend, isPlaceholderData: trendStale } = useTrend(6, month);
  const { graph } = useCashFlow(month);

  const isStale = summaryStale || trendStale;
  const headline = summary ? buildHeadline(summary) : null;

  const setView = (next: SpendingView) => {
    setSearchParams(
      (prev) => {
        const p = new URLSearchParams(prev);
        if (next === "trend") p.delete("view");
        else p.set("view", next);
        return p;
      },
      { replace: true }
    );
  };

  // Prefetch adjacent months for snappy navigation in both directions.
  useEffect(() => {
    for (const m of [shiftMonth(month, -1), shiftMonth(month, 1)]) {
      // Skip months the static demo has no fixture for (a real fetch 404s).
      if (!isDemoPrefetchable(m)) continue;
      queryClient.prefetchQuery(queries.summary(m));
      queryClient.prefetchQuery(queries.trend(6, m));
    }
  }, [month, queryClient]);

  return (
    <div className="space-y-6">
      <PageHeader
        title="Summary"
        titleAdornment={
          isStale && (
            <span className="relative inline-flex h-2 w-2 rounded-full bg-muted-foreground/70" />
          )
        }
        actions={
          <>
            <SegmentedControl
              options={VIEW_OPTIONS}
              value={view}
              onChange={setView}
              ariaLabel="Visualization"
            />
            <MonthPicker month={month} onChange={setMonth} />
          </>
        }
      />

      {/* Editorial lead (L5) — deterministic one-liner, no card */}
      {headline && <p className="text-[13.5px] text-fg-muted">{headline}</p>}

      {/* Summary Cards */}
      {!summary ? (
        <div className="grid grid-cols-2 gap-3 lg:grid-cols-4">
          {Array.from({ length: 4 }).map((_, i) => (
            <Skeleton key={i} className="h-24 w-full rounded-xl" />
          ))}
        </div>
      ) : (
        <SummaryCards data={summary} onOpenBreakdown={() => setBreakdownOpen(true)} />
      )}

      {/* Shared projection breakdown — mounted only when a commitment-aware
          breakdown exists (the card is interactive under the same condition). */}
      {summary?.pace?.breakdown && (
        <ProjectionBreakdownSheet
          open={breakdownOpen}
          onOpenChange={setBreakdownOpen}
          pace={summary.pace}
          budget={null}
          monthLabel={formatMonthLabelLong(month)}
        />
      )}

      {/* Visualization: Trend bars or Cash-flow Sankey */}
      {view === "trend" ? (
        !trend ? (
          <Skeleton className="h-[350px] w-full rounded-xl" />
        ) : (
          <SpendingChart
            trend={trend}
            selectedMonth={month}
            groups={groups}
            projectedTotal={summary?.pace?.projected_month_total ?? null}
          />
        )
      ) : !graph ? (
        <Skeleton className="h-[520px] w-full rounded-xl" />
      ) : (
        <SankeyCashFlow graph={graph} groups={groups} month={month} />
      )}

      {/* Category Table */}
      {!summary || !trend ? (
        <Skeleton className="h-64 w-full rounded-xl" />
      ) : (
        <CategoryTable
          current={summary.current}
          trend={trend}
          groups={groups}
          isCurrentMonth={summary.pace != null}
          onEditGroups={() => setGroupEditorOpen(true)}
        />
      )}

      <GroupEditorDialog open={groupEditorOpen} onOpenChange={setGroupEditorOpen} />
    </div>
  );
}
