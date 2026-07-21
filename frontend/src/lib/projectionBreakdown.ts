/** Pure row-model builder for the projection breakdown sheet (L12).
 *
 *  The sheet component is a thin renderer over the model this file produces:
 *  all section grouping, ordering, ordinal-day phrasing, quiet-signal lines,
 *  and currency formatting live here so they can be unit-tested without a DOM.
 *
 *  Derived from the commitment-aware `pace.breakdown` payload (L5/L6). No React,
 *  no side effects. Amounts go through the house formatters (U+2212 minus). */

import { formatCurrency, formatCurrencyRounded, MONTH_SHORT } from "@/lib/format";
import type { VerdictTone } from "@/lib/headlineVerdict";
import type { SummaryComparisonResponse } from "@/types/api";

/** The pace block, narrowed to non-null — the shape the current-month summary
 *  returns. Derived from the generated schema so a backend change flows through. */
export type MonthPace = NonNullable<SummaryComparisonResponse["pace"]>;
/** The commitment-aware decomposition; present only when the derivation succeeds. */
export type MonthPaceBreakdown = NonNullable<MonthPace["breakdown"]>;
/** One expected recurring charge with its derived status. */
export type ExpectedCharge = MonthPaceBreakdown["charges"][number];

/* ---------------------------------------------------------------------------
 * Shared headline presentation constants.
 *
 * These live in this (non-component) module so the headline component files can
 * export only components — `react-refresh/only-export-components` forbids mixing
 * component and value exports — while the container and both variants share one
 * definition. Pure strings and math; no JSX.
 * ------------------------------------------------------------------------- */

/** Outer strip shell — shared by the legacy fallback and both projection
 *  variants so the box geometry never drifts between treatments. */
export const HEADLINE_WRAPPER =
  "group/headline relative grid grid-cols-1 gap-7 rounded-[var(--radius-tidings-md)] border border-border/50 bg-card px-5 py-5 sm:grid-cols-[1.4fr_1fr] sm:items-end sm:px-6 sm:py-6";

/** Verdict tone → pace-bar fill class. One place so the bar color always
 *  tracks the words `headlineVerdict` chose. */
export const TONE_BAR: Record<VerdictTone, string> = {
  success: "bg-status-success",
  warning: "bg-status-warning",
  danger: "bg-status-danger-calm",
};

/** Track and tick colors, matched to the shipped strip (mockup `--track`/`--tick`). */
export const BAR_TRACK = "bg-[color-mix(in_oklch,var(--fg)_7%,transparent)]";
export const BAR_TICK = "bg-[color-mix(in_oklch,var(--fg)_50%,transparent)]";

/** Clamp a percentage into the 0–100 painting range. */
export function clampPct(n: number): number {
  return Math.max(0, Math.min(100, n));
}

export interface VsPrevDelta {
  /** Signed delta to display (negative = under the prior month to date). */
  delta: number;
  /** True when statement-assumed spend was folded in to make the comparison
   *  honest — the "like for like" case. */
  likeForLike: boolean;
}

/** The vs-previous-month comparison, corrected for statement observation lag.
 *
 *  The naive `monthDelta` (`observed − prevMonthSpent`) is skewed for
 *  statement-lag users: the prior month's to-date total already includes its
 *  imported statement rows, while the current month's have not landed yet — so
 *  the current month looks artificially cheap. When a breakdown exists and there
 *  is assumed (statement-observed) committed spend, fold it into the current
 *  side so both months count their statement charges. Otherwise the delta is
 *  exactly today's `monthDelta`. The hero "spent so far" figure is untouched —
 *  this only corrects the comparison column. */
export function vsPrevDelta(args: {
  monthDelta: number;
  prevMonthSpent: number;
  breakdown: MonthPaceBreakdown | null;
}): VsPrevDelta {
  const { monthDelta, prevMonthSpent, breakdown } = args;
  if (breakdown != null && breakdown.assumed_committed > 0) {
    return {
      delta: breakdown.observed_mtd + breakdown.assumed_committed - prevMonthSpent,
      likeForLike: true,
    };
  }
  return { delta: monthDelta, likeForLike: false };
}

/** Approximate amount — a whole-dollar figure with the leading "~" the sheet
 *  and timeline use for every estimate (never for observed/arrived figures). */
export function approxAmount(n: number): string {
  return `~${formatCurrencyRounded(n)}`;
}

/** "1st", "2nd", "3rd", "21st"… — day-of-month with its English ordinal suffix. */
export function ordinalDay(day: number): string {
  const mod100 = day % 100;
  if (mod100 >= 11 && mod100 <= 13) return `${day}th`;
  switch (day % 10) {
    case 1:
      return `${day}st`;
    case 2:
      return `${day}nd`;
    case 3:
      return `${day}rd`;
    default:
      return `${day}th`;
  }
}

/** "2026-03-01" → "Mar 1". Falls back to the raw string on a malformed date. */
function shortDate(iso: string): string {
  const parts = iso.split("-");
  const m = Number(parts[1]);
  const d = Number(parts[2]);
  const month = MONTH_SHORT[m - 1];
  if (!month || !Number.isFinite(d)) return iso;
  return `${month} ${d}`;
}

/** One rendered charge line inside a sheet section. */
export interface SheetChargeRow {
  /** Stable React key. */
  key: string;
  displayName: string;
  /** Right-aligned amount, or null for the unrecorded "nothing yet" case. */
  amountText: string | null;
  /** The "when" fragment: "usually around the 20th" / "arrived Mar 1" /
   *  "usually bills by the 20th — nothing yet". */
  whenText: string;
  /** Annual price memory ("renewed at $79 last year") or null. */
  priceMemory: string | null;
  /** Arrived rows read as settled — muted, with a check, counted in spent-so-far. */
  arrived: boolean;
  /** Arrived and unrecorded rows both render muted (no committed-sum weight). */
  muted: boolean;
  /** Penciled (upcoming/assumed) rows carry the dashed left rule. */
  penciled: boolean;
}

export interface SheetSection {
  /** Section total, e.g. "~$266". */
  totalText: string;
  rows: SheetChargeRow[];
}

export interface ProjectionBreakdownModel {
  /** Observed spend so far, exact ("$2,584.60"). */
  spentSoFarText: string;
  /** Statement-observed charges awaiting import — null when there are none. */
  assumed: SheetSection | null;
  /** Arrived + upcoming + unrecorded charges, ordered by expected day. */
  committed: SheetSection;
  everyday: {
    amountText: string;
    /** "12 days at about $84/day, from recent months", or null. */
    subLine: string | null;
  };
  /** Projected month-end total, approximate ("~$3,860"). */
  totalText: string;
  /** "Expected by Mar 31". */
  totalLabel: string;
  /** "Mar 31" — the month-end short label. */
  monthEndLabel: string;
}

function toRow(c: ExpectedCharge): SheetChargeRow {
  const arrived = c.status === "arrived";
  const unrecorded = c.status === "unrecorded";
  const penciled = c.status === "upcoming" || c.status === "assumed";

  let whenText: string;
  let amountText: string | null;
  if (arrived) {
    whenText = c.actual_date ? `arrived ${shortDate(c.actual_date)}` : "arrived";
    amountText = formatCurrency(c.actual_amount ?? c.amount_estimate);
  } else if (unrecorded) {
    // Calm quiet-note case — no amount, no danger framing.
    whenText = `usually bills by the ${ordinalDay(c.expected_day)} — nothing yet`;
    amountText = null;
  } else {
    whenText = `usually around the ${ordinalDay(c.expected_day)}`;
    amountText = approxAmount(c.amount_estimate);
  }

  const priceMemory =
    c.cadence === "annual" && c.previous_amount != null
      ? `renewed at ${formatCurrencyRounded(c.previous_amount)} last year`
      : null;

  return {
    key: `${c.merchant}:${c.status}:${c.expected_day}`,
    displayName: c.display_name,
    amountText,
    whenText,
    priceMemory,
    arrived,
    muted: arrived || unrecorded,
    penciled,
  };
}

/** Build the sheet's full row model, or null when the pace has no breakdown
 *  (past months, no history, fail-open). `monthLabel` is "March 2026". */
export function buildProjectionBreakdown(
  pace: MonthPace,
  monthLabel: string
): ProjectionBreakdownModel | null {
  const b = pace.breakdown;
  if (!b) return null;

  const shortMonth = monthLabel.split(" ")[0]?.slice(0, 3) ?? "";
  const monthEndLabel = `${shortMonth} ${pace.days_in_month}`;

  const byDay = [...b.charges].sort((a, z) => a.expected_day - z.expected_day);
  const assumedCharges = byDay.filter((c) => c.status === "assumed");
  const committedCharges = byDay.filter((c) => c.status !== "assumed");

  const assumed: SheetSection | null =
    assumedCharges.length > 0
      ? { totalText: approxAmount(b.assumed_committed), rows: assumedCharges.map(toRow) }
      : null;

  const committed: SheetSection = {
    totalText: approxAmount(b.upcoming_committed),
    rows: committedCharges.map(toRow),
  };

  const everydaySub =
    b.everyday_daily_rate != null && b.days_remaining > 0
      ? `${b.days_remaining} days at about ${formatCurrencyRounded(b.everyday_daily_rate)}/day, from recent months`
      : null;

  // The total is the L5 identity: observed + assumed + upcoming + everyday.
  // The backend guarantees this equals projected_month_total.
  const total = b.observed_mtd + b.assumed_committed + b.upcoming_committed + b.everyday_remainder;

  return {
    spentSoFarText: formatCurrency(b.observed_mtd),
    assumed,
    committed,
    everyday: { amountText: approxAmount(b.everyday_remainder), subLine: everydaySub },
    totalText: approxAmount(total),
    totalLabel: `Expected by ${monthEndLabel}`,
    monthEndLabel,
  };
}
