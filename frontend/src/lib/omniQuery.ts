import { formatDate, parseYearMonth } from "@/lib/format";
import { normalizeMerchant } from "@/lib/merchantNormalize";
import type { SearchResponse } from "@/types/api";

/**
 * Pure query-parsing + answer-aggregation logic for the Omnibar.
 *
 * This module must stay free of React imports and must never call `new Date()`:
 * every function that needs "now" takes it as an injected argument so the
 * behaviour is fully deterministic under test (see omniQuery.test.ts).
 */

export type OmniIntent =
  | { kind: "category"; name: string }
  | { kind: "month"; month: string } // "YYYY-MM"
  | { kind: "amount"; minAmount?: number; maxAmount?: number; month?: string }
  | { kind: "merchant"; query: string }; // fallback

export interface MerchantAnswer {
  visitCount: number;
  totalAmount: number; // over the searched window
  currentMonthAmount: number;
  dominantCategory: string | null;
  capped: boolean; // SearchResponse.capped — totals are partial
  totalMatching: number; // SearchResponse.total_matching
  merchantName: string | null; // most frequent normalized company, null when no matches
  merchantCount: number; // distinct normalized company names in the result set
}

/** Full + abbreviated English month names, index 0 = January. */
const MONTH_NAMES = [
  "january",
  "february",
  "march",
  "april",
  "may",
  "june",
  "july",
  "august",
  "september",
  "october",
  "november",
  "december",
];

const MONTH_ABBREVS = MONTH_NAMES.map((name) => name.slice(0, 3));

/**
 * Resolve a month token into a `YYYY-MM` string, or `null` if the input is not
 * a recognised month form.
 *
 * Accepted forms (case-insensitive): `march`, `mar`, `mar 2025`, `march 2025`,
 * `2026-03`. A bare month name (no year) resolves to its most recent
 * occurrence: this year when the month is at or before the current month, last
 * year otherwise.
 */
export function parseMonthToken(
  input: string,
  now: { year: number; month: number }
): string | null {
  const trimmed = input.trim().toLowerCase();
  if (!trimmed) return null;

  // Explicit YYYY-MM form.
  const isoMatch = /^(\d{4})-(\d{2})$/.exec(trimmed);
  if (isoMatch) {
    const year = Number(isoMatch[1]);
    const month = Number(isoMatch[2]);
    if (month < 1 || month > 12) return null;
    return `${year}-${String(month).padStart(2, "0")}`;
  }

  // "<month name>" or "<month name> <year>".
  const nameMatch = /^([a-z]+)(?:\s+(\d{4}))?$/.exec(trimmed);
  if (!nameMatch) return null;
  const word = nameMatch[1] ?? "";

  let monthIndex = MONTH_NAMES.indexOf(word);
  if (monthIndex === -1) monthIndex = MONTH_ABBREVS.indexOf(word);
  if (monthIndex === -1) return null;

  const monthNumber = monthIndex + 1; // 1-based

  // Explicit year supplied.
  if (nameMatch[2]) {
    return `${Number(nameMatch[2])}-${String(monthNumber).padStart(2, "0")}`;
  }

  // Bare month name → most recent occurrence relative to `now`.
  const year = monthNumber <= now.month ? now.year : now.year - 1;
  return `${year}-${String(monthNumber).padStart(2, "0")}`;
}

/** Parse the leading amount comparison (`>N` / `> N` / `<N` / `< N`) if present. */
function parseAmountComparison(
  input: string
): { minAmount?: number; maxAmount?: number; rest: string } | null {
  const match = /^([<>])\s*(\d+(?:\.\d+)?)\s*(.*)$/.exec(input.trim());
  if (!match) return null;
  const value = Number(match[2]);
  if (!Number.isFinite(value)) return null;
  const rest = (match[3] ?? "").trim();
  return match[1] === ">" ? { minAmount: value, rest } : { maxAmount: value, rest };
}

/**
 * Classify a raw Omnibar input into an `OmniIntent`.
 *
 * Precedence: amount grammar → month token → category match → merchant
 * fallback. Empty input is the caller's problem (it renders recents); we still
 * return a merchant intent with an empty query so the type stays total.
 *
 * Category matching is case-insensitive: prefix matches first, then substring,
 * with ties broken by the shorter category name.
 */
export function parseOmniQuery(
  input: string,
  ctx: { categories: string[]; now?: { year: number; month: number } }
): OmniIntent {
  // Reference for resolving bare month names. The component passes the real
  // clock; when omitted we use a neutral reference that still resolves explicit
  // `YYYY-MM` / `<month> <year>` forms.
  const now = ctx.now ?? { year: 0, month: 12 };
  const trimmed = input.trim();
  if (!trimmed) return { kind: "merchant", query: "" };

  // Amount grammar takes precedence; a trailing month token narrows the range.
  const amount = parseAmountComparison(trimmed);
  if (amount) {
    const month = amount.rest ? (parseMonthToken(amount.rest, now) ?? undefined) : undefined;
    const intent: OmniIntent = { kind: "amount" };
    if (amount.minAmount !== undefined) intent.minAmount = amount.minAmount;
    if (amount.maxAmount !== undefined) intent.maxAmount = amount.maxAmount;
    if (month !== undefined) intent.month = month;
    return intent;
  }

  // Month token (e.g. "march", "2026-03").
  const month = parseMonthToken(trimmed, now);
  if (month) return { kind: "month", month };

  // Category match: prefix first, then substring, shorter name wins ties.
  const category = matchCategory(trimmed, ctx.categories);
  if (category) return { kind: "category", name: category };

  // Fallback: merchant search.
  return { kind: "merchant", query: trimmed };
}

/** Best category match for `input`, or `null`. Prefix beats substring; ties → shorter name. */
function matchCategory(input: string, categories: string[]): string | null {
  const needle = input.toLowerCase();

  const prefix: string[] = [];
  const substring: string[] = [];
  for (const category of categories) {
    const haystack = category.toLowerCase();
    if (haystack.startsWith(needle)) prefix.push(category);
    else if (haystack.includes(needle)) substring.push(category);
  }

  const pool = prefix.length > 0 ? prefix : substring;
  if (pool.length === 0) return null;

  return pool.reduce((best, current) => (current.length < best.length ? current : best));
}

/** Derive the `YYYY-MM` month of a transaction date string, or `null`. */
function monthOfTransaction(date: string | null): string | null {
  if (!date) return null;
  const iso = formatDate(date, "iso"); // "YYYY-MM-DD" or "—"
  if (iso === "—") return null;
  return iso.slice(0, 7);
}

/**
 * Roll a `SearchResponse` up into the inline answer the Omnibar shows for a
 * merchant query. The API has already filtered the result set, so nothing is
 * skipped here.
 *
 * Visit count is `transactions.length`, or `total_matching` when the response
 * is capped (the list is a partial window of a larger set). The current-month
 * subtotal sums items dated within `currentMonth`. Dominant category is the
 * mode of the non-null `category` field across the result set. Merchant name
 * is the mode of `normalizeMerchant(company)` — variants like "SAFEWAY #1234"
 * and "SAFEWAY #9" collapse to one name — with `merchantCount` reporting how
 * many distinct normalized names the query actually matched.
 */
export function aggregateMerchantAnswer(
  resp: SearchResponse,
  currentMonth: string
): MerchantAnswer {
  const txns = resp.transactions;

  let totalAmount = 0;
  let currentMonthAmount = 0;
  const categoryCounts = new Map<string, number>();
  // Keyed by lowercased normalized name; value keeps first-seen casing + count.
  const merchantCounts = new Map<string, { display: string; count: number }>();

  for (const txn of txns) {
    const amount = txn.amount ?? 0;
    totalAmount += amount;
    if (monthOfTransaction(txn.date) === currentMonth) {
      currentMonthAmount += amount;
    }
    if (txn.category) {
      categoryCounts.set(txn.category, (categoryCounts.get(txn.category) ?? 0) + 1);
    }
    const normalized = normalizeMerchant(txn.company);
    if (normalized) {
      const key = normalized.toLowerCase();
      const entry = merchantCounts.get(key);
      if (entry) entry.count += 1;
      else merchantCounts.set(key, { display: normalized, count: 1 });
    }
  }

  let dominantCategory: string | null = null;
  let topCount = 0;
  for (const [category, count] of categoryCounts) {
    if (count > topCount) {
      topCount = count;
      dominantCategory = category;
    }
  }

  let merchantName: string | null = null;
  let topMerchantCount = 0;
  for (const { display, count } of merchantCounts.values()) {
    if (count > topMerchantCount) {
      topMerchantCount = count;
      merchantName = display;
    }
  }

  return {
    visitCount: resp.capped ? resp.total_matching : txns.length,
    totalAmount,
    currentMonthAmount,
    dominantCategory,
    capped: resp.capped,
    totalMatching: resp.total_matching,
    merchantName,
    merchantCount: merchantCounts.size,
  };
}

/**
 * Days remaining in `month` as of `now`, replicating `JournalPage`'s
 * computation exactly: `Math.max(0, daysInMonth - daysIntoMonth)` where
 * `daysIntoMonth` is today's day-of-month for the current month, the full
 * month length for a past month, and 0 for a future month.
 *
 * `now` is injected (a `YYYY-MM-DD` string, as `JournalPage` derives from the
 * configured timezone) so the function never reads the clock itself.
 */
export function daysRemainingInMonth(now: { todayLocal: string }, month: string): number {
  const [y, m] = parseYearMonth(month);
  const daysInMonth = new Date(y, m, 0).getDate();
  const todayMonth = now.todayLocal.slice(0, 7);
  const daysIntoMonth =
    todayMonth === month
      ? parseInt(now.todayLocal.slice(-2), 10)
      : todayMonth > month
        ? daysInMonth
        : 0;
  return Math.max(0, daysInMonth - daysIntoMonth);
}
