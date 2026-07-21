import { DEMO_MONTH, DEMO_NOW_ISO, DEMO_TODAY, DEMO_YEAR } from "./demoConstants";

export function formatCurrency(amount: number | null): string {
  if (amount == null) return "—";
  // U+2212 minus (not the ASCII hyphen Intl emits) — matches formatVariance
  // and formatPercent so negative amounts read consistently everywhere.
  return new Intl.NumberFormat("en-CA", {
    style: "currency",
    currency: "CAD",
  })
    .format(amount)
    .replace(/^-/, "−");
}

/** Zero renders as an em dash (empty-cell convention in the finance tables),
 * everything else falls through to `formatCurrency`. Shared by the income
 * statement and the budget table. */
export function formatCurrencyZeroDash(n: number): string {
  if (n === 0) return "—";
  return formatCurrency(n);
}

/** Whole-dollar currency (no cents) for the budget editor's compact columns.
 * `null` renders as the "-" placeholder; negatives use the house U+2212 minus
 * (not the ASCII hyphen `toLocaleString` emits). */
export function formatCurrencyRounded(n: number | null): string {
  if (n == null) return "-";
  return `$${Math.round(n).toLocaleString().replace(/^-/, "−")}`;
}

/** Abbreviated English month names, index 0 = January. */
export const MONTH_SHORT = [
  "Jan",
  "Feb",
  "Mar",
  "Apr",
  "May",
  "Jun",
  "Jul",
  "Aug",
  "Sep",
  "Oct",
  "Nov",
  "Dec",
];

/** Full English month names, index 0 = January. */
export const MONTH_LONG = [
  "January",
  "February",
  "March",
  "April",
  "May",
  "June",
  "July",
  "August",
  "September",
  "October",
  "November",
  "December",
];

export type DateFormat = "medium" | "dmy" | "iso" | "legacy";

export function formatDate(dateStr: string | null, fmt: DateFormat = "medium"): string {
  if (!dateStr) return "—";
  // Date comes as "MM/DD/YYYY HH:MM PDT/PST"
  const datePart = dateStr.split(" ")[0];
  if (!datePart) return "—";
  if (fmt === "legacy") return datePart;
  const [mm, dd, yyyy] = datePart.split("/").map(Number);
  if (!mm || !dd || !yyyy) return datePart;
  const d = new Date(yyyy, mm - 1, dd);
  if (fmt === "iso") {
    return `${yyyy}-${String(mm).padStart(2, "0")}-${String(dd).padStart(2, "0")}`;
  }
  if (fmt === "dmy") {
    return d.toLocaleDateString("en-GB", { year: "numeric", month: "short", day: "numeric" });
  }
  // medium (default)
  return d.toLocaleDateString("en-US", { year: "numeric", month: "short", day: "numeric" });
}

// Short words stay lowercase after the first word — mechanical Title Case
// ("Sports And Recreation") is exactly what category labels shouldn't look like.
const TITLE_CASE_SMALL_WORDS = new Set([
  "a",
  "an",
  "and",
  "at",
  "for",
  "in",
  "of",
  "on",
  "or",
  "the",
  "to",
  "with",
]);

export function titleCase(str: string | null): string {
  if (!str) return "—";
  return str
    .split(/[\s/]+/)
    .map((word, i) => {
      const lower = word.toLowerCase();
      if (i > 0 && TITLE_CASE_SMALL_WORDS.has(lower)) return lower;
      return word.charAt(0).toUpperCase() + lower.slice(1);
    })
    .join(" ");
}

export function currentMonth(): string {
  // Static demo is anchored to a known month that has fixtures; otherwise use
  // today's real month.
  if (import.meta.env.VITE_DEMO_MODE === "true") {
    return DEMO_MONTH;
  }
  const now = new Date();
  const year = now.getFullYear();
  const month = String(now.getMonth() + 1).padStart(2, "0");
  return `${year}-${month}`;
}

/** Today's local calendar date (`YYYY-MM-DD`) in the given IANA timezone.
 *
 * Pinned to the demo world's "today" in demo mode so pace markers,
 * days-remaining math, and "as of" labels stay inside the fixture window.
 */
export function todayLocalISO(timezone?: string): string {
  if (import.meta.env.VITE_DEMO_MODE === "true") {
    return DEMO_TODAY;
  }
  return new Date().toLocaleDateString("en-CA", {
    timeZone: timezone || "America/Los_Angeles",
  });
}

/**
 * Compact relative time for recently-captured items: "just now", "5m ago",
 * "3h ago", "2d ago", then an absolute "Mar 18" once older than a week.
 *
 * Anchored to the demo world's pinned clock in demo mode so fixture timestamps
 * read coherently (a March fixture shows "1d ago", not "3 months ago" when the
 * hosted demo is viewed months later). Pass `nowMs` explicitly to make the
 * function deterministic in tests.
 */
export function formatRelativeTime(iso: string | null, nowMs?: number): string {
  if (!iso) return "—";
  const then = new Date(iso).getTime();
  if (Number.isNaN(then)) return "—";
  const anchor =
    nowMs ??
    (import.meta.env.VITE_DEMO_MODE === "true" ? new Date(DEMO_NOW_ISO).getTime() : Date.now());
  const sec = Math.max(0, Math.floor((anchor - then) / 1000));
  if (sec < 45) return "just now";
  const min = Math.floor(sec / 60);
  if (min < 60) return `${min}m ago`;
  const hr = Math.floor(min / 60);
  if (hr < 24) return `${hr}h ago`;
  const day = Math.floor(hr / 24);
  if (day < 7) return `${day}d ago`;
  return new Date(then).toLocaleDateString("en-US", { month: "short", day: "numeric" });
}

export function formatPercent(value: number): string {
  if (!isFinite(value)) return "N/A";
  const sign = value > 0 ? "+" : value < 0 ? "−" : "";
  return `${sign}${Math.abs(value).toFixed(1)}%`;
}

export function parseYearMonth(yearMonth: string): [number, number] {
  const [y, m] = yearMonth.split("-").map(Number);
  if (y === undefined || m === undefined) {
    throw new Error(`Invalid YYYY-MM string: ${yearMonth}`);
  }
  return [y, m];
}

export function formatMonthLabel(yearMonth: string, showYear = false): string {
  const [y, m] = parseYearMonth(yearMonth);
  const d = new Date(y, m - 1, 1);
  const label = d.toLocaleDateString("en-US", { month: "short" });
  if (showYear) {
    return `${label} '${String(y).slice(2)}`;
  }
  return label;
}

export function formatMonthLabelLong(yearMonth: string): string {
  const [y, m] = parseYearMonth(yearMonth);
  const date = new Date(y, m - 1, 1);
  return date.toLocaleDateString("en-US", { month: "long", year: "numeric" });
}

export function formatVariance(amount: number): string {
  const sign = amount > 0 ? "+" : amount < 0 ? "−" : "";
  return `${sign}${formatCurrency(Math.abs(amount))}`;
}

export function shiftMonth(month: string, delta: number): string {
  const [y, m] = parseYearMonth(month);
  const d = new Date(y, m - 1 + delta, 1);
  const newY = d.getFullYear();
  const newM = String(d.getMonth() + 1).padStart(2, "0");
  return `${newY}-${newM}`;
}

export function currentYear(): number {
  if (import.meta.env.VITE_DEMO_MODE === "true") {
    return DEMO_YEAR;
  }
  return new Date().getFullYear();
}
