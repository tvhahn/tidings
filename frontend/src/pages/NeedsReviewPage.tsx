import { MailCheck } from "lucide-react";
import { useState } from "react";
import { toast } from "sonner";
import { PageHeader } from "@/components/PageHeader";
import { ParseFailureList } from "@/components/ParseFailureList";
import { Button } from "@/components/ui/button";
import { Card, CardContent } from "@/components/ui/card";
import { Skeleton } from "@/components/ui/skeleton";
import { useDemoMode } from "@/hooks/useDemoMode";
import { useDismissParseFailure } from "@/hooks/useDismissParseFailure";
import { useParseFailures } from "@/hooks/useParseFailures";
import { useRetryAllParseFailures } from "@/hooks/useRetryAllParseFailures";
import { useRetryParseFailure } from "@/hooks/useRetryParseFailure";
import {
  PARSE_FAILURE_FILTERS,
  deriveRetryAllFilter,
  summarizeRetryAll,
  type ParseFailureFilterKey,
} from "@/lib/parseFailures";

export function NeedsReviewPage() {
  const demo = useDemoMode();
  const [filterKey, setFilterKey] = useState<ParseFailureFilterKey>("needs-review");
  const filter = PARSE_FAILURE_FILTERS.find((f) => f.key === filterKey) ?? PARSE_FAILURE_FILTERS[0];
  const query = useParseFailures(filter.status);
  const failures = query.data?.failures ?? [];

  const retry = useRetryParseFailure();
  const dismiss = useDismissParseFailure();
  const retryAll = useRetryAllParseFailures();
  const [confirmRetryAll, setConfirmRetryAll] = useState(false);

  // Demo mode has no backend to mutate — gate the actions with a calm toast
  // rather than calling the throwing demo twins. Retry returns only a synthetic
  // outcome, so the list refresh that moves a row out of the queue rides on the
  // mutation's query invalidation, not an optimistic patch.
  const handleRetry = (id: string) => {
    if (demo) {
      toast("Actions are disabled in the demo");
      return;
    }
    retry.mutate(id);
  };
  const handleSetAside = (id: string) => {
    if (demo) {
      toast("Actions are disabled in the demo");
      return;
    }
    dismiss.mutate(id);
  };

  // "Retry all" recovers a backlog after a parser lands. Only offered on the
  // active (quarantined) view, when there are at least two rows and they share a
  // single institution or sender domain to filter on.
  const retryAllFilter =
    filterKey === "needs-review" && failures.length >= 2 ? deriveRetryAllFilter(failures) : null;
  const handleRetryAll = () => {
    setConfirmRetryAll(false);
    if (demo) {
      toast("Actions are disabled in the demo");
      return;
    }
    if (!retryAllFilter) return;
    retryAll.mutate(retryAllFilter, {
      onSuccess: (res) => toast(summarizeRetryAll(res)),
      onError: () => toast.error("Couldn't retry the queue — try again"),
    });
  };

  const retryAllAction = retryAllFilter ? (
    confirmRetryAll ? (
      <div className="flex items-center gap-2">
        <Button
          variant="outline"
          size="sm"
          className="h-8 text-xs"
          onClick={handleRetryAll}
          disabled={retryAll.isPending}
        >
          Confirm retry all
        </Button>
        <Button
          variant="ghost"
          size="sm"
          className="h-8 text-xs"
          onClick={() => setConfirmRetryAll(false)}
        >
          Cancel
        </Button>
      </div>
    ) : (
      <Button
        variant="ghost"
        size="sm"
        className="h-8 text-xs text-fg-muted"
        onClick={() => setConfirmRetryAll(true)}
        disabled={retryAll.isPending}
      >
        Retry all
      </Button>
    )
  ) : undefined;

  return (
    <div className="space-y-6">
      <PageHeader
        title="Needs review"
        subtitle="Bank emails Tidings couldn't read yet — retry after a parser update, or set them aside."
        actions={retryAllAction}
      />

      <div role="tablist" aria-label="Status filter" className="flex flex-wrap gap-2">
        {PARSE_FAILURE_FILTERS.map((f) => {
          const active = f.key === filter.key;
          return (
            <button
              key={f.key}
              type="button"
              role="tab"
              aria-selected={active}
              onClick={() => setFilterKey(f.key)}
              className={`rounded-full px-3 py-1.5 text-xs font-medium transition-colors ${
                active
                  ? "bg-surface-accent text-fg"
                  : "bg-surface-muted text-fg-muted hover:text-fg-secondary"
              }`}
            >
              {f.label}
            </button>
          );
        })}
      </div>

      {query.isLoading ? (
        <div className="space-y-3">
          <Skeleton className="h-24 w-full rounded-xl" />
          <Skeleton className="h-24 w-full rounded-xl" />
        </div>
      ) : query.isError ? (
        <Card>
          <CardContent className="p-8 text-center text-sm text-fg-muted">
            Couldn't load the queue — try again.
          </CardContent>
        </Card>
      ) : failures.length === 0 ? (
        <div className="flex flex-col items-center gap-3 py-16 text-fg-muted">
          <MailCheck className="h-12 w-12" />
          <p className="text-sm">{filter.empty}</p>
        </div>
      ) : (
        <ParseFailureList
          failures={failures}
          onRetry={handleRetry}
          onSetAside={handleSetAside}
          retryingId={retry.isPending ? (retry.variables ?? null) : null}
          dismissingId={dismiss.isPending ? (dismiss.variables ?? null) : null}
          busy={retry.isPending || dismiss.isPending}
        />
      )}
    </div>
  );
}
