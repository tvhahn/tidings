import { useQueryClient } from "@tanstack/react-query";
import { useEffect, useRef } from "react";
import { toast } from "sonner";
import { useJournalSummaries } from "@/hooks/useJournalSummaries";
import { useJournalSummaryStatus } from "@/hooks/useJournalSummaryGeneration";
import { queryKeys } from "@/lib/queryConfigs";

/**
 * Orchestrates daily summary state for the journal page.
 *
 * - Fetches saved summaries for the month.
 * - Polls generation status; on running → idle, refetches saved summaries.
 * - Surfaces backend errors as toasts.
 *
 * Generation is no longer auto-triggered on page load. Days without summaries
 * render a "Summarize" button (DayCard); the configurable evening schedule
 * (handled in the backend lifespan) covers the unattended case.
 */
export function useJournalSummariesOrchestrator(month: string) {
  const { data: summaries } = useJournalSummaries(month);
  const { data: genStatus } = useJournalSummaryStatus();
  const queryClient = useQueryClient();

  const prevStatusRef = useRef(genStatus?.status);
  useEffect(() => {
    const prev = prevStatusRef.current;
    const curr = genStatus?.status;
    prevStatusRef.current = curr;
    if (prev === "running" && curr === "idle") {
      queryClient.invalidateQueries({
        queryKey: queryKeys.journalSummaries(month),
      });
    } else if (prev === "running" && curr === "error") {
      toast.error(genStatus?.error || "Summary generation failed");
      queryClient.invalidateQueries({
        queryKey: queryKeys.journalSummaries(month),
      });
    }
  }, [genStatus?.status, genStatus?.error, month, queryClient]);

  return { summaries, genStatus };
}
