import { ChevronDown } from "lucide-react";
import { useState } from "react";
import { Button } from "@/components/ui/button";
import { activityEntryTitle, formatActivityRelativeTime } from "@/lib/activityGrouping";
import { cn } from "@/lib/utils";
import type { ActivityEntry } from "@/types/api";

interface ActivityEntryRowProps {
  entry: ActivityEntry;
  onRevert: (entry: ActivityEntry) => void;
  /** True while this entry's revert is in flight. */
  reverting: boolean;
  /** A quiet inline note under the row (revert conflict, or the demo guard). */
  note: string | null;
  /** Shared reference clock for relative timestamps across the view. */
  nowMs: number;
}

function ImageBlock({ label, value }: { label: string; value: Record<string, unknown> | null }) {
  if (value === null) return null;
  return (
    <div className="space-y-1">
      <p className="text-[11px] uppercase tracking-[0.08em] text-fg-muted">{label}</p>
      <pre className="overflow-x-auto rounded-md bg-muted/40 px-3 py-2 text-xs text-fg-secondary">
        {Object.keys(value).length === 0 ? "—" : JSON.stringify(value, null, 2)}
      </pre>
    </div>
  );
}

export function ActivityEntryRow({
  entry,
  onRevert,
  reverting,
  note,
  nowMs,
}: ActivityEntryRowProps) {
  const [expanded, setExpanded] = useState(false);
  const [confirming, setConfirming] = useState(false);

  const canRevert = entry.reversible && !entry.reverted_at;
  const secondary = [entry.method, entry.path].filter(Boolean).join(" ");

  return (
    <li className="rounded-lg border border-border/50">
      <div className="flex items-start justify-between gap-3 px-4 py-3">
        <button
          type="button"
          onClick={() => setExpanded((v) => !v)}
          aria-expanded={expanded}
          className="flex min-w-0 flex-1 items-start gap-2 text-left"
        >
          <ChevronDown
            className={cn(
              "mt-0.5 h-4 w-4 shrink-0 text-fg-muted transition-transform",
              expanded && "rotate-180"
            )}
          />
          <span className="min-w-0">
            <span className="block truncate text-sm font-medium">{activityEntryTitle(entry)}</span>
            {secondary && (
              <span className="mt-0.5 block truncate text-xs text-muted-foreground">
                {secondary}
              </span>
            )}
          </span>
        </button>

        <div className="flex shrink-0 flex-col items-end gap-1">
          <span className="text-xs text-muted-foreground tabular-nums">
            {formatActivityRelativeTime(entry.ts, nowMs)}
          </span>
          {entry.reverted_at ? (
            <span className="text-xs text-fg-muted">
              reverted {formatActivityRelativeTime(entry.reverted_at, nowMs)}
            </span>
          ) : canRevert ? (
            confirming ? (
              <div className="flex items-center gap-1">
                <Button
                  variant="outline"
                  size="sm"
                  className="h-7 text-xs"
                  disabled={reverting}
                  onClick={() => {
                    setConfirming(false);
                    onRevert(entry);
                  }}
                >
                  Confirm revert
                </Button>
                <Button
                  variant="ghost"
                  size="sm"
                  className="h-7 text-xs"
                  disabled={reverting}
                  onClick={() => setConfirming(false)}
                >
                  Cancel
                </Button>
              </div>
            ) : (
              <Button
                variant="ghost"
                size="sm"
                className="h-7 text-xs text-fg-muted"
                disabled={reverting}
                onClick={() => setConfirming(true)}
              >
                Revert
              </Button>
            )
          ) : null}
        </div>
      </div>

      {note && <p className="px-4 pb-3 text-xs text-fg-muted">{note}</p>}

      {expanded && (
        <div className="space-y-3 border-t border-border/50 px-4 py-3">
          {entry.before === null && entry.after === null ? (
            <p className="text-xs text-fg-muted">No field-level detail recorded.</p>
          ) : (
            <>
              <ImageBlock label="Before" value={entry.before} />
              <ImageBlock label="After" value={entry.after} />
            </>
          )}
        </div>
      )}
    </li>
  );
}
