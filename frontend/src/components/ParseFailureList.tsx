import { ParseFailureRow } from "@/components/ParseFailureRow";
import type { ParseFailureSummary } from "@/types/api";

interface ParseFailureListProps {
  failures: ParseFailureSummary[];
  onRetry: (id: string) => void;
  onSetAside: (id: string) => void;
  /** Id of the row whose retry is in flight, or null. */
  retryingId: string | null;
  /** Id of the row whose set-aside is in flight, or null. */
  dismissingId: string | null;
  /** Any retry/set-aside is in flight — disables every row's actions. */
  busy: boolean;
}

/** Flat list of captured emails, newest first (the server returns them sorted). */
export function ParseFailureList({
  failures,
  onRetry,
  onSetAside,
  retryingId,
  dismissingId,
  busy,
}: ParseFailureListProps) {
  return (
    <div className="space-y-3">
      {failures.map((failure) => (
        <ParseFailureRow
          key={failure.id}
          failure={failure}
          onRetry={onRetry}
          onSetAside={onSetAside}
          retrying={retryingId === failure.id}
          dismissing={dismissingId === failure.id}
          busy={busy}
        />
      ))}
    </div>
  );
}
