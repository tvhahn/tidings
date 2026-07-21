import { RefreshCw } from "lucide-react";
import { ApiError } from "@/lib/apiError";

interface QueryErrorNoticeProps {
  error: unknown;
  /** Re-runs the failed query (pass the hook's `refetch`). */
  onRetry?: () => void;
  /** Surface-specific guidance shown when the error carries no useful message. */
  fallback?: string;
}

/**
 * Calm error card for a failed page-level query — the answer to "is this an
 * empty month, or is the server down?". Pages previously rendered nothing on
 * a fetch failure (only `isLoading` and `data &&` branches), which left the
 * default route blank when the backend died.
 */
export function QueryErrorNotice({ error, onRetry, fallback }: QueryErrorNoticeProps) {
  const message =
    error instanceof ApiError
      ? error.message
      : (fallback ?? "The server didn't respond. Check that the backend is running, then retry.");
  return (
    <div className="rounded-[var(--radius-tidings-md)] border border-status-danger-calm/30 bg-status-danger-calm/[0.025] px-5 py-5">
      {/* Sentence-case heading, not an uppercase eyebrow — data eyebrows are
          reserved for labels over display amounts (docs/brand/voice.md). */}
      <p className="text-sm font-medium text-fg">Couldn&apos;t load this page</p>
      <p className="mt-1 text-small text-status-danger-calm-text">{message}</p>
      {onRetry && (
        <button
          onClick={onRetry}
          className="mt-3 inline-flex items-center gap-1.5 rounded-md border px-3 py-1.5 text-sm font-medium hover:bg-accent/50"
        >
          <RefreshCw className="h-3.5 w-3.5" aria-hidden />
          Retry
        </button>
      )}
    </div>
  );
}
