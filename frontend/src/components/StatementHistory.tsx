import { FileText, Trash2, RefreshCw, ChevronRight, Loader2, Download } from "lucide-react";
import { useState } from "react";
import { Badge } from "@/components/ui/badge";
import { Button } from "@/components/ui/button";
import { Card, CardContent } from "@/components/ui/card";
import { getStatementDownloadUrl } from "@/lib/api";
import type { StatementSummaryItem } from "@/types/api";

const STATUS_PILL_BASE = "rounded-full px-2 py-0.5 text-xs font-medium";

interface StatementHistoryProps {
  statements: StatementSummaryItem[];
  onSelect: (id: string) => void;
  onReparse: (id: string) => void;
  onDelete: (id: string) => void;
  /** Overrides the default open-the-PDF behaviour (demo mode gates it). */
  onDownload?: (id: string) => void;
  isReparsing?: boolean;
  reparsingId?: string | null;
}

function formatPeriod(start: string | null, end: string | null): string {
  if (!start && !end) return "—";
  const fmt = (d: string) => {
    const date = new Date(d + "T00:00:00");
    return date.toLocaleDateString("en-US", { month: "short", day: "numeric" });
  };
  if (start && end) return `${fmt(start)} – ${fmt(end)}`;
  if (start) return fmt(start);
  if (end) return fmt(end);
  return "";
}

function statusBadge(stmt: StatementSummaryItem) {
  const committed = stmt.imported_count + stmt.enriched_count + stmt.updated_count;
  switch (stmt.status) {
    case "complete":
      if (committed === 0) {
        return (
          <span className={`${STATUS_PILL_BASE} text-fg-muted bg-surface-muted`}>Reviewed</span>
        );
      }
      // Calm gray — reserve --status-success for genuinely-good states.
      return <span className={`${STATUS_PILL_BASE} text-fg-muted bg-surface-muted`}>Complete</span>;
    case "in_progress":
      return <span className={`${STATUS_PILL_BASE} text-fg-2 bg-surface-accent`}>In progress</span>;
    default:
      return (
        <span className={`${STATUS_PILL_BASE} text-fg-muted bg-surface-muted`}>Pending review</span>
      );
  }
}

function parseTimeText(stmt: StatementSummaryItem): string {
  const parts = [`${stmt.total_parsed} parsed`];
  if (stmt.new_count > 0) parts.push(`${stmt.new_count} new`);
  if (stmt.suspected_duplicate_count > 0)
    parts.push(`${stmt.suspected_duplicate_count} suspected dups`);
  if (stmt.matched_count > 0) parts.push(`${stmt.matched_count} matched`);
  return parts.join(" · ");
}

function outcomeText(stmt: StatementSummaryItem): string | null {
  const parts: string[] = [];
  if (stmt.imported_count > 0) parts.push(`${stmt.imported_count} imported`);
  if (stmt.enriched_count > 0) parts.push(`${stmt.enriched_count} enriched`);
  if (stmt.updated_count > 0) parts.push(`${stmt.updated_count} updated`);
  if (stmt.skipped_count > 0) parts.push(`${stmt.skipped_count} skipped`);
  if (stmt.duplicate_count > 0) parts.push(`${stmt.duplicate_count} duplicate`);
  return parts.length > 0 ? parts.join(" · ") : null;
}

export function StatementHistory({
  statements,
  onSelect,
  onReparse,
  onDelete,
  onDownload,
  isReparsing,
  reparsingId,
}: StatementHistoryProps) {
  const [confirmDeleteId, setConfirmDeleteId] = useState<string | null>(null);

  if (statements.length === 0) return null;

  return (
    <div className="space-y-3">
      <h2 className="text-[10.5px] font-medium uppercase tracking-[0.08em] text-fg-muted">
        Upload history
      </h2>
      {statements.map((stmt) => (
        <Card key={stmt.id} className="border-border hover:bg-surface-muted transition-colors">
          <CardContent className="p-4">
            <div className="flex items-center justify-between gap-4">
              <div
                role="button"
                tabIndex={0}
                className="flex items-center gap-3 flex-1 min-w-0 cursor-pointer"
                onClick={() => onSelect(stmt.id)}
                onKeyDown={(e) => {
                  if (e.key === "Enter" || e.key === " ") {
                    e.preventDefault();
                    onSelect(stmt.id);
                  }
                }}
              >
                <FileText className="h-5 w-5 text-muted-foreground shrink-0" />
                <div className="min-w-0 flex-1">
                  <div className="flex items-center gap-2">
                    <span className="text-sm font-medium">
                      {formatPeriod(stmt.period_start, stmt.period_end)}
                    </span>
                    <Badge variant="outline" className="text-xs shrink-0">
                      {stmt.institution}
                    </Badge>
                  </div>
                  <div className="flex items-center gap-3 mt-1">
                    {statusBadge(stmt)}
                    {(() => {
                      const outcome = outcomeText(stmt);
                      const parseTime = parseTimeText(stmt);
                      return outcome ? (
                        <span className="text-xs text-muted-foreground" title={parseTime}>
                          {outcome}
                        </span>
                      ) : (
                        <span className="text-xs text-muted-foreground">{parseTime}</span>
                      );
                    })()}
                  </div>
                  <div className="mt-1 font-mono text-xs text-muted-foreground truncate">
                    {stmt.filename}
                  </div>
                </div>
                <ChevronRight className="h-4 w-4 text-muted-foreground shrink-0" />
              </div>

              <div className="flex items-center gap-1 shrink-0">
                <Button
                  variant="ghost"
                  size="icon"
                  className="h-8 w-8"
                  onClick={(e) => {
                    e.stopPropagation();
                    if (onDownload) {
                      onDownload(stmt.id);
                    } else {
                      window.open(getStatementDownloadUrl(stmt.id), "_blank");
                    }
                  }}
                  title="Download PDF"
                >
                  <Download className="h-4 w-4" />
                </Button>
                <Button
                  variant="ghost"
                  size="icon"
                  className="h-8 w-8"
                  onClick={(e) => {
                    e.stopPropagation();
                    onReparse(stmt.id);
                  }}
                  disabled={isReparsing && reparsingId === stmt.id}
                  title="Re-parse"
                >
                  {isReparsing && reparsingId === stmt.id ? (
                    <Loader2 className="h-4 w-4 animate-spin" />
                  ) : (
                    <RefreshCw className="h-4 w-4" />
                  )}
                </Button>
                {confirmDeleteId === stmt.id ? (
                  <div className="flex items-center gap-1">
                    <Button
                      variant="destructive"
                      size="sm"
                      className="h-8 text-xs"
                      onClick={(e) => {
                        e.stopPropagation();
                        onDelete(stmt.id);
                        setConfirmDeleteId(null);
                      }}
                    >
                      Confirm
                    </Button>
                    <Button
                      variant="ghost"
                      size="sm"
                      className="h-8 text-xs"
                      onClick={(e) => {
                        e.stopPropagation();
                        setConfirmDeleteId(null);
                      }}
                    >
                      Cancel
                    </Button>
                  </div>
                ) : (
                  <Button
                    variant="ghost"
                    size="icon"
                    className="h-8 w-8 text-muted-foreground hover:text-destructive"
                    onClick={(e) => {
                      e.stopPropagation();
                      setConfirmDeleteId(stmt.id);
                    }}
                    title="Delete"
                  >
                    <Trash2 className="h-4 w-4" />
                  </Button>
                )}
              </div>
            </div>
          </CardContent>
        </Card>
      ))}
    </div>
  );
}
