import { useQueryClient, type QueryClient } from "@tanstack/react-query";
import { useEffect } from "react";
import { isDemoPrefetchable } from "@/hooks/useDemoMode";
import { shiftMonth } from "@/lib/format";
import { queries } from "@/lib/queryConfigs";

/**
 * Warm one month's Journal caches (the day list + its AI summaries). The
 * existing usePrefetchMonth only warms `transactions-combined`, which the
 * Journal page doesn't consume — hence a Journal-specific warmer.
 *
 * Exported standalone so the MonthPicker's hover/arrow-focus prefetch can warm
 * the *right* caches on the Journal page (see JournalPage's onPrefetch). React
 * Query dedupes in-flight keys and prefetchQuery honors staleTime, so this is a
 * no-op on already-warm months and safe to call on rapid nav.
 */
export function prefetchJournalMonth(queryClient: QueryClient, month: string) {
  // Skip months the static demo has no fixture for (a real fetch would 404).
  if (!isDemoPrefetchable(month)) return;
  void queryClient.prefetchQuery(queries.journal(month));
  void queryClient.prefetchQuery(queries.journalSummaries(month));
}

/**
 * Prefetch the adjacent (±1) months' Journal data whenever the month changes,
 * so a subsequent Prev/Next click fills the day list from cache with no network
 * wait — the "content follows" half of the instant-ack nav.
 */
export function usePrefetchJournalMonth(month: string) {
  const queryClient = useQueryClient();
  useEffect(() => {
    prefetchJournalMonth(queryClient, shiftMonth(month, -1));
    prefetchJournalMonth(queryClient, shiftMonth(month, 1));
  }, [month, queryClient]);
}
