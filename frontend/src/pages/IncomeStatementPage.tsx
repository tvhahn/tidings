import { ChevronDown, ChevronRight } from "lucide-react";
import { useCallback, useState, type KeyboardEvent, type ReactNode } from "react";
import { PageHeader } from "@/components/PageHeader";
import { QueryErrorNotice } from "@/components/QueryErrorNotice";
import { Card, CardContent } from "@/components/ui/card";
import { Skeleton } from "@/components/ui/skeleton";
import { YearPicker } from "@/components/YearPicker";
import { useIncomeStatement } from "@/hooks/useIncomeStatement";
import {
  currentMonth,
  currentYear,
  formatCurrency,
  formatCurrencyZeroDash,
  MONTH_LONG,
  MONTH_SHORT,
  parseYearMonth,
} from "@/lib/format";
import type {
  IncomeStatementResponse,
  ExpenseSectionResponse,
  ExpenseCategoryRow,
  IncomeCompanyRow,
} from "@/types/api";

const fmt = formatCurrencyZeroDash;

function fmtPct(n: number | null): string {
  if (n == null) return "—";
  return `${n.toFixed(1)}%`;
}

function handleRowKey(cb: () => void) {
  return (e: KeyboardEvent) => {
    if (e.key === "Enter" || e.key === " ") {
      e.preventDefault();
      cb();
    }
  };
}

type ExpandedSet = Set<string>;

export function IncomeStatementPage() {
  const [year, setYear] = useState(currentYear());
  const { data, isLoading, isError, error, refetch } = useIncomeStatement(year);

  const [expanded, setExpanded] = useState<ExpandedSet>(new Set());

  const toggle = useCallback((key: string) => {
    setExpanded((prev) => {
      const next = new Set(prev);
      if (next.has(key)) next.delete(key);
      else next.add(key);
      return next;
    });
  }, []);

  if (isLoading) {
    return (
      <div className="space-y-4">
        <div className="flex items-center justify-between">
          <Skeleton className="h-8 w-48" />
          <Skeleton className="h-9 w-32" />
        </div>
        <div className="grid grid-cols-2 md:grid-cols-4 gap-3">
          {[...Array(4)].map((_, i) => (
            <Skeleton key={i} className="h-20 rounded-xl" />
          ))}
        </div>
        <Skeleton className="h-96 w-full rounded-xl" />
      </div>
    );
  }

  // A fetch failure must not read as an empty year — render the shared error
  // surface (with retry) instead of the "no data" empty state below.
  if (isError) {
    return (
      <div className="space-y-4">
        <PageHeader
          title="Income statement"
          actions={<YearPicker year={year} onChange={setYear} />}
        />
        <QueryErrorNotice error={error} onRetry={() => void refetch()} />
      </div>
    );
  }

  if (!data) {
    return (
      <div className="space-y-4">
        <PageHeader
          title="Income statement"
          actions={<YearPicker year={year} onChange={setYear} />}
        />
        <p className="text-fg-muted">No data available for {year}.</p>
      </div>
    );
  }

  // Current-year views hide future months entirely: past + current month only.
  // Past-year views show all 12. Collapsing the empty tail is what lets the
  // Total column live on-screen at 1280×800 without horizontal scroll.
  // `currentMonth()` is demo-pinned, so the demo never shows future columns.
  const [nowYear, nowMonth] = parseYearMonth(currentMonth());
  const isCurrentYear = nowYear === data.year;
  const visibleMonthCount = isCurrentYear ? nowMonth : 12;
  const incompleteMonthIdx = isCurrentYear ? nowMonth - 1 : -1;

  return (
    <div className="space-y-4">
      <PageHeader
        title="Income statement"
        actions={<YearPicker year={year} onChange={setYear} />}
      />

      <ReceivedHeadline data={data} isCurrentYear={isCurrentYear} />

      <MetricsBar data={data} isCurrentYear={isCurrentYear} />

      {data.projection.months_elapsed > 0 && data.projection.months_elapsed < 12 && (
        <ProjectionCallout data={data} />
      )}

      {data.committed_floor > 0 && (
        <div className="text-sm text-muted-foreground">
          Fixed commitments: {formatCurrency(data.committed_floor)}/yr (
          {formatCurrency(data.committed_floor / 12)}/mo)
        </div>
      )}

      {/* Desktop spreadsheet */}
      <div className="hidden md:block">
        <SpreadsheetTable
          data={data}
          expanded={expanded}
          onToggle={toggle}
          visibleMonthCount={visibleMonthCount}
          incompleteMonthIdx={incompleteMonthIdx}
        />
      </div>

      {/* Mobile drill-down */}
      <div className="md:hidden">
        <MobileIncomeStatement
          data={data}
          visibleMonthCount={visibleMonthCount}
          incompleteMonthIdx={incompleteMonthIdx}
        />
      </div>
    </div>
  );
}

function ReceivedHeadline({
  data,
  isCurrentYear,
}: {
  data: IncomeStatementResponse;
  isCurrentYear: boolean;
}) {
  const prefix = isCurrentYear ? "YTD" : data.year;
  const wholeAmount = Math.floor(data.income.annual_total);
  const cents = Math.abs(data.income.annual_total - Math.floor(data.income.annual_total))
    .toFixed(2)
    .slice(2);

  return (
    <div className="rounded-[14px] border border-status-success/25 bg-status-success/[0.025] px-5 py-4 sm:px-6 sm:py-5">
      <div className="text-[11px] font-medium uppercase tracking-[0.08em] text-fg-muted">
        Received · {prefix}
      </div>
      <div className="t-display mt-1.5 leading-none text-status-success tabular-nums">
        ${wholeAmount.toLocaleString()}
        <span className="text-[0.65em] font-medium text-fg-muted">.{cents}</span>
      </div>
      <div className="mt-2 text-[13px] text-fg-muted">
        {formatCurrency(data.total_expenses_annual)} spent · {fmtPct(data.savings_rate_annual)}{" "}
        savings rate
      </div>
    </div>
  );
}

function MetricsBar({
  data,
  isCurrentYear,
}: {
  data: IncomeStatementResponse;
  isCurrentYear: boolean;
}) {
  // "Annual" is only honest for past years. Current-year totals are YTD.
  const prefix = isCurrentYear ? "YTD" : "Annual";
  const metrics = [
    { label: `${prefix} income`, value: formatCurrency(data.income.annual_total) },
    { label: `${prefix} expenses`, value: formatCurrency(data.total_expenses_annual) },
    {
      label: `${prefix} net savings`,
      value: formatCurrency(data.net_annual),
      color: data.net_annual >= 0 ? "text-status-success" : "text-status-danger-calm-text",
    },
    {
      label: `${prefix} savings rate`,
      value: fmtPct(data.savings_rate_annual),
      color:
        (data.savings_rate_annual ?? 0) >= 0
          ? "text-status-success"
          : "text-status-danger-calm-text",
    },
  ];

  return (
    <div className="grid grid-cols-2 md:grid-cols-4 gap-3">
      {metrics.map((m) => (
        <div key={m.label} className="rounded-[12px] border border-border bg-card px-4 py-[14px]">
          <p className="text-[11.5px] text-fg-muted">{m.label}</p>
          <p
            className={`mt-1.5 text-[20px] font-semibold leading-tight tracking-[-0.01em] tabular-nums ${
              m.color ?? "text-fg"
            }`}
          >
            {m.value}
          </p>
        </div>
      ))}
    </div>
  );
}

function ProjectionCallout({ data }: { data: IncomeStatementResponse }) {
  const p = data.projection;
  return (
    <div className="rounded-[12px] border border-border bg-card px-4 py-3">
      <p className="text-[10.5px] font-medium uppercase tracking-[0.08em] text-fg-muted">
        YTD projection
      </p>
      <p className="mt-1 text-[13px] text-fg">
        <span className="text-fg-muted">{p.months_elapsed} of 12 months</span>
        {" · "}On pace for{" "}
        <span
          className={
            p.annualized_net >= 0
              ? "font-medium text-status-success"
              : "font-medium text-status-danger-calm-text"
          }
        >
          {formatCurrency(p.annualized_net)}
        </span>{" "}
        net savings by December
      </p>
    </div>
  );
}

// --- Spreadsheet Table ---

interface SpreadsheetProps {
  data: IncomeStatementResponse;
  expanded: ExpandedSet;
  onToggle: (key: string) => void;
  visibleMonthCount: number;
  incompleteMonthIdx: number;
}

function SpreadsheetTable({
  data,
  expanded,
  onToggle,
  visibleMonthCount,
  incompleteMonthIdx,
}: SpreadsheetProps) {
  const visibleMonths = MONTH_SHORT.slice(0, visibleMonthCount);
  return (
    <div className="rounded-xl border border-border/50 overflow-x-auto scroll-shadow-x">
      <table className="w-full text-sm tabular-nums border-collapse">
        <thead>
          <tr className="border-b bg-muted/30">
            <th className="text-left p-2 font-medium text-muted-foreground sticky left-0 bg-muted/30 w-[200px]">
              &nbsp;
            </th>
            {visibleMonths.map((m) => (
              <th key={m} className="text-right p-2 font-medium text-muted-foreground min-w-[80px]">
                {m}
              </th>
            ))}
            <th className="text-right p-2 font-medium text-muted-foreground min-w-[90px]">Total</th>
          </tr>
        </thead>
        <tbody>
          <IncomeSection
            income={data.income}
            expanded={expanded}
            onToggle={onToggle}
            visibleMonthCount={visibleMonthCount}
          />

          {data.expense_sections.map((section) => (
            <ExpenseSection
              key={section.type_name}
              section={section}
              expanded={expanded}
              onToggle={onToggle}
              visibleMonthCount={visibleMonthCount}
            />
          ))}

          <SummaryRow
            label="Total expenses"
            months={data.total_expenses_monthly}
            total={data.total_expenses_annual}
            className="font-semibold bg-muted/30 border-t"
            visibleMonthCount={visibleMonthCount}
          />

          <SummaryRow
            label={
              <span className="flex flex-col leading-tight">
                <span className="font-semibold">Net</span>
                <span className="text-xs text-muted-foreground font-normal">Income − Expenses</span>
              </span>
            }
            months={data.net_monthly}
            total={data.net_annual}
            className="font-semibold border-t"
            colorize
            incompleteMonthIdx={incompleteMonthIdx}
            visibleMonthCount={visibleMonthCount}
          />

          <tr className="border-t">
            <td className="p-2 text-muted-foreground italic sticky left-0 bg-background w-[200px]">
              Savings rate
            </td>
            {data.savings_rate_monthly.slice(0, visibleMonthCount).map((val, i) => {
              const isIncomplete = i === incompleteMonthIdx;
              const colorClass = isIncomplete
                ? "text-muted-foreground/70"
                : val != null && val >= 0
                  ? "text-status-success"
                  : val != null
                    ? "text-status-danger-calm-text"
                    : "text-muted-foreground";
              return (
                <td key={i} className={`text-right p-2 ${colorClass}`}>
                  {fmtPct(val)}
                </td>
              );
            })}
            <td
              className={`text-right p-2 font-medium ${(data.savings_rate_annual ?? 0) >= 0 ? "text-status-success" : "text-status-danger-calm-text"}`}
            >
              {fmtPct(data.savings_rate_annual)}
            </td>
          </tr>
        </tbody>
      </table>
    </div>
  );
}

// --- Income Section ---

function IncomeSection({
  income,
  expanded,
  onToggle,
  visibleMonthCount,
}: {
  income: IncomeStatementResponse["income"];
  expanded: ExpandedSet;
  onToggle: (key: string) => void;
  visibleMonthCount: number;
}) {
  const key = "income";
  const isExpanded = expanded.has(key);

  return (
    <>
      <tr
        className="border-b cursor-pointer hover:bg-muted/30 bg-muted/20 focus-visible:outline-none focus-visible:ring-2 focus-visible:ring-ring"
        onClick={() => onToggle(key)}
        onKeyDown={handleRowKey(() => onToggle(key))}
        role="button"
        tabIndex={0}
        aria-expanded={isExpanded}
      >
        <td className="p-2 font-semibold sticky left-0 bg-muted/20 w-[200px]">
          <span className="flex items-center gap-1">
            {isExpanded ? (
              <ChevronDown className="h-4 w-4" />
            ) : (
              <ChevronRight className="h-4 w-4" />
            )}
            Income
          </span>
        </td>
        {income.monthly_totals.slice(0, visibleMonthCount).map((val, i) => (
          <td key={i} className="text-right p-2 font-medium">
            {fmt(val)}
          </td>
        ))}
        <td className="text-right p-2 font-semibold">{fmt(income.annual_total)}</td>
      </tr>
      {isExpanded &&
        income.companies.map((c) => (
          <CompanyRow
            key={c.company}
            company={c}
            indent={1}
            visibleMonthCount={visibleMonthCount}
          />
        ))}
    </>
  );
}

// --- Expense Section ---

function ExpenseSection({
  section,
  expanded,
  onToggle,
  visibleMonthCount,
}: {
  section: ExpenseSectionResponse;
  expanded: ExpandedSet;
  onToggle: (key: string) => void;
  visibleMonthCount: number;
}) {
  const sectionKey = `section:${section.type_name}`;
  const isSectionExpanded = expanded.has(sectionKey);

  return (
    <>
      <tr
        className="border-b cursor-pointer hover:bg-muted/30 bg-muted/20 focus-visible:outline-none focus-visible:ring-2 focus-visible:ring-ring"
        onClick={() => onToggle(sectionKey)}
        onKeyDown={handleRowKey(() => onToggle(sectionKey))}
        role="button"
        tabIndex={0}
        aria-expanded={isSectionExpanded}
      >
        <td className="p-2 font-semibold sticky left-0 bg-muted/20 w-[200px]">
          <span className="flex items-center gap-1">
            {isSectionExpanded ? (
              <ChevronDown className="h-4 w-4" />
            ) : (
              <ChevronRight className="h-4 w-4" />
            )}
            {section.display_name}
          </span>
        </td>
        {section.monthly_totals.slice(0, visibleMonthCount).map((val, i) => (
          <td key={i} className="text-right p-2 font-medium">
            {fmt(val)}
          </td>
        ))}
        <td className="text-right p-2 font-semibold">{fmt(section.annual_total)}</td>
      </tr>

      {isSectionExpanded &&
        section.categories.map((cat) => (
          <CategoryRow
            key={cat.category}
            cat={cat}
            sectionKey={sectionKey}
            expanded={expanded}
            onToggle={onToggle}
            visibleMonthCount={visibleMonthCount}
          />
        ))}
    </>
  );
}

function CategoryRow({
  cat,
  sectionKey,
  expanded,
  onToggle,
  visibleMonthCount,
}: {
  cat: ExpenseCategoryRow;
  sectionKey: string;
  expanded: ExpandedSet;
  onToggle: (key: string) => void;
  visibleMonthCount: number;
}) {
  const catKey = `${sectionKey}:${cat.category}`;
  const isCatExpanded = expanded.has(catKey);
  const hasCompanies = cat.companies.length > 0;

  return (
    <>
      <tr
        className={`border-b ${hasCompanies ? "cursor-pointer hover:bg-muted/30 focus-visible:outline-none focus-visible:ring-2 focus-visible:ring-ring" : ""}`}
        onClick={hasCompanies ? () => onToggle(catKey) : undefined}
        onKeyDown={hasCompanies ? handleRowKey(() => onToggle(catKey)) : undefined}
        role={hasCompanies ? "button" : undefined}
        tabIndex={hasCompanies ? 0 : undefined}
        aria-expanded={hasCompanies ? isCatExpanded : undefined}
      >
        <td className="p-2 pl-8 capitalize sticky left-0 bg-background w-[200px]">
          <span className="flex items-center gap-1">
            {hasCompanies &&
              (isCatExpanded ? (
                <ChevronDown className="h-3 w-3" />
              ) : (
                <ChevronRight className="h-3 w-3" />
              ))}
            {cat.category}
          </span>
        </td>
        {cat.months.slice(0, visibleMonthCount).map((val, i) => (
          <td key={i} className="text-right p-2">
            {fmt(val)}
          </td>
        ))}
        <td className="text-right p-2 font-medium">{fmt(cat.total)}</td>
      </tr>
      {isCatExpanded &&
        cat.companies.map((c) => (
          <CompanyRow
            key={c.company}
            company={c}
            indent={2}
            visibleMonthCount={visibleMonthCount}
          />
        ))}
    </>
  );
}

function CompanyRow({
  company,
  indent,
  visibleMonthCount,
}: {
  company: IncomeCompanyRow;
  indent: number;
  visibleMonthCount: number;
}) {
  const paddingLeft = indent === 1 ? "pl-8" : "pl-14";
  return (
    <tr className="border-b text-muted-foreground">
      <td className={`p-2 ${paddingLeft} text-xs sticky left-0 bg-background w-[200px]`}>
        {company.company}
      </td>
      {company.months.slice(0, visibleMonthCount).map((val, i) => (
        <td key={i} className="text-right p-2 text-xs">
          {fmt(val)}
        </td>
      ))}
      <td className="text-right p-2 text-xs font-medium">{fmt(company.total)}</td>
    </tr>
  );
}

function SummaryRow({
  label,
  months,
  total,
  className = "",
  colorize = false,
  incompleteMonthIdx = -1,
  visibleMonthCount,
}: {
  label: ReactNode;
  months: number[];
  total: number;
  className?: string;
  colorize?: boolean;
  incompleteMonthIdx?: number;
  visibleMonthCount: number;
}) {
  const colorClass = colorize
    ? total >= 0
      ? "text-status-success"
      : "text-status-danger-calm-text"
    : "";

  return (
    <tr className={`border-b ${className}`}>
      <td className={`p-2 sticky left-0 bg-background w-[200px] ${colorClass}`}>{label}</td>
      {months.slice(0, visibleMonthCount).map((val, i) => {
        const isIncomplete = i === incompleteMonthIdx;
        const cellClass = isIncomplete
          ? "text-muted-foreground/70"
          : colorize
            ? val >= 0
              ? "text-status-success"
              : "text-status-danger-calm-text"
            : "";
        return (
          <td key={i} className={`text-right p-2 ${cellClass}`}>
            {fmt(val)}
          </td>
        );
      })}
      <td className={`text-right p-2 font-semibold ${colorClass}`}>{fmt(total)}</td>
    </tr>
  );
}

// --- Mobile drill-down ---

function MobileIncomeStatement({
  data,
  visibleMonthCount,
  incompleteMonthIdx,
}: {
  data: IncomeStatementResponse;
  visibleMonthCount: number;
  incompleteMonthIdx: number;
}) {
  const [selectedIdx, setSelectedIdx] = useState(visibleMonthCount - 1);
  const clampedIdx = Math.min(Math.max(selectedIdx, 0), visibleMonthCount - 1);

  const incomeForMonth = data.income.monthly_totals[clampedIdx] ?? 0;
  const totalExpenseForMonth = data.total_expenses_monthly[clampedIdx] ?? 0;
  const netForMonth = data.net_monthly[clampedIdx] ?? 0;
  const savingsRateForMonth = data.savings_rate_monthly[clampedIdx];
  const isIncomplete = clampedIdx === incompleteMonthIdx;
  const netColor = isIncomplete
    ? "text-muted-foreground"
    : netForMonth >= 0
      ? "text-status-success"
      : "text-status-danger-calm-text";

  return (
    <div className="space-y-3">
      {/* Month chip selector â horizontal scroll */}
      <div
        className="flex gap-2 overflow-x-auto snap-x pb-1 -mx-1 px-1"
        role="tablist"
        aria-label="Month selector"
      >
        {Array.from({ length: visibleMonthCount }).map((_, i) => {
          const active = i === clampedIdx;
          return (
            <button
              key={i}
              role="tab"
              aria-selected={active}
              onClick={() => setSelectedIdx(i)}
              className={`snap-start shrink-0 rounded-full px-3 py-1.5 text-xs font-medium transition-colors ${
                active
                  ? "bg-brand text-brand-foreground"
                  : "bg-muted text-muted-foreground hover:text-foreground"
              }`}
            >
              {MONTH_SHORT[i]}
            </button>
          );
        })}
      </div>

      {/* Selected month card */}
      <Card className="border-border/50">
        <CardContent className="p-4">
          <div className="flex items-baseline justify-between mb-3">
            <h3 className="text-base font-medium">
              {MONTH_LONG[clampedIdx]} {data.year}
            </h3>
            {isIncomplete && (
              <span className="text-xs text-muted-foreground italic">In progress</span>
            )}
          </div>

          <div className="space-y-1.5 text-sm">
            <MobileRow label="Income" value={fmt(incomeForMonth)} bold />
            {data.expense_sections.map((section) => (
              <MobileRow
                key={section.type_name}
                label={section.display_name}
                value={fmt(section.monthly_totals[clampedIdx] ?? 0)}
                indent
              />
            ))}
            <div className="border-t pt-1.5">
              <MobileRow label="Total expenses" value={fmt(totalExpenseForMonth)} bold />
            </div>
            <div className="border-t pt-1.5 flex items-baseline justify-between">
              <span className={`font-semibold ${netColor}`}>Net</span>
              <span className={`font-semibold tabular-nums ${netColor}`}>{fmt(netForMonth)}</span>
            </div>
            {savingsRateForMonth != null && !isIncomplete && (
              <div className="flex items-baseline justify-between">
                <span className="text-xs text-muted-foreground italic">Savings rate</span>
                <span
                  className={`text-xs tabular-nums ${netForMonth >= 0 ? "text-status-success" : "text-status-danger-calm-text"}`}
                >
                  {fmtPct(savingsRateForMonth)}
                </span>
              </div>
            )}
          </div>
        </CardContent>
      </Card>
    </div>
  );
}

function MobileRow({
  label,
  value,
  bold = false,
  indent = false,
}: {
  label: string;
  value: string;
  bold?: boolean;
  indent?: boolean;
}) {
  return (
    <div className="flex items-baseline justify-between">
      <span
        className={`${bold ? "font-semibold" : "text-muted-foreground"} ${indent ? "pl-3 text-xs" : ""}`}
      >
        {label}
      </span>
      <span
        className={`tabular-nums ${bold ? "font-semibold" : "text-muted-foreground"} ${indent ? "text-xs" : ""}`}
      >
        {value}
      </span>
    </div>
  );
}
