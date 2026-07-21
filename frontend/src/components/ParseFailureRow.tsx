import { Archive, ChevronDown, ChevronRight, Loader2, PenLine, RefreshCw } from "lucide-react";
import { useState } from "react";
import { toast } from "sonner";
import { AddTransactionDialog } from "@/components/AddTransactionDialog";
import { Button } from "@/components/ui/button";
import { Card, CardContent } from "@/components/ui/card";
import { useDemoMode } from "@/hooks/useDemoMode";
import { useParseFailureDetail } from "@/hooks/useParseFailures";
import { formatRelativeTime } from "@/lib/format";
import { failureStageLabel, statusLabel } from "@/lib/parseFailures";
import type { ParseFailureSummary } from "@/types/api";

interface ParseFailureRowProps {
  failure: ParseFailureSummary;
  onRetry: (id: string) => void;
  onSetAside: (id: string) => void;
  /** This row's retry is in flight (drives the spinner). */
  retrying: boolean;
  /** This row's set-aside is in flight (drives the spinner). */
  dismissing: boolean;
  /** Any row's action is in flight — disables every action button so a second
   *  concurrent mutation can't move the spinner to the wrong row. */
  busy: boolean;
}

export function ParseFailureRow({
  failure,
  onRetry,
  onSetAside,
  retrying,
  dismissing,
  busy,
}: ParseFailureRowProps) {
  const demo = useDemoMode();
  const [expanded, setExpanded] = useState(false);
  const [confirmSetAside, setConfirmSetAside] = useState(false);
  const [entering, setEntering] = useState(false);
  // The raw email body is PII — only fetch the detail once the row is expanded
  // or the manual-entry dialog needs the body to transcribe from.
  const detail = useParseFailureDetail(expanded || entering ? failure.id : null);

  const handleEnterManually = () => {
    // Demo has no backend to write to — gate like retry / set aside.
    if (demo) {
      toast("Actions are disabled in the demo");
      return;
    }
    setEntering(true);
  };

  const institution = failure.detected_institution ?? "Unknown bank";
  const subject = failure.subject ?? "(no subject)";
  const status = statusLabel(failure.status);
  const isActive = failure.status === "quarantined";

  return (
    <Card className="border-border">
      <CardContent className="space-y-3 p-4">
        <div className="space-y-1.5">
          <div className="flex flex-wrap items-center gap-2">
            <span className="text-sm font-medium text-fg">{institution}</span>
            <span className="text-xs text-fg-muted">
              received {formatRelativeTime(failure.received_at)}
            </span>
            {status && (
              <span className="inline-flex rounded-full bg-surface-muted px-2 py-0.5 text-xs font-medium text-fg-muted">
                {status}
              </span>
            )}
          </div>
          <p className="truncate text-sm text-fg-secondary">{subject}</p>
          <span className="inline-flex rounded-full bg-surface-muted px-2 py-0.5 text-xs font-medium text-fg-muted">
            {failureStageLabel(failure.failure_stage)}
          </span>
        </div>

        <div className="flex flex-wrap items-center justify-between gap-2">
          <button
            type="button"
            onClick={() => setExpanded((v) => !v)}
            aria-expanded={expanded}
            className="inline-flex items-center gap-1 text-xs text-fg-muted transition-colors hover:text-fg-secondary"
          >
            {expanded ? (
              <ChevronDown className="h-3.5 w-3.5" />
            ) : (
              <ChevronRight className="h-3.5 w-3.5" />
            )}
            {expanded ? "Hide email" : "View email"}
          </button>

          {isActive && (
            <div className="flex items-center gap-1">
              <Button
                variant="ghost"
                size="sm"
                className="h-8 text-xs"
                onClick={() => onRetry(failure.id)}
                disabled={busy}
              >
                {retrying ? (
                  <Loader2 className="mr-1 h-3.5 w-3.5 animate-spin" />
                ) : (
                  <RefreshCw className="mr-1 h-3.5 w-3.5" />
                )}
                Retry
              </Button>
              <Button
                variant="ghost"
                size="sm"
                className="h-8 text-xs"
                onClick={handleEnterManually}
                disabled={busy}
              >
                <PenLine className="mr-1 h-3.5 w-3.5" />
                Enter manually
              </Button>
              {confirmSetAside ? (
                <>
                  <Button
                    variant="outline"
                    size="sm"
                    className="h-8 text-xs"
                    onClick={() => {
                      onSetAside(failure.id);
                      setConfirmSetAside(false);
                    }}
                    disabled={busy}
                  >
                    {dismissing && <Loader2 className="mr-1 h-3.5 w-3.5 animate-spin" />}
                    Confirm
                  </Button>
                  <Button
                    variant="ghost"
                    size="sm"
                    className="h-8 text-xs"
                    onClick={() => setConfirmSetAside(false)}
                  >
                    Cancel
                  </Button>
                </>
              ) : (
                <Button
                  variant="ghost"
                  size="sm"
                  className="h-8 text-xs text-fg-muted"
                  onClick={() => setConfirmSetAside(true)}
                  disabled={busy}
                >
                  <Archive className="mr-1 h-3.5 w-3.5" />
                  Set aside
                </Button>
              )}
            </div>
          )}
        </div>

        {expanded && (
          <div className="rounded-md border border-border bg-surface-muted/50 p-3">
            {detail.isLoading ? (
              <div className="flex items-center gap-2 text-xs text-fg-muted">
                <Loader2 className="h-3.5 w-3.5 animate-spin" />
                Loading email…
              </div>
            ) : detail.isError ? (
              <p className="text-xs text-fg-muted">Couldn't load the email — try again.</p>
            ) : detail.data?.body ? (
              <pre className="max-h-72 overflow-auto whitespace-pre-wrap break-words font-mono text-xs text-fg-secondary">
                {detail.data.body}
              </pre>
            ) : (
              <p className="text-xs text-fg-muted">No email body was stored.</p>
            )}
          </div>
        )}

        {/* Deep-link into the shared add-transaction dialog, prefilled with the
         *  detected bank and the email body to transcribe from. Only mounted
         *  while open so the body fetch and form state reset between entries. */}
        {entering && (
          <AddTransactionDialog
            open={entering}
            onOpenChange={setEntering}
            resolveFailure={{
              id: failure.id,
              institution: failure.detected_institution,
              emailBody: detail.data?.body ?? "",
              emailLoading: detail.isLoading,
            }}
          />
        )}
      </CardContent>
    </Card>
  );
}
