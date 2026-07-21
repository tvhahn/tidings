import { formatForecastCurrency } from "@/lib/budgetCalc";
import {
  formatCurrency,
  formatMonthLabel,
  formatMonthLabelLong,
  formatPercent,
  formatVariance,
  parseYearMonth,
} from "@/lib/format";
import type { SummaryComparisonResponse } from "@/types/api";

type MonthPace = NonNullable<SummaryComparisonResponse["pace"]>;

export interface SummaryCardModel {
  label: string;
  value: string;
  sub: string;
  tone: string;
  icon: "up" | "down" | "receipt" | "transfer" | "gauge";
  /** True when the card opens the shared projection breakdown sheet — set only
   *  on the "Projected month end" card, and only when `pace.breakdown` is
   *  present (the sheet has nothing to show otherwise). Absent means the card
   *  stays a plain, non-interactive tile. */
  opensBreakdown?: boolean;
}

/** Days in a `YYYY-MM` month — explicit-argument Date construction only
 * (never `new Date()` / `Date.now()`; the backend `pace` payload is the
 * only clock signal for "is this the current month"). */
function daysInMonth(yearMonth: string): number {
  const [y, m] = parseYearMonth(yearMonth);
  return new Date(y, m, 0).getDate();
}

/** Float-tolerant boundary compare so e.g. 105/100 lands exactly on ±5%. */
const EPSILON = 1e-9;

/** Assumed statement-channel charges the projection counts but that haven't
 *  posted yet (0 when there's no breakdown or nothing assumed). */
function assumedCommitted(pace: MonthPace): number {
  const a = pace.breakdown?.assumed_committed ?? 0;
  return a > 0 ? a : 0;
}

/** The comparison basis for the lead + "vs typical pace": observed MTD plus any
 *  assumed statement charges. Statement-lag honesty — historical months carry
 *  their imported statement rows, so comparing observed-only MTD against them
 *  understates this month by exactly those not-yet-imported charges. The hero
 *  "Spent so far" figure never uses this; it stays observed-only. */
function effectiveToDate(data: SummaryComparisonResponse, pace: MonthPace): number {
  return data.current.total_spending + assumedCommitted(pace);
}

function depositsCard(data: SummaryComparisonResponse): SummaryCardModel | null {
  const { current } = data;
  if (current.deposit_count <= 0) return null;
  return {
    label: "Deposits",
    value: formatCurrency(current.deposit_total),
    sub: `${current.deposit_count} e-transfer${current.deposit_count !== 1 ? "s" : ""}`,
    tone: "text-fg-muted",
    icon: "transfer",
  };
}

function currentMonthCards(data: SummaryComparisonResponse, pace: MonthPace): SummaryCardModel[] {
  const { current } = data;

  const spentSoFar: SummaryCardModel = {
    label: "Spent so far",
    value: formatCurrency(current.total_spending),
    sub: `day ${pace.day_of_month} of ${pace.days_in_month}`,
    tone: "text-fg-muted",
    icon: "receipt",
  };

  let projected: SummaryCardModel;
  if (pace.projected_month_total == null) {
    projected = {
      label: "Projected month end",
      value: "—",
      sub: "not enough history",
      tone: "text-fg-muted",
      icon: "gauge",
    };
  } else {
    const lo = pace.projected_lower;
    const hi = pace.projected_upper;
    let sub: string;
    if (lo != null && hi != null && lo !== hi) {
      sub = `typical range ${formatForecastCurrency(lo)}–${formatForecastCurrency(hi)}`;
    } else if (pace.forecast_quality === "limited") {
      sub = "limited history";
    } else {
      sub = "based on typical spending";
    }
    projected = {
      label: "Projected month end",
      value: formatForecastCurrency(pace.projected_month_total),
      sub,
      tone: "text-fg-muted",
      icon: "gauge",
      // Clickable only when the commitment-aware breakdown exists (L12 entry
      // point). When it's null the card stays exactly as it is today.
      opensBreakdown: pace.breakdown != null,
    };
  }

  let vsTypical: SummaryCardModel;
  if (pace.typical_to_date == null) {
    vsTypical = {
      label: "vs typical pace",
      value: "—",
      sub: "not enough history",
      tone: "text-fg-muted",
      icon: "gauge",
    };
  } else {
    const assumed = assumedCommitted(pace);
    const diff = current.total_spending + assumed - pace.typical_to_date;
    const above = diff > 0;
    const base = above
      ? `above typical by day ${pace.day_of_month}`
      : `below typical by day ${pace.day_of_month}`;
    vsTypical = {
      label: "vs typical pace",
      value: formatVariance(diff),
      // When assumed statement charges are folded into the comparison, say so —
      // otherwise the fragment stays absent and the card is byte-identical.
      sub: assumed > 0 ? `${base} · statement charges assumed` : base,
      tone: above ? "text-status-danger-calm-text" : "text-status-success",
      icon: above ? "up" : "down",
    };
  }

  return [spentSoFar, projected, vsTypical];
}

function completeMonthCards(data: SummaryComparisonResponse): SummaryCardModel[] {
  const { current, previous, delta_amount, delta_percent } = data;
  const isUp = delta_amount > 0;

  const totalSpending: SummaryCardModel = {
    label: "Total spending",
    value: formatCurrency(current.total_spending),
    sub:
      previous.total_spending === 0
        ? ""
        : `${formatPercent(delta_percent)} vs ${formatMonthLabel(previous.year_month)}`,
    tone: isUp ? "text-status-danger-calm-text" : "text-status-success",
    icon: isUp ? "up" : "down",
  };

  const transactions: SummaryCardModel = {
    label: "Transactions",
    value: String(current.spending_count),
    sub: current.deposit_count > 0 ? `${current.deposit_count} deposits received` : "no deposits",
    tone: "text-fg-muted",
    icon: "receipt",
  };

  const days = daysInMonth(current.year_month);
  const dailyAverage: SummaryCardModel = {
    label: "Daily average",
    value: formatCurrency(current.total_spending / days),
    sub: `across ${days} days`,
    tone: "text-fg-muted",
    icon: "gauge",
  };

  return [totalSpending, transactions, dailyAverage];
}

/** L4 — month-state dependent card sets. A month is "current" iff `pace` is
 * non-null; the pace payload is the only clock signal. */
export function buildSummaryCards(data: SummaryComparisonResponse): SummaryCardModel[] {
  const pace = data.pace ?? null;
  const cards = pace != null ? currentMonthCards(data, pace) : completeMonthCards(data);
  const deposits = depositsCard(data);
  if (deposits) cards.push(deposits);
  return cards;
}

/** L5 — deterministic one-sentence editorial lead; null when inputs are
 * missing (current month with no typical baseline, complete month with a
 * zero previous total). */
export function buildHeadline(data: SummaryComparisonResponse): string | null {
  const pace = data.pace ?? null;

  if (pace != null) {
    const typical = pace.typical_to_date;
    if (typical == null || typical <= 0) return null;
    const deviation = effectiveToDate(data, pace) / typical - 1;
    if (Math.abs(deviation) <= 0.05 + EPSILON) {
      return "Spending is tracking close to typical for this point in the month.";
    }
    const pct = Math.round(Math.abs(deviation) * 100);
    const direction = deviation > 0 ? "above" : "below";
    return `Spending is tracking ${pct}% ${direction} typical for this point in the month.`;
  }

  if (data.previous.total_spending <= 0) return null;
  const monthName = formatMonthLabelLong(data.current.year_month);
  const prevName = formatMonthLabelLong(data.previous.year_month);
  const total = formatCurrency(data.current.total_spending);
  if (Math.abs(data.delta_percent) <= 2 + EPSILON) {
    return `${monthName} closed at ${total}, about even with ${prevName}.`;
  }
  const pct = Math.round(Math.abs(data.delta_percent));
  const direction = data.delta_percent > 0 ? "above" : "below";
  return `${monthName} closed at ${total}, ${pct}% ${direction} ${prevName}.`;
}
