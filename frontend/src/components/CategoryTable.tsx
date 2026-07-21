import { ChevronRight, Settings2 } from "lucide-react";
import { useNavigate } from "react-router-dom";
import { Card, CardContent, CardHeader, CardTitle } from "@/components/ui/card";
import {
  Table,
  TableBody,
  TableCell,
  TableHead,
  TableHeader,
  TableRow,
} from "@/components/ui/table";
import { useChartTone } from "@/hooks/useChartTone";
import type { CategoryGroup, ChartTone } from "@/lib/categoryGroups";
import { groupCategory, getGroupColor } from "@/lib/categoryGroups";
import { formatCurrency, formatVariance } from "@/lib/format";
import { cn } from "@/lib/utils";
import type { MonthSummary, TrendResponse } from "@/types/api";

interface CategoryTableProps {
  current: MonthSummary;
  trend: TrendResponse;
  groups: CategoryGroup[];
  /** True when the displayed month is the in-progress month (`pace != null`
   * on the summary response) — suppresses the vs-avg comparison, which
   * would pit a partial month against full-month averages. */
  isCurrentMonth: boolean;
  onEditGroups?: () => void;
}

interface GroupRow {
  name: string;
  amount: number;
  count: number;
  color: string;
  /** Per-month totals for sparkline, oldest-first. */
  history: number[];
  /** L7b — amount minus the mean of *other complete* trend months; null for
   * the current (partial) month or when fewer than 2 other complete months
   * exist. */
  vsAvg: number | null;
  /** Mirrors the old anomaly rule: amount ≥ 1.5 × mean of other months. */
  vsAvgDanger: boolean;
}

export interface CategoryRowsResult {
  rows: GroupRow[];
  /** L7c — rows with zero amount and zero count this month, collapsed into
   * one muted line after the data rows. */
  zeroCount: number;
}

// eslint-disable-next-line react-refresh/only-export-components -- pure row math exported for unit tests (spec L7)
export function buildGroupRows(
  current: MonthSummary,
  trend: TrendResponse,
  groups: CategoryGroup[],
  tone: ChartTone,
  isCurrentMonth: boolean
): CategoryRowsResult {
  const allGroups = [...groups.map((g) => g.name), "Other"];

  // Current month totals per group
  const groupTotals = new Map<string, { amount: number; count: number }>();
  for (const g of allGroups) {
    groupTotals.set(g, { amount: 0, count: 0 });
  }
  for (const [cat, info] of Object.entries(current.by_category)) {
    const totals = groupTotals.get(groupCategory(cat, groups));
    if (totals) {
      totals.amount += info.amount;
      totals.count += info.count;
    }
  }

  // Build per-group history from trend
  const groupHistory = new Map<string, number[]>();
  for (const g of allGroups) {
    groupHistory.set(g, []);
  }
  for (const m of trend.months) {
    const monthGroup = new Map<string, number>();
    for (const g of allGroups) monthGroup.set(g, 0);
    for (const [cat, info] of Object.entries(m.by_category)) {
      const g = groupCategory(cat, groups);
      monthGroup.set(g, (monthGroup.get(g) ?? 0) + info.amount);
    }
    for (const g of allGroups) {
      groupHistory.get(g)?.push(monthGroup.get(g) ?? 0);
    }
  }

  // Indexes of "other complete months" in the trend: everything except the
  // displayed month (which, when it is the in-progress month, is exactly
  // the partial month the comparison must never include).
  const otherCompleteIdx = trend.months
    .map((m, i) => ({ ym: m.year_month, i }))
    .filter(({ ym }) => ym !== current.year_month)
    .map(({ i }) => i);

  const relevant = allGroups
    .map((name): GroupRow => {
      const hist = groupHistory.get(name) ?? [];
      const totals = groupTotals.get(name) ?? { amount: 0, count: 0 };

      let vsAvg: number | null = null;
      let vsAvgDanger = false;
      if (!isCurrentMonth && otherCompleteIdx.length >= 2) {
        const basis = otherCompleteIdx.map((i) => hist[i] ?? 0);
        const mean = basis.reduce((a, b) => a + b, 0) / basis.length;
        vsAvg = totals.amount - mean;
        vsAvgDanger = mean > 0 && totals.amount >= mean * 1.5;
      }

      return {
        name,
        amount: totals.amount,
        count: totals.count,
        color: getGroupColor(name, groups, tone),
        history: hist,
        vsAvg,
        vsAvgDanger,
      };
    })
    .filter((r) => r.amount > 0 || r.history.some((v) => v > 0))
    .sort((a, b) => b.amount - a.amount);

  const rows = relevant.filter((r) => !(r.amount === 0 && r.count === 0));
  return { rows, zeroCount: relevant.length - rows.length };
}

/** Inline SVG sparkline — lightweight, no Recharts overhead in table cells. */
function Sparkline({ data, color }: { data: number[]; color: string }) {
  if (data.length < 2) return null;
  const max = Math.max(...data, 1);
  const w = 80;
  const h = 24;
  const points = data
    .map((v, i) => {
      const x = (i / (data.length - 1)) * w;
      const y = h - (v / max) * (h - 4) - 2;
      return `${x},${y}`;
    })
    .join(" ");

  return (
    <svg width={w} height={h} className="inline-block">
      <polyline
        points={points}
        fill="none"
        stroke={color}
        strokeWidth={2}
        strokeLinecap="round"
        strokeLinejoin="round"
      />
    </svg>
  );
}

export function CategoryTable({
  current,
  trend,
  groups,
  isCurrentMonth,
  onEditGroups,
}: CategoryTableProps) {
  const navigate = useNavigate();
  const tone = useChartTone();
  const { rows, zeroCount } = buildGroupRows(current, trend, groups, tone, isCurrentMonth);
  const monthTotal = current.total_spending;

  const handleRowClick = (groupName: string) => {
    navigate(`/transactions?month=${current.year_month}&group=${encodeURIComponent(groupName)}`);
  };

  return (
    <Card className="border-border/50">
      <CardHeader className="pb-2">
        <div className="flex items-center justify-between">
          <CardTitle className="text-base font-medium">Categories</CardTitle>
          {onEditGroups && (
            <button
              onClick={onEditGroups}
              className="rounded p-1.5 text-muted-foreground hover:text-foreground hover:bg-muted transition-colors"
              title="Edit category groups"
            >
              <Settings2 className="h-4 w-4" />
            </button>
          )}
        </div>
      </CardHeader>
      <CardContent className="px-2 sm:px-6">
        <Table>
          <TableHeader>
            <TableRow>
              <TableHead>Category</TableHead>
              <TableHead className="hidden sm:table-cell">Share</TableHead>
              <TableHead className="text-right">Amount</TableHead>
              <TableHead className="hidden text-right sm:table-cell">vs avg</TableHead>
              <TableHead className="hidden text-right sm:table-cell">Count</TableHead>
              <TableHead className="hidden text-right sm:table-cell">Trend</TableHead>
              <TableHead className="w-8" />
            </TableRow>
          </TableHeader>
          <TableBody>
            {rows.map((row) => (
              <TableRow
                key={row.name}
                className="group cursor-pointer"
                onClick={() => handleRowClick(row.name)}
              >
                <TableCell>
                  <div className="flex items-center gap-2">
                    <span
                      className="inline-block h-3 w-3 rounded-sm"
                      style={{ backgroundColor: row.color }}
                    />
                    <span className="text-sm">{row.name}</span>
                  </div>
                </TableCell>
                <TableCell className="hidden sm:table-cell">
                  {/* L7a — quiet share-of-month track */}
                  <div className="h-1.5 w-16 overflow-hidden rounded-full bg-muted">
                    <div
                      className="h-full rounded-full"
                      style={{
                        width: `${monthTotal > 0 ? Math.min((row.amount / monthTotal) * 100, 100) : 0}%`,
                        backgroundColor: row.color,
                        opacity: 0.7,
                      }}
                    />
                  </div>
                </TableCell>
                <TableCell className="text-right">
                  <span className="tabular-nums text-sm font-medium">
                    {formatCurrency(row.amount)}
                  </span>
                </TableCell>
                <TableCell className="hidden text-right sm:table-cell">
                  {row.vsAvg == null ? (
                    <span className="text-muted-foreground">—</span>
                  ) : (
                    <span
                      className={cn(
                        "tabular-nums text-sm",
                        row.vsAvgDanger ? "text-status-danger-calm-text" : "text-muted-foreground"
                      )}
                    >
                      {formatVariance(row.vsAvg)}
                    </span>
                  )}
                </TableCell>
                <TableCell className="hidden text-right tabular-nums sm:table-cell">
                  {row.count}
                </TableCell>
                <TableCell className="hidden text-right sm:table-cell">
                  {row.count > 0 ? (
                    <Sparkline data={row.history} color={row.color} />
                  ) : (
                    <span className="text-muted-foreground">—</span>
                  )}
                </TableCell>
                <TableCell className="w-8">
                  <ChevronRight
                    className="h-3.5 w-3.5 text-muted-foreground opacity-0 transition-opacity group-hover:opacity-100"
                    aria-hidden
                  />
                </TableCell>
              </TableRow>
            ))}
            {zeroCount > 0 && (
              <TableRow className="hover:bg-transparent">
                <TableCell colSpan={7} className="text-[12.5px] text-muted-foreground">
                  {zeroCount} {zeroCount === 1 ? "category" : "categories"} with no spending this
                  month
                </TableCell>
              </TableRow>
            )}
          </TableBody>
        </Table>
      </CardContent>
    </Card>
  );
}
