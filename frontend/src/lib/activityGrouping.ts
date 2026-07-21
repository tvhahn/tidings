/**
 * Pure transforms for the agent activity feed (settings sub-page).
 *
 * The page keeps only rendering; the grouping and label shaping live here so
 * they stay unit-testable and out of the component tree (see frontend/CLAUDE.md
 * "Pull pure data transformations into src/lib/").
 */
import type { ActivityEntry } from "@/types/api";
import { MONTH_SHORT } from "./format";

// Consecutive writes by the same principal within this window collapse into one
// burst group — "kitchen-agent · 14 changes · yesterday 11:42 pm".
export const BURST_WINDOW_MS = 10 * 60 * 1000;

export interface ActivityGroup {
  /** Stable identity for the principal (kind + id/label), used as a React key. */
  principalKey: string;
  /** Human label for the header — token label, or a fallback. */
  principalLabel: string;
  /** ISO timestamp of the newest entry in the burst. */
  ts: string;
  /** Number of entries in the burst. */
  count: number;
  entries: ActivityEntry[];
}

// A principal is the same actor across entries when its kind and identity match.
// Token principals carry an id; sessions / tofu / dev-bypass do not, so fall
// back to the label and finally the bare kind.
function principalKey(entry: ActivityEntry): string {
  const kind = entry.principal_kind ?? "unknown";
  const id = entry.principal_id ?? entry.principal_label ?? "";
  return `${kind}:${id}`;
}

// Non-token principal kinds are internal vocabulary; show a plain-language
// label instead of the raw enum value in the feed.
const PRINCIPAL_KIND_LABELS: Record<string, string> = {
  tofu: "this device",
  session: "browser session",
  "dev-bypass": "dev bypass",
};

export function principalLabel(entry: ActivityEntry): string {
  // Token principals are named by their token label (e.g. "laptop-claude").
  if (entry.principal_kind === "token") {
    return entry.principal_label ?? entry.principal_id ?? "token";
  }
  if (entry.principal_kind) {
    const mapped = PRINCIPAL_KIND_LABELS[entry.principal_kind];
    if (mapped) return mapped;
  }
  return entry.principal_label ?? entry.principal_id ?? entry.principal_kind ?? "Unknown";
}

/**
 * Group a newest-first list of entries into bursts. A new group starts when the
 * principal changes or the gap to the previous (newer) entry in the current
 * group exceeds {@link BURST_WINDOW_MS}. Input order is preserved (newest
 * first), so `entries[0].ts` is the group's newest timestamp.
 */
export function groupActivity(entries: ActivityEntry[]): ActivityGroup[] {
  const groups: ActivityGroup[] = [];
  for (const entry of entries) {
    const key = principalKey(entry);
    const tsMs = new Date(entry.ts).getTime();
    const current = groups[groups.length - 1];
    const prev = current?.entries[current.entries.length - 1];
    const withinWindow = prev != null && new Date(prev.ts).getTime() - tsMs <= BURST_WINDOW_MS;

    if (current && current.principalKey === key && withinWindow) {
      current.entries.push(entry);
      current.count += 1;
    } else {
      groups.push({
        principalKey: key,
        principalLabel: principalLabel(entry),
        ts: entry.ts,
        count: 1,
        entries: [entry],
      });
    }
  }
  return groups;
}

function formatClock(d: Date): string {
  const h24 = d.getHours();
  const min = d.getMinutes();
  const ampm = h24 < 12 ? "am" : "pm";
  const h12 = h24 % 12 === 0 ? 12 : h24 % 12;
  return `${h12}:${String(min).padStart(2, "0")} ${ampm}`;
}

function startOfDayMs(ms: number): number {
  const d = new Date(ms);
  d.setHours(0, 0, 0, 0);
  return d.getTime();
}

/**
 * Calm, statement-style timestamp for a burst header: "today 3:14 pm",
 * "yesterday 11:42 pm", or "Jun 9, 8:05 am" for older days. `nowMs` is injected
 * so callers (and tests) control the reference clock.
 */
export function formatBurstTimestamp(iso: string, nowMs: number): string {
  const then = new Date(iso);
  const clock = formatClock(then);
  const dayDelta = Math.round((startOfDayMs(nowMs) - startOfDayMs(then.getTime())) / 86_400_000);
  if (dayDelta <= 0) return `today ${clock}`;
  if (dayDelta === 1) return `yesterday ${clock}`;
  return `${MONTH_SHORT[then.getMonth()]} ${then.getDate()}, ${clock}`;
}

/** "14 changes" / "1 change" — plain count, no gamified framing. */
export function formatChangeCount(count: number): string {
  return `${count} ${count === 1 ? "change" : "changes"}`;
}

// The backend summary for a revert is the locked `revert of <id>` form (L8).
// Surface a calm sentence in the title instead of a raw 32-hex id; the raw
// summary stays available in the expanded detail.
const REVERT_SUMMARY_RE = /^revert of [0-9a-f]{32}$/;

/**
 * A short, human title for a single entry: the backend-staged summary when
 * present, otherwise a humanized operation id, falling back to method + path.
 */
export function activityEntryTitle(entry: ActivityEntry): string {
  if (entry.summary) {
    if (REVERT_SUMMARY_RE.test(entry.summary)) return "reverted an earlier change";
    return entry.summary;
  }
  if (entry.operation_id) return humanizeOperationId(entry.operation_id);
  if (entry.method && entry.path) return `${entry.method} ${entry.path}`;
  return "Change";
}

/**
 * Relative time for the feed, unified across the row timestamp and the reverted
 * note: under a minute reads "just now"; from one minute up it is "Nm ago",
 * then "Nh ago", "Nd ago", and finally an absolute short date. `nowMs` is
 * injected so the whole view shares one reference clock.
 */
export function formatActivityRelativeTime(iso: string | null, nowMs: number): string {
  if (!iso) return "—";
  const then = new Date(iso).getTime();
  if (Number.isNaN(then)) return "—";
  const sec = Math.max(0, Math.floor((nowMs - then) / 1000));
  if (sec < 60) return "just now";
  const min = Math.floor(sec / 60);
  if (min < 60) return `${min}m ago`;
  const hr = Math.floor(min / 60);
  if (hr < 24) return `${hr}h ago`;
  const day = Math.floor(hr / 24);
  if (day < 7) return `${day}d ago`;
  const thenDate = new Date(then);
  return `${MONTH_SHORT[thenDate.getMonth()]} ${thenDate.getDate()}`;
}

// camelCase / snake_case operation id -> sentence-case phrase.
// "bulkUpdateTransactionCategory" -> "Bulk update transaction category".
export function humanizeOperationId(operationId: string): string {
  const spaced = operationId
    .replace(/([a-z0-9])([A-Z])/g, "$1 $2")
    .replace(/[_-]+/g, " ")
    .trim();
  if (!spaced) return operationId;
  return spaced.charAt(0).toUpperCase() + spaced.slice(1).toLowerCase();
}
