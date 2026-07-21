import { useState } from "react";
import { useNavigate } from "react-router-dom";
import {
  BarChart,
  Bar,
  XAxis,
  YAxis,
  Tooltip,
  ReferenceLine,
  ResponsiveContainer,
  Cell,
  LabelList,
} from "recharts";
import { Card, CardContent, CardHeader, CardTitle } from "@/components/ui/card";
import { useChartTone } from "@/hooks/useChartTone";
import { useMediaQuery } from "@/hooks/useMediaQuery";
import { formatForecastCurrency } from "@/lib/budgetCalc";
import { groupCategory, getGroupColor } from "@/lib/categoryGroups";
import type { CategoryGroup } from "@/lib/categoryGroups";
import { currentMonth, formatCurrency, formatMonthLabel } from "@/lib/format";
import type { TrendResponse } from "@/types/api";

interface SpendingChartProps {
  trend: TrendResponse;
  selectedMonth?: string;
  groups: CategoryGroup[];
  /** L6 — `pace.projected_month_total` for the current month; drives the
   * hatched projection segment. Null/absent = no hatch. */
  projectedTotal?: number | null;
}

/** Synthetic stacked key for the hatched projection remainder (L6). */
const PROJECTED_KEY = "__projected";

/** Check whether trend months span multiple calendar years. */
function spansMultipleYears(months: { year_month: string }[]): boolean {
  if (months.length === 0) return false;
  const years = new Set(months.map((m) => m.year_month.slice(0, 4)));
  return years.size > 1;
}

/** Format a total as compact currency: $950, $5.2k, $12k */
function formatCompactCurrency(value: number): string {
  if (value < 1000) return `$${Math.round(value)}`;
  if (value < 10000) {
    const k = value / 1000;
    const rounded = Math.round(k * 10) / 10;
    return rounded % 1 === 0 ? `$${rounded.toFixed(0)}k` : `$${rounded.toFixed(1)}k`;
  }
  return `$${Math.round(value / 1000)}k`;
}

/** Today's `YYYY-MM` — demo-pinned via `currentMonth()` so the anchored
 * month keeps its in-progress treatment in the static demo. */
function currentYearMonth(): string {
  return currentMonth();
}

/** Build chart data: one row per month, one key per group. `_total` is the
 * actual spend; `__projected` (current-month row only) is the remainder up
 * to the projected month end, stacked last as the hatched segment. */
function buildChartData(
  trend: TrendResponse,
  groups: CategoryGroup[],
  multiYear: boolean,
  currentMonthYm: string,
  projectedTotal: number | null
) {
  return trend.months.map((m) => {
    const row: Record<string, string | number> = {
      month: m.year_month,
      label: formatMonthLabel(m.year_month, multiYear),
    };
    let total = 0;
    for (const [cat, info] of Object.entries(m.by_category)) {
      const group = groupCategory(cat, groups);
      row[group] = ((row[group] as number) || 0) + info.amount;
      total += info.amount;
    }
    row._total = total;
    row[PROJECTED_KEY] =
      m.year_month === currentMonthYm && projectedTotal != null
        ? Math.max(projectedTotal - total, 0)
        : 0;
    return row;
  });
}

interface TooltipPayloadEntry {
  value?: number;
  dataKey?: string;
  color?: string;
  payload?: { month?: string };
}

function CustomTooltip({
  active,
  payload,
  label,
  currentMonthYm,
  projectedTotal,
}: {
  active?: boolean;
  payload?: TooltipPayloadEntry[];
  label?: string;
  currentMonthYm: string;
  projectedTotal: number | null;
}) {
  if (!active || !payload?.length) return null;
  const month = payload[0]?.payload?.month;
  const isCurrent = month === currentMonthYm;
  return (
    <div className="rounded-lg border bg-card p-3 shadow-md">
      <p className="mb-1 text-sm font-medium">
        {label}
        {isCurrent && (
          <span className="ml-2 text-xs font-normal italic text-muted-foreground">in progress</span>
        )}
      </p>
      {payload
        .filter((p: TooltipPayloadEntry) => p.dataKey !== PROJECTED_KEY && (p.value ?? 0) > 0)
        .sort((a: TooltipPayloadEntry, b: TooltipPayloadEntry) => (b.value ?? 0) - (a.value ?? 0))
        .map((p: TooltipPayloadEntry) => (
          <div key={p.dataKey} className="flex items-center gap-2 text-xs">
            <span
              className="inline-block h-2.5 w-2.5 rounded-sm"
              style={{ backgroundColor: p.color }}
            />
            <span className="flex-1">{p.dataKey}</span>
            <span className="font-medium">{formatCurrency(p.value ?? 0)}</span>
          </div>
        ))}
      {isCurrent && projectedTotal != null && (
        <p className="mt-1 text-xs text-muted-foreground">
          projected month end {formatForecastCurrency(projectedTotal)}
        </p>
      )}
    </div>
  );
}

export function SpendingChart({
  trend,
  selectedMonth,
  groups,
  projectedTotal,
}: SpendingChartProps) {
  const navigate = useNavigate();
  const [hoveredIdx, setHoveredIdx] = useState<number | null>(null);
  const tone = useChartTone();
  const isDesktop = useMediaQuery("(min-width: 640px)");
  const showBarLabels = isDesktop;
  const chartHeight = isDesktop ? 350 : 280;
  const axisFontSize = isDesktop ? 12 : 10;
  const multiYear = spansMultipleYears(trend.months);
  const currentMonthYm = currentYearMonth();
  const data = buildChartData(trend, groups, multiYear, currentMonthYm, projectedTotal ?? null);
  const groupNames = [...groups.map((g) => g.name), "Other"];
  const hasProjection = data.some((d) => (d[PROJECTED_KEY] as number) > 0);

  // Dashed 6-mo average reference — mean of complete months only (current
  // month excluded), rendered only when at least 2 complete months exist.
  const completeTotals = data
    .filter((d) => d.month !== currentMonthYm)
    .map((d) => d._total as number);
  const completeAvg =
    completeTotals.length >= 2
      ? completeTotals.reduce((a, b) => a + b, 0) / completeTotals.length
      : null;

  const handleClick = (groupName: string, month: string) => {
    navigate(`/transactions?month=${month}&group=${encodeURIComponent(groupName)}`);
  };

  const isEmpty = data.length === 0 || data.every((d) => (d._total as number) === 0);

  return (
    <Card className="border-border/50">
      <CardHeader className="pb-2">
        <CardTitle className="text-base font-medium">Monthly spending</CardTitle>
      </CardHeader>
      <CardContent>
        {isEmpty ? (
          <div
            className="flex items-center justify-center text-sm text-muted-foreground"
            style={{ height: chartHeight }}
          >
            No spending yet for this range
          </div>
        ) : (
          <ResponsiveContainer width="100%" height={chartHeight}>
            {/* Top margin reserves room for the tallest bar's total label so it
                never collides with the bar when the max lands near the axis top. */}
            {/* Right margin reserves room for the 6-mo avg label so it sits
                outside the plot instead of colliding with the last bar. */}
            <BarChart data={data} margin={{ top: 16, right: completeAvg != null ? 64 : 0 }}>
              {/* Hatch pattern must live inside the chart's <svg> — a
                  pattern defined outside renders black in some browsers. */}
              <defs>
                <pattern
                  id="tidings-projected-hatch"
                  width={6}
                  height={6}
                  patternUnits="userSpaceOnUse"
                  patternTransform="rotate(45)"
                >
                  <line
                    x1="0"
                    y1="0"
                    x2="0"
                    y2="6"
                    stroke="var(--muted-foreground)"
                    strokeWidth={1.5}
                  />
                </pattern>
              </defs>
              <XAxis dataKey="label" tick={{ fontSize: axisFontSize, fill: "var(--foreground)" }} />
              <YAxis
                tick={{ fontSize: axisFontSize, fill: "var(--foreground)" }}
                tickFormatter={(v: number) => `$${(v / 1000).toFixed(0)}k`}
              />
              <Tooltip
                content={
                  <CustomTooltip
                    currentMonthYm={currentMonthYm}
                    projectedTotal={projectedTotal ?? null}
                  />
                }
              />
              {groupNames.map((name, groupIdx) => (
                <Bar
                  key={name}
                  dataKey={name}
                  stackId="spending"
                  fill={getGroupColor(name, groups, tone)}
                  cursor="pointer"
                  onClick={(_entry, index: number) => {
                    const month = data[index]?.month as string;
                    if (month) handleClick(name, month);
                  }}
                  onMouseEnter={(_entry, index: number) => setHoveredIdx(index)}
                  onMouseLeave={() => setHoveredIdx(null)}
                >
                  {data.map((entry, idx) => {
                    const isSelected = selectedMonth === entry.month;
                    const isHovered = hoveredIdx === idx;
                    const fillOpacity = selectedMonth && !isSelected ? 0.7 : 1;
                    let stroke: string = "none";
                    let strokeWidth = 0;
                    let strokeOpacity = 1;
                    if (isSelected) {
                      stroke = "var(--brand)";
                      strokeWidth = 1;
                    } else if (isHovered) {
                      stroke = "var(--brand)";
                      strokeWidth = 1;
                      strokeOpacity = 0.7;
                    }
                    return (
                      <Cell
                        key={entry.month}
                        fillOpacity={fillOpacity}
                        stroke={stroke}
                        strokeWidth={strokeWidth}
                        strokeOpacity={strokeOpacity}
                      />
                    );
                  })}
                  {groupIdx === groupNames.length - 1 && showBarLabels && !hasProjection && (
                    <LabelList
                      dataKey="_total"
                      position="top"
                      formatter={(value) => formatCompactCurrency(Number(value) || 0)}
                      style={{ fontSize: 11, fill: "var(--foreground)" }}
                    />
                  )}
                </Bar>
              ))}
              {/* Hatched projection remainder (L6) — current month only,
                  stacked last, non-clickable, excluded from the legend.
                  The bar-top label rides here so it clears the hatch but
                  keeps showing the ACTUAL total. */}
              {hasProjection && (
                <Bar
                  dataKey={PROJECTED_KEY}
                  stackId="spending"
                  fill="url(#tidings-projected-hatch)"
                  isAnimationActive={false}
                >
                  {showBarLabels && (
                    <LabelList
                      dataKey="_total"
                      position="top"
                      formatter={(value) => formatCompactCurrency(Number(value) || 0)}
                      style={{ fontSize: 11, fill: "var(--foreground)" }}
                    />
                  )}
                </Bar>
              )}
              {completeAvg != null && (
                <ReferenceLine
                  y={completeAvg}
                  stroke="var(--muted-foreground)"
                  strokeDasharray="4 4"
                  label={{
                    value: "6-mo avg",
                    position: "right",
                    fontSize: 11,
                    fill: "var(--muted-foreground)",
                  }}
                />
              )}
            </BarChart>
          </ResponsiveContainer>
        )}
        {/* Legend */}
        <div className="mt-3 flex flex-wrap gap-x-5 gap-y-1.5 sm:gap-x-6">
          {groupNames.map((name) => (
            <div key={name} className="flex items-center gap-1.5 text-xs text-fg-secondary">
              <span
                className="inline-block h-2.5 w-2.5 rounded-sm shrink-0"
                style={{ backgroundColor: getGroupColor(name, groups, tone) }}
              />
              {name}
            </div>
          ))}
        </div>
      </CardContent>
    </Card>
  );
}
