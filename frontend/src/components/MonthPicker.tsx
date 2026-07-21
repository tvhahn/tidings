import { useQuery, useQueryClient } from "@tanstack/react-query";
import { Calendar, ChevronLeft, ChevronRight, Loader2, RotateCw } from "lucide-react";
import { useEffect, useRef, useState } from "react";
import { Link } from "react-router-dom";
import { MonthGrid } from "@/components/MonthGrid";
import { Button } from "@/components/ui/button";
import { Popover, PopoverContent, PopoverTrigger } from "@/components/ui/popover";
import { Tooltip, TooltipContent, TooltipTrigger } from "@/components/ui/tooltip";
import { isDemoMode } from "@/hooks/useDemoMode";
import { DEMO_MONTH } from "@/lib/demoConstants";
import { formatMonthLabelLong, shiftMonth } from "@/lib/format";
import { queries } from "@/lib/queryConfigs";
import { cn } from "@/lib/utils";
import { useFreshness } from "@/stores/freshness";
import type { HealthStatus } from "@/types/api";

interface MonthPickerProps {
  month: string; // "YYYY-MM"
  onChange: (month: string) => void;
  loading?: boolean;
  /** Warm the given month's caches on hover / arrow-focus. Defaults to warming
   *  the `transactions-combined` cache; pass a page-specific warmer (e.g. the
   *  Journal's) so hovering Prev/Next preloads the data that page actually uses. */
  onPrefetch?: (target: string) => void;
}

const AGE_FADE_MS = 5 * 60_000;
const PULSE_DURATION_MS = 2000;

function formatAgo(ms: number): string {
  const sec = Math.floor(ms / 1000);
  if (sec < 5) return "just now";
  if (sec < 60) return `${sec}s ago`;
  const min = Math.floor(sec / 60);
  if (min < 60) return `${min}m ago`;
  const hr = Math.floor(min / 60);
  return `${hr}h ago`;
}

function formatAbsolute(ts: number): string {
  return new Date(ts)
    .toLocaleTimeString("en-US", { hour: "numeric", minute: "2-digit", second: "2-digit" })
    .toLowerCase();
}

function formatAge(seconds: number | null | undefined): string {
  if (seconds == null) return "never";
  if (seconds < 60) return `${seconds}s`;
  const m = Math.floor(seconds / 60);
  if (m < 60) return `${m}m`;
  const h = Math.floor(m / 60);
  if (h < 24) return `${h}h`;
  const d = Math.floor(h / 24);
  return `${d}d`;
}

function formatBackend(backend: string | undefined): string {
  if (!backend) return "—";
  if (backend === "sqlite") return "SQLite";
  if (backend === "dynamodb") return "DynamoDB";
  return backend;
}

/**
 * Small publication-dot rendered inside the MonthPicker trigger. It sits to
 * the left of the month label and carries two signals simultaneously:
 *
 * 1. Freshness (from ``useFreshness``) — color cycles brand → brand/60 →
 *    muted as time passes since the last sync; a ping ring fires for 2s on
 *    each probe-detected invalidation.
 * 2. Backend health (from the ``/health`` query) — when the backend reports
 *    ``stale`` (IMAP dead >30 min OR no transaction parsed in 14 days) the
 *    dot tint overrides freshness with status-danger and a calm ``animate-
 *    pulse`` runs in the background. ``degraded`` (SQLite-only poller lag, or
 *    one or more quiet institutions) tints the dot with the softer
 *    status-warning token — no anim; stale still wins the tint.
 *
 * The dot isn't a separate button (would nest inside the picker trigger);
 * the refresh action lives in the picker popover header.
 */
function SyncDot({ health }: { health: HealthStatus | undefined }) {
  const lastSyncAt = useFreshness((s) => s.lastSyncAt);
  const pulseToken = useFreshness((s) => s.pulseToken);

  const [now, setNow] = useState(() => Date.now());
  useEffect(() => {
    const id = window.setInterval(() => setNow(Date.now()), 10_000);
    return () => window.clearInterval(id);
  }, []);

  const [pulsing, setPulsing] = useState(false);
  useEffect(() => {
    if (!pulseToken) return;
    setPulsing(true);
    const id = window.setTimeout(() => setPulsing(false), PULSE_DURATION_MS);
    return () => window.clearTimeout(id);
  }, [pulseToken]);

  const isStale = health?.status === "stale";
  const isDegraded = health?.status === "degraded";

  if (lastSyncAt == null && !isStale && !isDegraded) {
    return <span className="inline-block h-1.5 w-1.5" aria-hidden />;
  }

  const aged = lastSyncAt != null && now - lastSyncAt >= AGE_FADE_MS;
  // stale health wins the tint (over degraded); sync pulse takes precedence in
  // its 2s window. degraded gets the softer status-warning token, distinct from
  // stale's status-danger.
  const dotColor = pulsing
    ? "bg-brand"
    : isStale
      ? "bg-status-danger"
      : isDegraded
        ? "bg-status-warning"
        : aged
          ? "bg-muted-foreground/40"
          : "bg-brand/60";

  // The dot conveys a sync via a transient brand color-fade (below); the former
  // expanding pulse ring was the one attention-grab on a calm page, and redundant
  // with that fade — removed per the UI-slop audit.
  return (
    <span
      className={cn(
        "inline-flex h-1.5 w-1.5 rounded-full transition-colors duration-500",
        dotColor
      )}
      aria-hidden
    />
  );
}

function SyncStatusLine({ health }: { health: HealthStatus | undefined }) {
  const lastSyncAt = useFreshness((s) => s.lastSyncAt);
  const [now, setNow] = useState(() => Date.now());
  useEffect(() => {
    const id = window.setInterval(() => setNow(Date.now()), 10_000);
    return () => window.clearInterval(id);
  }, []);

  const syncPart =
    lastSyncAt == null
      ? null
      : `synced ${formatAgo(now - lastSyncAt)} · ${formatAbsolute(lastSyncAt)}`;

  const healthParts: string[] = [];
  if (health) {
    if (health.last_transaction_age_seconds != null) {
      healthParts.push(`latest tx ${formatAge(health.last_transaction_age_seconds)} ago`);
    }
    healthParts.push(formatBackend(health.backend));
    if (health.status === "degraded") healthParts.push("poller degraded");
    else if (health.status === "stale") healthParts.push("stale");
    if (health.quiet_institutions != null && health.quiet_institutions > 0) {
      healthParts.push(`${health.quiet_institutions} quiet`);
    }
  }

  if (!syncPart && healthParts.length === 0) return null;

  return (
    <span className="tabular-nums">{[syncPart, ...healthParts].filter(Boolean).join(" · ")}</span>
  );
}

export function MonthPicker({ month, onChange, loading, onPrefetch }: MonthPickerProps) {
  const queryClient = useQueryClient();
  const hoverTimer = useRef<ReturnType<typeof setTimeout>>(undefined);
  const [open, setOpen] = useState(false);
  const { data: health } = useQuery<HealthStatus>(queries.health());

  const prefetch = (target: string) => {
    clearTimeout(hoverTimer.current);
    hoverTimer.current = setTimeout(() => {
      if (onPrefetch) {
        onPrefetch(target);
        return;
      }
      queryClient.prefetchQuery(queries.transactionsCombined(target));
    }, 100);
  };

  const cancelPrefetch = () => clearTimeout(hoverTimer.current);

  const handleMonthSelect = (newMonth: string) => {
    onChange(newMonth);
    setOpen(false);
  };

  const handleRefresh = () => {
    queryClient.invalidateQueries();
  };

  return (
    <div className="flex items-center gap-1">
      <Button
        variant="ghost"
        size="icon"
        aria-label="Previous month"
        onClick={() => onChange(shiftMonth(month, -1))}
        onPointerEnter={() => prefetch(shiftMonth(month, -1))}
        onPointerLeave={cancelPrefetch}
      >
        <ChevronLeft className="h-4 w-4" />
      </Button>

      <Popover open={open} onOpenChange={setOpen}>
        <Tooltip>
          <TooltipTrigger asChild>
            <PopoverTrigger asChild>
              <button className="min-w-[140px] inline-flex items-center justify-center gap-2 text-sm font-medium rounded-full border border-border/60 px-3 py-1 hover:bg-accent hover:text-accent-foreground transition-colors cursor-pointer">
                <SyncDot health={health} />
                <span>{formatMonthLabelLong(month)}</span>
                <Calendar className="h-3.5 w-3.5 text-muted-foreground" aria-hidden />
                {loading && (
                  <Loader2 className="inline h-3.5 w-3.5 animate-spin text-muted-foreground" />
                )}
              </button>
            </PopoverTrigger>
          </TooltipTrigger>
          <TooltipContent
            side="top"
            className="rounded-lg border border-border bg-popover px-3 py-2 text-meta text-popover-foreground shadow-md"
          >
            <SyncStatusLine health={health} />
          </TooltipContent>
        </Tooltip>
        <PopoverContent className="w-64 p-3" align="center">
          <div className="mb-2 flex items-center justify-between border-b pb-2">
            <span className="text-meta text-muted-foreground tabular-nums">
              <SyncStatusLine health={health} />
            </span>
            <button
              type="button"
              onClick={handleRefresh}
              className="inline-flex items-center gap-1 rounded px-1.5 py-0.5 text-meta text-muted-foreground hover:text-foreground hover:bg-accent transition-colors"
              title="Refresh now"
            >
              <RotateCw className="h-3 w-3" />
              Refresh
            </button>
          </div>
          {health && health.status !== "ok" && (
            <div className="mb-2">
              <Link
                to="/settings/system"
                onClick={() => setOpen(false)}
                className="text-meta text-muted-foreground underline-offset-2 transition-colors hover:text-foreground hover:underline"
              >
                system status
              </Link>
            </div>
          )}
          <MonthGrid key={String(open)} selectedMonth={month} onSelect={handleMonthSelect} />
        </PopoverContent>
      </Popover>

      <Button
        variant="ghost"
        size="icon"
        aria-label="Next month"
        disabled={isDemoMode() && month >= DEMO_MONTH}
        onClick={() => onChange(shiftMonth(month, 1))}
        onPointerEnter={() => prefetch(shiftMonth(month, 1))}
        onPointerLeave={cancelPrefetch}
      >
        <ChevronRight className="h-4 w-4" />
      </Button>
    </div>
  );
}
