import { History, Pencil, Wallet } from "lucide-react";
import { useState } from "react";
import { useNavigate, useSearchParams } from "react-router-dom";
import { BudgetFirstScreen } from "@/components/budgets/BudgetFirstScreen";
import { BudgetTable } from "@/components/BudgetTable";
import { PageHeader } from "@/components/PageHeader";
import { QueryErrorNotice } from "@/components/QueryErrorNotice";
import { SegmentedControl } from "@/components/SegmentedControl";
import { Button } from "@/components/ui/button";
import { Card, CardContent } from "@/components/ui/card";
import { Skeleton } from "@/components/ui/skeleton";
import { Tooltip, TooltipContent, TooltipTrigger } from "@/components/ui/tooltip";
import { UnbudgetedSection } from "@/components/UnbudgetedSection";
import { YearPicker } from "@/components/YearPicker";
import { useBudgetConfig } from "@/hooks/useBudgetConfig";
import { useBudgetStatus } from "@/hooks/useBudgetStatus";
import { currentYear } from "@/lib/format";

type BudgetView = "ytd" | "monthly";

const VIEW_OPTIONS: { value: BudgetView; label: string }[] = [
  { value: "ytd", label: "Year to date" },
  { value: "monthly", label: "Monthly" },
];

export function BudgetPage() {
  const [year, setYear] = useState(currentYear);
  const [searchParams, setSearchParams] = useSearchParams();
  const view: BudgetView = searchParams.get("view") === "monthly" ? "monthly" : "ytd";
  const [showPriorYear, setShowPriorYear] = useState(false);
  const navigate = useNavigate();

  const setView = (next: BudgetView) => {
    setSearchParams(
      (prev) => {
        const p = new URLSearchParams(prev);
        if (next === "ytd") p.delete("view");
        else p.set("view", next);
        return p;
      },
      { replace: true }
    );
  };

  const compareYear = showPriorYear ? year - 1 : undefined;

  const {
    data: config,
    isLoading: configLoading,
    isError: configError,
    error: configErrorObj,
    refetch: refetchConfig,
  } = useBudgetConfig(year);

  const hasConfig = config != null;
  const { data: status, isLoading: statusLoading } = useBudgetStatus(year, hasConfig, compareYear);

  const isLoading = configLoading || (hasConfig && statusLoading);

  const elapsedYearFraction = status?.elapsed_year_fraction ?? 0;

  return (
    <div className="space-y-6">
      <PageHeader
        title="Category budgets"
        actions={<YearPicker year={year} onChange={setYear} />}
      />

      {/* N8.2 controls: the view on the left, Edit on the right. */}
      {hasConfig && (
        <div className="-mt-2 flex items-center justify-between gap-3">
          {status ? (
            <SegmentedControl
              options={VIEW_OPTIONS}
              value={view}
              onChange={setView}
              ariaLabel="Budget view"
            />
          ) : (
            <span />
          )}
          <Button
            variant="ghost"
            size="sm"
            className="text-fg-secondary"
            onClick={() => navigate(`/budgets/edit?year=${year}`)}
          >
            <Pencil className="mr-1 h-3 w-3" /> Edit
          </Button>
        </div>
      )}

      {/* Loading */}
      {isLoading && (
        <div className="space-y-4">
          <Skeleton className="h-24 w-full rounded-xl" />
          <Skeleton className="h-64 w-full rounded-xl" />
        </div>
      )}

      {/* Error — the shared query-error surface (with retry), so a failed load
          is visibly distinct from the "no budget yet" empty state below. */}
      {!isLoading && configError && (
        <QueryErrorNotice error={configErrorObj} onRetry={() => void refetchConfig()} />
      )}

      {/* Empty state */}
      {!isLoading && !configError && !hasConfig && (
        <Card className="border-border/50">
          <CardContent className="flex flex-col items-center gap-4 py-12 text-center">
            <div className="rounded-full bg-muted p-4">
              <Wallet className="h-8 w-8 text-muted-foreground" />
            </div>
            <div>
              <h3 className="text-lg font-medium">Set up your {year} budget</h3>
              <p className="mt-1 text-sm text-muted-foreground">
                Track your spending against targets and see if you're on pace.
              </p>
            </div>
            <div className="flex gap-2">
              <Button variant="outline" onClick={() => navigate(`/budgets/edit?year=${year}`)}>
                Start from scratch
              </Button>
              <Button onClick={() => navigate(`/budgets/edit?year=${year}&prefill=history`)}>
                Start with historical averages
              </Button>
            </div>
          </CardContent>
        </Card>
      )}

      {/* Dashboard */}
      {!isLoading && hasConfig && status && (
        <>
          <BudgetFirstScreen status={status} />

          <div className="flex items-center justify-between gap-3 pt-2">
            <h2 className="text-[13px] font-medium text-fg-muted">
              {view === "ytd" ? "All categories, year to date" : "All categories, by month"}
            </h2>
            {view === "ytd" && (
              <Tooltip>
                <TooltipTrigger asChild>
                  <Button
                    variant="ghost"
                    size="sm"
                    aria-label={`Compare with ${year - 1}`}
                    aria-pressed={showPriorYear}
                    onClick={() => setShowPriorYear((p) => !p)}
                    className={
                      showPriorYear
                        ? "ring-1 ring-border/60 text-foreground"
                        : "text-muted-foreground"
                    }
                  >
                    <History className="mr-1 h-3 w-3" />
                    {year - 1}
                  </Button>
                </TooltipTrigger>
                <TooltipContent>Compare with {year - 1}</TooltipContent>
              </Tooltip>
            )}
          </div>

          <BudgetTable
            status={status}
            view={view}
            elapsedYearFraction={elapsedYearFraction}
            showPriorYear={showPriorYear}
            compareYear={compareYear}
          />

          <UnbudgetedSection
            categories={status.unbudgeted}
            onSetBudget={(cat) => navigate(`/budgets/edit?year=${year}&add=${cat}`)}
          />
        </>
      )}
    </div>
  );
}
