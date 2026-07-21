import { ChevronDown, ChevronRight, Lock } from "lucide-react";
import { useState, useCallback } from "react";
import { useNavigate } from "react-router-dom";
import { Tooltip, TooltipContent, TooltipTrigger } from "@/components/ui/tooltip";
import { useCategoryGroups } from "@/hooks/useCategoryGroups";
import { useChartTone } from "@/hooks/useChartTone";
import { forecastRangeLabel, formatForecastCurrency } from "@/lib/budgetCalc";
import { groupMonthlyBudget, heatClass } from "@/lib/budgetHeat";
import { getGroupColor } from "@/lib/categoryGroups";
import {
  currentMonth,
  formatCurrencyZeroDash,
  formatVariance,
  MONTH_SHORT,
  titleCase,
} from "@/lib/format";
import { paceSeverity, severityTextClass } from "@/lib/severity";
import type { BudgetStatusResponse, GroupPace, CategoryPaceDetail } from "@/types/api";

/** Right-aligned pace-percent color: muted under 100, severity color at ≥100. */
function pacePctClass(pct: number): string {
  return pct >= 100 ? severityTextClass[paceSeverity(pct)] : "text-muted-foreground";
}

/** Lock marker + tooltip for fixed-amount categories (L9). */
function FixedMarker() {
  return (
    <Tooltip>
      <TooltipTrigger asChild>
        <Lock className="h-3 w-3 text-fg-muted" />
      </TooltipTrigger>
      <TooltipContent>Fixed expense — same amount each month</TooltipContent>
    </Tooltip>
  );
}

function varianceClass(actual: number, expected: number): string {
  if (expected <= 0) return "";
  if (actual <= expected) return "text-status-success";
  return severityTextClass[paceSeverity((actual / expected) * 100)];
}

function overspendClass(actual: number, expected: number): string {
  // For category rows: under/on-budget rendered in default color (less noisy).
  if (expected <= 0 || actual <= expected) return "";
  return severityTextClass[paceSeverity((actual / expected) * 100)];
}

const fmt = formatCurrencyZeroDash;

interface BudgetTableProps {
  status: BudgetStatusResponse;
  view: "ytd" | "monthly";
  elapsedYearFraction: number;
  showPriorYear?: boolean | undefined;
  compareYear?: number | undefined;
}

export function BudgetTable({
  status,
  view,
  elapsedYearFraction,
  showPriorYear,
  compareYear,
}: BudgetTableProps) {
  const { groups: categoryGroups } = useCategoryGroups();
  const [collapsed, setCollapsed] = useState<Set<string>>(new Set());

  const toggle = useCallback((key: string) => {
    setCollapsed((prev) => {
      const next = new Set(prev);
      if (next.has(key)) next.delete(key);
      else next.add(key);
      return next;
    });
  }, []);

  // Determine which months have data for monthly view
  const activeMonths = status.monthly_totals.map((v, i) => (v > 0 ? i : -1)).filter((i) => i >= 0);

  // Compute totals across all groups
  const totalBudget = status.groups.reduce((s, g) => s + g.budgeted_total, 0);
  const totalYtdSpent = status.groups.reduce((s, g) => s + g.ytd_spent, 0);
  const totalVariance = totalBudget * elapsedYearFraction - totalYtdSpent;

  if (view === "monthly") {
    return (
      <MonthlyTable
        status={status}
        activeMonths={activeMonths}
        categoryGroups={categoryGroups}
        collapsed={collapsed}
        onToggle={toggle}
        totalBudget={totalBudget}
        totalYtdSpent={totalYtdSpent}
      />
    );
  }

  return (
    <YTDTable
      status={status}
      elapsedYearFraction={elapsedYearFraction}
      categoryGroups={categoryGroups}
      collapsed={collapsed}
      onToggle={toggle}
      totalBudget={totalBudget}
      totalYtdSpent={totalYtdSpent}
      totalVariance={totalVariance}
      showPriorYear={showPriorYear}
      compareYear={compareYear}
    />
  );
}

// ---------------------------------------------------------------------------
// YTD View
// ---------------------------------------------------------------------------

interface YTDTableProps {
  status: BudgetStatusResponse;
  elapsedYearFraction: number;
  categoryGroups: { name: string; categories: string[] }[];
  collapsed: Set<string>;
  onToggle: (key: string) => void;
  totalBudget: number;
  totalYtdSpent: number;
  totalVariance: number;
  showPriorYear?: boolean | undefined;
  compareYear?: number | undefined;
}

function YTDTable({
  status,
  elapsedYearFraction,
  categoryGroups,
  collapsed,
  onToggle,
  totalBudget,
  totalYtdSpent,
  totalVariance,
  showPriorYear,
  compareYear,
}: YTDTableProps) {
  const totalExpected = totalBudget * elapsedYearFraction;
  const totalPacePct = totalExpected > 0 ? Math.round((totalYtdSpent / totalExpected) * 100) : null;
  return (
    <div className="space-y-2">
      <div className="rounded-xl border border-border/50 overflow-x-auto scroll-shadow-x">
        <table className="w-full text-sm border-collapse min-w-[700px]">
          <thead>
            <tr className="border-b bg-muted/30">
              <th className="text-left p-2 font-medium text-muted-foreground sticky left-0 bg-muted/30 min-w-[180px]">
                Category
              </th>
              <th className="text-right p-2 font-medium text-muted-foreground min-w-[70px]">
                Pace
              </th>
              <th className="text-right p-2 font-medium text-muted-foreground min-w-[90px]">
                YTD spent
              </th>
              <th className="text-right p-2 font-medium text-muted-foreground min-w-[90px]">
                Monthly budget
              </th>
              <th className="text-right p-2 font-medium text-muted-foreground min-w-[90px]">
                Annual budget
              </th>
              {showPriorYear && (
                <th className="text-right p-2 font-medium text-muted-foreground min-w-[90px]">
                  {compareYear} actual
                </th>
              )}
              <th className="text-right p-2 font-medium text-muted-foreground min-w-[90px]">
                Variance
              </th>
            </tr>
          </thead>
          <tbody>
            {status.groups
              .filter((g) => g.categories.length > 0)
              .map((group) => (
                <YTDGroupRows
                  key={group.name}
                  group={group}
                  elapsedYearFraction={elapsedYearFraction}
                  categoryGroups={categoryGroups}
                  isCollapsed={collapsed.has(group.name)}
                  onToggle={() => onToggle(group.name)}
                  showPriorYear={showPriorYear}
                />
              ))}

            {/* Footer: Total Budgeted */}
            <tr className="border-t font-semibold bg-muted/30">
              <td className="p-2 sticky left-0 bg-muted/30">Total budgeted</td>
              <td
                className={`text-right p-2 tabular-nums ${
                  totalPacePct != null ? pacePctClass(totalPacePct) : ""
                }`}
              >
                {totalPacePct != null ? `${totalPacePct}%` : ""}
              </td>
              <td className="text-right p-2">{fmt(totalYtdSpent)}</td>
              <td className="text-right p-2 text-muted-foreground">
                {fmt(
                  status.groups.reduce(
                    (s, g) =>
                      s +
                      g.categories
                        .filter((c) => c.category_type !== "lumpy")
                        .reduce((a, c) => a + c.monthly_amount, 0),
                    0
                  )
                )}
              </td>
              <td className="text-right p-2">{fmt(totalBudget)}</td>
              {showPriorYear && (
                <td className="text-right p-2 text-muted-foreground">
                  {fmt(status.prior_year_total ?? 0)}
                </td>
              )}
              <td
                className={`text-right p-2 ${varianceClass(totalYtdSpent, totalBudget * elapsedYearFraction)}`}
              >
                {formatVariance(Math.round(totalVariance))}
              </td>
            </tr>

            {/* Spending ceiling row */}
            <tr className="text-muted-foreground bg-muted/30">
              <td className="p-2 sticky left-0 bg-muted/30">Spending ceiling</td>
              <td />
              <td />
              <td className="text-right p-2">-</td>
              <td className="text-right p-2">{fmt(status.overall.spending_ceiling)}</td>
              {showPriorYear && <td />}
              <td />
            </tr>
          </tbody>
        </table>
      </div>
      <p className="px-1 text-[11.5px] text-fg-muted">
        Pace and variance compare spending with the budget pro-rated to today.
      </p>
    </div>
  );
}

function YTDGroupRows({
  group,
  elapsedYearFraction,
  categoryGroups,
  isCollapsed,
  onToggle,
  showPriorYear,
}: {
  group: GroupPace;
  elapsedYearFraction: number;
  categoryGroups: { name: string; categories: string[] }[];
  isCollapsed: boolean;
  onToggle: () => void;
  showPriorYear?: boolean | undefined;
}) {
  const tone = useChartTone();
  const color = getGroupColor(group.name, categoryGroups, tone);
  const groupExpected = group.budgeted_total * elapsedYearFraction;
  const groupVariance = groupExpected - group.ytd_spent;
  const varianceColor = varianceClass(group.ytd_spent, groupExpected);
  const groupPacePct =
    groupExpected > 0 ? Math.round((group.ytd_spent / groupExpected) * 100) : null;
  const washed = groupPacePct != null && groupPacePct >= 100;
  const rowBg = washed ? "bg-status-danger-wash" : "bg-muted/20";

  return (
    <>
      {/* Group header */}
      <tr
        className={`border-b cursor-pointer ${washed ? "bg-status-danger-wash" : "hover:bg-muted/30 bg-muted/20"}`}
        onClick={onToggle}
      >
        <td className={`p-2 font-semibold sticky left-0 ${rowBg}`}>
          <span className="flex items-center gap-2">
            <span
              className="h-2.5 w-2.5 shrink-0 rounded-full"
              style={{ backgroundColor: color }}
            />
            {isCollapsed ? (
              <ChevronRight className="h-4 w-4 text-muted-foreground" />
            ) : (
              <ChevronDown className="h-4 w-4 text-muted-foreground" />
            )}
            {group.name}
          </span>
        </td>
        <td
          className={`text-right p-2 font-medium tabular-nums ${
            groupPacePct != null ? pacePctClass(groupPacePct) : ""
          }`}
        >
          {groupPacePct != null ? `${groupPacePct}%` : ""}
        </td>
        <td className="text-right p-2 font-medium">{fmt(group.ytd_spent)}</td>
        <td className="text-right p-2 font-medium text-muted-foreground">
          {fmt(
            group.categories
              .filter((c) => c.category_type !== "lumpy")
              .reduce((s, c) => s + c.monthly_amount, 0)
          )}
        </td>
        <td className="text-right p-2 font-medium">{fmt(group.budgeted_total)}</td>
        {showPriorYear && (
          <td className="text-right p-2 font-medium text-muted-foreground">
            {fmt(group.prior_year_total ?? 0)}
          </td>
        )}
        <td className={`text-right p-2 font-medium ${varianceColor}`}>
          {formatVariance(Math.round(groupVariance))}
        </td>
      </tr>

      {/* Category rows */}
      {!isCollapsed &&
        group.categories.map((cat) => (
          <YTDCategoryRow
            key={cat.category}
            cat={cat}
            elapsedYearFraction={elapsedYearFraction}
            showPriorYear={showPriorYear}
          />
        ))}
    </>
  );
}

function YTDCategoryRow({
  cat,
  elapsedYearFraction,
  showPriorYear,
}: {
  cat: CategoryPaceDetail;
  elapsedYearFraction: number;
  showPriorYear?: boolean | undefined;
}) {
  const navigate = useNavigate();
  const ytdVariance = cat.target * elapsedYearFraction - cat.ytd_spent;
  const varianceColor = overspendClass(cat.ytd_spent, cat.target * elapsedYearFraction);

  // Compute YTD pace status
  const ytdExpected = cat.target * elapsedYearFraction;
  const ytdPacePct = ytdExpected > 0 ? Math.round((cat.ytd_spent / ytdExpected) * 100) : 0;
  const washed = ytdPacePct >= 100;
  const stickyBg = washed ? "bg-status-danger-wash" : "bg-background";
  // Variable categories carry a curve forecast; a recurring-dominated category
  // (L14, `forecast_quality === "committed"`) carries a committed forecast even
  // when it's a fixed category — surface the tooltip in both cases.
  const hasForecast =
    cat.forecast_month_total != null &&
    (cat.category_type === "variable" || cat.forecast_quality === "committed");

  return (
    <tr
      className={`border-b cursor-pointer ${washed ? "bg-status-danger-wash" : "hover:bg-muted/30"}`}
      onClick={() => navigate(`/transactions?category=${encodeURIComponent(cat.category)}`)}
    >
      <td className={`p-2 pl-10 sticky left-0 ${stickyBg}`}>
        <span className="flex items-center gap-1.5">
          {titleCase(cat.category)}
          {cat.category_type === "fixed" && <FixedMarker />}
        </span>
      </td>
      <td className={`text-right p-2 tabular-nums ${pacePctClass(ytdPacePct)}`}>
        {hasForecast ? (
          <Tooltip>
            <TooltipTrigger asChild>
              <span>{ytdPacePct}%</span>
            </TooltipTrigger>
            <TooltipContent>
              <ForecastTooltip cat={cat} />
            </TooltipContent>
          </Tooltip>
        ) : (
          <>{ytdPacePct}%</>
        )}
      </td>
      <td className="text-right p-2">{fmt(cat.ytd_spent)}</td>
      <td className="text-right p-2 text-muted-foreground">
        {cat.category_type === "lumpy" ? "—" : fmt(cat.monthly_amount)}
      </td>
      <td className="text-right p-2 text-muted-foreground">{fmt(cat.target)}</td>
      {showPriorYear && (
        <td className="text-right p-2 text-muted-foreground">{fmt(cat.prior_year_total ?? 0)}</td>
      )}
      <td className={`text-right p-2 ${varianceColor}`}>
        {formatVariance(Math.round(ytdVariance))}
      </td>
    </tr>
  );
}

/** L9 — forecast tooltip shown on a category's pace percent. Recurring-dominated
 *  categories (L14) read as "known charges pending" — no variance range, since
 *  the committed terms are point estimates with null bounds. */
function ForecastTooltip({ cat }: { cat: CategoryPaceDetail }) {
  if (cat.forecast_quality === "committed") {
    return (
      <>
        {formatForecastCurrency(cat.forecast_month_total ?? null)} expected this month
        <div className="mt-0.5">includes known charges still to come</div>
      </>
    );
  }
  const suffix =
    cat.forecast_quality === "historical"
      ? " · based on typical spending"
      : cat.forecast_quality === "limited"
        ? " · limited history"
        : "";
  const range = forecastRangeLabel(cat);
  return (
    <>
      {formatForecastCurrency(cat.forecast_month_total ?? null)} projected this month
      {suffix}
      {range && <div className="mt-0.5">{range}</div>}
    </>
  );
}

// ---------------------------------------------------------------------------
// Monthly View
// ---------------------------------------------------------------------------

interface MonthlyTableProps {
  status: BudgetStatusResponse;
  activeMonths: number[];
  categoryGroups: { name: string; categories: string[] }[];
  collapsed: Set<string>;
  onToggle: (key: string) => void;
  totalBudget: number;
  totalYtdSpent: number;
}

function MonthlyTable({
  status,
  activeMonths,
  categoryGroups,
  collapsed,
  onToggle,
  totalBudget,
  totalYtdSpent,
}: MonthlyTableProps) {
  // Current-month column highlight — only when the displayed year is the
  // year of the demo-pinned "current" month (L11).
  const cm = currentMonth();
  const currentColIndex =
    parseInt(cm.slice(0, 4), 10) === status.year ? parseInt(cm.slice(5, 7), 10) - 1 : -1;

  return (
    <div className="space-y-2">
      <div className="rounded-xl border border-border/50 overflow-x-auto scroll-shadow-x">
        <table className="w-full text-sm border-collapse min-w-[900px]">
          <thead>
            <tr className="border-b bg-muted/30">
              <th className="text-left p-2 font-medium text-muted-foreground sticky left-0 bg-muted/30 min-w-[180px]">
                Category
              </th>
              {activeMonths.map((mi) => (
                <th
                  key={mi}
                  className={`text-right p-2 font-medium text-muted-foreground min-w-[72px] ${
                    mi === currentColIndex ? "bg-muted/20" : ""
                  }`}
                >
                  <span className="inline-flex items-center gap-1">
                    {mi === currentColIndex && (
                      <span className="h-1.5 w-1.5 rounded-full bg-brand" />
                    )}
                    {MONTH_SHORT[mi]}
                  </span>
                </th>
              ))}
              <th className="text-right p-2 font-medium text-muted-foreground min-w-[85px]">YTD</th>
              <th className="text-right p-2 font-medium text-muted-foreground min-w-[85px]">
                Annual budget
              </th>
            </tr>
          </thead>
          <tbody>
            {status.groups
              .filter((g) => g.categories.length > 0)
              .map((group) => (
                <MonthlyGroupRows
                  key={group.name}
                  group={group}
                  activeMonths={activeMonths}
                  categoryGroups={categoryGroups}
                  isCollapsed={collapsed.has(group.name)}
                  onToggle={() => onToggle(group.name)}
                  currentColIndex={currentColIndex}
                />
              ))}

            {/* Footer: Total */}
            <tr className="border-t font-semibold bg-muted/30">
              <td className="p-2 sticky left-0 bg-muted/30">Total budgeted</td>
              {activeMonths.map((mi) => (
                <td key={mi} className="text-right p-2">
                  {fmt(status.monthly_totals[mi] ?? 0)}
                </td>
              ))}
              <td className="text-right p-2">{fmt(totalYtdSpent)}</td>
              <td className="text-right p-2">{fmt(totalBudget)}</td>
            </tr>
          </tbody>
        </table>
      </div>
      <div className="flex flex-wrap items-center gap-x-4 gap-y-1 px-1 text-[11.5px] text-fg-muted">
        <span className="inline-flex items-center gap-1.5">
          <span className="h-3 w-3 rounded-sm bg-status-danger-wash" />
          over budget
        </span>
        <span className="inline-flex items-center gap-1.5">
          <span className="h-3 w-3 rounded-sm bg-status-warning-wash" />
          near budget
        </span>
        <span>untinted months are within budget</span>
      </div>
    </div>
  );
}

function MonthlyGroupRows({
  group,
  activeMonths,
  categoryGroups,
  isCollapsed,
  onToggle,
  currentColIndex,
}: {
  group: GroupPace;
  activeMonths: number[];
  categoryGroups: { name: string; categories: string[] }[];
  isCollapsed: boolean;
  onToggle: () => void;
  currentColIndex: number;
}) {
  const tone = useChartTone();
  const color = getGroupColor(group.name, categoryGroups, tone);
  const budget = groupMonthlyBudget(group.categories);

  return (
    <>
      <tr className="border-b cursor-pointer hover:bg-muted/30 bg-muted/20" onClick={onToggle}>
        <td className="p-2 font-semibold sticky left-0 bg-muted/20">
          <span className="flex items-center gap-2">
            <span
              className="h-2.5 w-2.5 shrink-0 rounded-full"
              style={{ backgroundColor: color }}
            />
            {isCollapsed ? (
              <ChevronRight className="h-4 w-4 text-muted-foreground" />
            ) : (
              <ChevronDown className="h-4 w-4 text-muted-foreground" />
            )}
            {group.name}
          </span>
        </td>
        {activeMonths.map((mi) => {
          const heat = heatClass(group.monthly_totals[mi] ?? 0, budget);
          const cellBg = heat || (mi === currentColIndex ? "bg-muted/20" : "");
          return (
            <td key={mi} className={`text-right p-2 font-medium ${cellBg}`}>
              {fmt(group.monthly_totals[mi] ?? 0)}
            </td>
          );
        })}
        <td className="text-right p-2 font-semibold">{fmt(group.ytd_spent)}</td>
        <td className="text-right p-2 font-medium text-muted-foreground">
          {fmt(group.budgeted_total)}
        </td>
      </tr>

      {!isCollapsed &&
        group.categories.map((cat) => (
          <MonthlyCategoryRow
            key={cat.category}
            cat={cat}
            activeMonths={activeMonths}
            currentColIndex={currentColIndex}
          />
        ))}
    </>
  );
}

function MonthlyCategoryRow({
  cat,
  activeMonths,
  currentColIndex,
}: {
  cat: CategoryPaceDetail;
  activeMonths: number[];
  currentColIndex: number;
}) {
  return (
    <tr className="border-b">
      <td className="p-2 pl-10 sticky left-0 bg-background">
        <span className="flex items-center gap-1.5">
          {titleCase(cat.category)}
          {cat.category_type === "fixed" && <FixedMarker />}
        </span>
      </td>
      {activeMonths.map((mi) => {
        // Lumpy categories have no steady monthly budget — never tint them,
        // even though the API reports a positive monthly_amount (annual ÷ 12).
        const heat = heatClass(
          cat.monthly_spent[mi] ?? 0,
          cat.category_type === "lumpy" ? 0 : cat.monthly_amount
        );
        const cellBg = heat || (mi === currentColIndex ? "bg-muted/20" : "");
        return (
          <td key={mi} className={`text-right p-2 ${cellBg}`}>
            {fmt(cat.monthly_spent[mi] ?? 0)}
          </td>
        );
      })}
      <td className="text-right p-2 font-medium">{fmt(cat.ytd_spent)}</td>
      <td className="text-right p-2 text-muted-foreground">{fmt(cat.target)}</td>
    </tr>
  );
}
