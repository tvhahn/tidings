/** Pure models for the N8.2 first screens — the Journal's spent hero, its two
 *  figure tiles and the "regular charges to come" list, and the Budgets hero
 *  with its group tiles. The components are thin renderers over these; all
 *  arithmetic, ordering and wording lives here so it can be unit-tested
 *  without a DOM. No React, no side effects. */

import { formatCurrencyRounded, parseYearMonth } from "@/lib/format";
import type { ExpectedCharge, MonthPaceBreakdown } from "@/lib/projectionBreakdown";
import type { BudgetStatusResponse, GroupPace } from "@/types/api";

/** Clamp a percentage into the 0–100 drawing range. */
function clamp(pct: number): number {
  if (!Number.isFinite(pct)) return 0;
  return Math.min(100, Math.max(0, pct));
}

/** Split an amount into its whole-dollar text and two-digit cents so the
 *  cents can be set muted. Negative amounts are not expected here. */
export function splitCents(amount: number): { whole: string; cents: string } {
  const abs = Math.abs(amount);
  const roundedCents = Math.round(abs * 100);
  const whole = Math.floor(roundedCents / 100);
  const cents = String(roundedCents % 100).padStart(2, "0");
  return { whole: `$${whole.toLocaleString("en-US")}`, cents };
}

/* ---------------------------------------------------------------------------
 * Journal
 * ------------------------------------------------------------------------- */

/** The month-end projection the breakdown sheet totals to (the L5 identity). */
export function projectedMonthTotal(b: MonthPaceBreakdown): number {
  return b.observed_mtd + b.assumed_committed + b.upcoming_committed + b.everyday_remainder;
}

/** Widths for the Journal pace bar: spent so far over a pale run to the
 *  projection. No ticks, no labels on the bar — the ceiling is named beneath. */
export function paceBarWidths(args: { spent: number; budget: number; projected: number | null }): {
  fillPct: number;
  projPct: number | null;
} {
  const { spent, budget, projected } = args;
  if (budget <= 0) return { fillPct: 0, projPct: null };
  const fillPct = clamp((spent / budget) * 100);
  const projPct = projected != null ? clamp((projected / budget) * 100) : null;
  return { fillPct, projPct: projPct != null && projPct > fillPct ? projPct : null };
}

/** Screen-reader text for the pace bar — the bar itself carries no words. */
export function paceBarLabel(args: {
  spent: number;
  budget: number;
  projected: number | null;
}): string {
  const { spent, budget, projected } = args;
  const spentPct = Math.round((spent / budget) * 100);
  const head = `${formatCurrencyRounded(spent)} of the ${formatCurrencyRounded(budget)} ceiling is spent, ${spentPct}%.`;
  if (projected == null) return head;
  const projPct = Math.round((projected / budget) * 100);
  return `${head} The month is heading for about ${formatCurrencyRounded(projected)}, ${projPct}%.`;
}

/** The sentence under the hero figure for a finished month: its result
 *  against the ceiling. (The current month reads forward instead — "Heading for
 *  about …" — which the hero renders with the breakdown button inline.) */
export function closedMonthSentence(args: { spent: number; budget: number | null }): string | null {
  const { spent, budget } = args;
  if (budget == null || budget <= 0) return null;
  const diff = budget - spent;
  if (Math.round(Math.abs(diff)) === 0)
    return `Right at the ${formatCurrencyRounded(budget)} ceiling.`;
  return diff > 0
    ? `${formatCurrencyRounded(diff)} under the ${formatCurrencyRounded(budget)} ceiling.`
    : `${formatCurrencyRounded(-diff)} over the ${formatCurrencyRounded(budget)} ceiling.`;
}

export interface CeilingTile {
  label: string;
  amount: number;
  caption: string;
}

/** "Below the ceiling" tile: room left this month, with the days remaining.
 *  Over the ceiling it says so in words and keeps the figure positive. */
export function ceilingTile(args: {
  spent: number;
  budget: number | null;
  daysRemaining: number;
  monthClosed: boolean;
}): CeilingTile | null {
  const { spent, budget, daysRemaining, monthClosed } = args;
  if (budget == null || budget <= 0) return null;
  const diff = budget - spent;
  const caption = monthClosed
    ? "at month end"
    : daysRemaining === 0
      ? "last day of the month"
      : `${daysRemaining} ${daysRemaining === 1 ? "day" : "days"} left`;
  return diff >= 0
    ? { label: "Below the ceiling", amount: diff, caption }
    : { label: "Over the ceiling", amount: -diff, caption };
}

/** Regular charges still to come this month, in the order they are expected. */
export function upcomingCharges(b: MonthPaceBreakdown): ExpectedCharge[] {
  return b.charges
    .filter((c) => c.status === "upcoming")
    .sort(
      (a, z) => a.expected_day - z.expected_day || a.display_name.localeCompare(z.display_name)
    );
}

/** "Still expected" tile: the sum of regular charges still to come. */
export function stillExpectedTile(b: MonthPaceBreakdown): CeilingTile | null {
  const rows = upcomingCharges(b);
  if (rows.length === 0 || b.upcoming_committed <= 0) return null;
  return {
    label: "Still expected",
    amount: b.upcoming_committed,
    caption: `${rows.length} regular ${rows.length === 1 ? "charge" : "charges"}`,
  };
}

const WEEKDAY_SHORT = ["Sun", "Mon", "Tue", "Wed", "Thu", "Fri", "Sat"];

/** "Fri 20" — the weekday and day of an expected charge within `month`. */
export function chargeDayLabel(month: string, day: number): string {
  const [y, m] = parseYearMonth(month);
  const weekday = WEEKDAY_SHORT[new Date(y, m - 1, day).getDay()] ?? "";
  return `${weekday} ${day}`;
}

/* ---------------------------------------------------------------------------
 * Budgets
 * ------------------------------------------------------------------------- */

/** Where "expected by now" sits on every Budgets bar. Bars are drawn on the
 *  year so far, not the whole year, so differences read in tens of pixels. */
export const BUDGET_TICK_PCT = 60;

/** Widths for a Budgets bar: spending up to the expected mark in ink, any
 *  overage past it in calm red, capped at the bar's end. */
export function budgetBarWidths(args: { spent: number; expected: number }): {
  fillPct: number;
  overPct: number;
} {
  const { spent, expected } = args;
  if (expected <= 0) return { fillPct: spent > 0 ? 100 : 0, overPct: 0 };
  const ratio = spent / expected;
  if (ratio <= 1) return { fillPct: clamp(ratio * BUDGET_TICK_PCT), overPct: 0 };
  return {
    fillPct: BUDGET_TICK_PCT,
    overPct: Math.min(100 - BUDGET_TICK_PCT, (ratio - 1) * BUDGET_TICK_PCT),
  };
}

/** True once the budget year is fully elapsed (a past year). */
export function yearClosed(status: BudgetStatusResponse): boolean {
  return status.elapsed_year_fraction >= 1;
}

/** "Mar 19" from the status `as_of` ISO date. */
function asOfShort(asOf: string): string {
  const [y, m, d] = asOf.slice(0, 10).split("-").map(Number);
  if (!y || !m || !d) return "";
  return new Date(y, m - 1, d).toLocaleDateString("en-US", { month: "short", day: "numeric" });
}

export interface BudgetHeroModel {
  eyebrow: string;
  spent: number;
  sentence: string;
  bar: { fillPct: number; overPct: number };
  key: string;
  ariaLabel: string;
}

/** The Budgets hero: spent this year against the pace for the ceiling. */
export function budgetHero(status: BudgetStatusResponse): BudgetHeroModel {
  const { overall } = status;
  const closed = yearClosed(status);
  const expected = overall.expected_pace;
  const ceiling = formatCurrencyRounded(overall.spending_ceiling);
  const diff = expected - overall.ytd_spent; // positive = under
  const amt = formatCurrencyRounded(Math.abs(diff));
  const even = Math.round(Math.abs(diff)) === 0;

  const sentence = closed
    ? even
      ? `Right at the ${ceiling} ceiling.`
      : `${amt} ${diff > 0 ? "under" : "over"} the ${ceiling} ceiling.`
    : even
      ? `Right on the pace for a ${ceiling} year.`
      : `About ${amt} ${diff > 0 ? "under" : "over"} the pace for a ${ceiling} year.`;

  const expectedText = formatCurrencyRounded(expected);
  return {
    eyebrow: closed
      ? `Spent in ${status.year}`
      : `Spent this year · as of ${asOfShort(status.as_of)}`,
    spent: overall.ytd_spent,
    sentence,
    bar: budgetBarWidths({ spent: overall.ytd_spent, expected }),
    key: closed ? `${ceiling} ceiling` : `${expectedText} expected by now`,
    ariaLabel: closed
      ? `${formatCurrencyRounded(overall.ytd_spent)} spent against the ${ceiling} ceiling.`
      : `${formatCurrencyRounded(overall.ytd_spent)} spent against ${expectedText} expected by ${asOfShort(status.as_of)}.`,
  };
}

export interface GroupTileModel {
  name: string;
  /** "over by" / "under by" / "on pace" — set lighter than the amount. */
  stateWords: string;
  /** "$736", or empty when the group is on pace. */
  stateAmount: string;
  bar: { fillPct: number; overPct: number } | null;
  caption: string;
  wide: boolean;
}

/** One tile per budget group, the most over first and the most under last.
 *  The first tile spans the row when the count is odd, so the grid closes. */
export function groupTiles(status: BudgetStatusResponse): GroupTileModel[] {
  const closed = yearClosed(status);
  const groups: GroupPace[] = [...status.groups]
    .filter((g) => g.budgeted_total > 0 || g.ytd_spent > 0)
    .sort((a, z) => z.ytd_spent - z.expected_pace - (a.ytd_spent - a.expected_pace));
  const oddCount = groups.length % 2 === 1;

  return groups.map((g, i) => {
    const wide = oddCount && i === 0;
    const diff = g.ytd_spent - g.expected_pace; // positive = over
    const even = Math.round(Math.abs(diff)) === 0;
    const spent = formatCurrencyRounded(g.ytd_spent);
    const expected = formatCurrencyRounded(g.expected_pace);
    const caption =
      g.expected_pace <= 0
        ? `${spent} spent, no budget set`
        : wide
          ? closed
            ? `${spent} spent of a ${expected} budget`
            : `${spent} spent of ${expected} expected by now`
          : `${spent} of ${expected}`;
    return {
      name: g.name,
      stateWords: even ? "on pace" : diff > 0 ? "over by" : "under by",
      stateAmount: even ? "" : formatCurrencyRounded(Math.abs(diff)),
      bar:
        g.expected_pace > 0
          ? budgetBarWidths({ spent: g.ytd_spent, expected: g.expected_pace })
          : null,
      caption,
      wide,
    };
  });
}

/* ---------------------------------------------------------------------------
 * Shared surface classes (pure strings, so the component files can export only
 * components — react-refresh forbids mixing).
 * ------------------------------------------------------------------------- */

/** A first-screen card: the hero and every tile share this edge and radius. */
export const TILE_CARD =
  "relative min-w-0 rounded-[var(--radius-tidings-md)] border border-border/70 bg-card dark:border-border";

/* ---------------------------------------------------------------------------
 * Sidebar — last six months against the ceiling
 * ------------------------------------------------------------------------- */

export interface MonthBar {
  month: string;
  /** Height of the spent bar, 0–100 of the plot. */
  spentPct: number;
  /** Height of the pale projection behind the current month's bar, or null. */
  projPct: number | null;
  current: boolean;
}

export interface MonthBarsModel {
  bars: MonthBar[];
  /** Where the dashed ceiling line sits, 0–100 from the bottom, or null. */
  ceilingPct: number | null;
  ariaLabel: string;
}

/** The sidebar's six-month chart. Bars share one scale — the ceiling, or the
 *  largest month when that is higher — and the current month shows its
 *  projected total behind what is spent, so a part month is not read as a
 *  light one. */
export function monthBars(args: {
  months: { year_month: string; total_spending: number }[];
  currentMonth: string;
  ceiling: number | null;
  projected: number | null;
}): MonthBarsModel | null {
  const { months, currentMonth: cur, ceiling, projected } = args;
  if (months.length === 0) return null;
  const scale = Math.max(ceiling ?? 0, projected ?? 0, ...months.map((m) => m.total_spending));
  if (scale <= 0) return null;
  const bars = months.map((m) => {
    const current = m.year_month === cur;
    const spentPct = clamp((m.total_spending / scale) * 100);
    const projPct =
      current && projected != null && projected > m.total_spending
        ? clamp((projected / scale) * 100)
        : null;
    return { month: m.year_month, spentPct, projPct, current };
  });

  const monthName = (ym: string) => {
    const [y, mo] = parseYearMonth(ym);
    return new Date(y, mo - 1, 1).toLocaleDateString("en-US", { month: "long" });
  };
  let ariaLabel: string;
  if (ceiling != null && ceiling > 0) {
    const share = (v: number) => Math.round((v / ceiling) * 100);
    const past = months.filter((m) => m.year_month !== cur);
    const parts = [
      `Spending in the last ${months.length} months against the ${formatCurrencyRounded(ceiling)} ceiling.`,
    ];
    const first = past[0];
    const last = past[past.length - 1];
    if (first && last && past.length === 1) {
      parts.push(`${monthName(first.year_month)} was at ${share(first.total_spending)}% of it.`);
    } else if (first && last) {
      const shares = past.map((m) => share(m.total_spending));
      parts.push(
        `${monthName(first.year_month)} to ${monthName(last.year_month)} were between ${Math.min(...shares)}% and ${Math.max(...shares)}% of it.`
      );
    }
    const now = months.find((m) => m.year_month === cur);
    if (now) {
      parts.push(
        projected != null
          ? `${monthName(cur)} is at ${share(now.total_spending)}% and heading for ${share(projected)}%.`
          : `${monthName(cur)} is at ${share(now.total_spending)}%.`
      );
    }
    ariaLabel = parts.join(" ");
  } else {
    ariaLabel = `Spending in the last ${months.length} months.`;
  }

  return {
    bars,
    ceilingPct: ceiling != null && ceiling > 0 ? clamp((ceiling / scale) * 100) : null,
    ariaLabel,
  };
}
