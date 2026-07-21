import { useQueryClient } from "@tanstack/react-query";
import { useEffect, useRef } from "react";
import { fetchLatestTimestamp } from "@/lib/api";
import { TRANSACTION_DEPENDENT_PREFIXES } from "@/lib/queryConfigs";
import { useFreshness } from "@/stores/freshness";

const POLL_INTERVAL_MS = 30_000;

/**
 * Polls the backend every 30s (only while the tab is visible) for the newest
 * DateFileName and invalidates transaction-dependent React Query caches when
 * it moves forward. Mount exactly once at the app level. The list of
 * invalidated prefixes is `TRANSACTION_DEPENDENT_PREFIXES` from
 * `lib/queryConfigs.ts` — same list used by `invalidateTransactionDependents`.
 */
export function useFreshnessProbe(): void {
  const queryClient = useQueryClient();
  const lastLatestRef = useRef<string | null>(null);
  const setSync = useFreshness((s) => s.setSync);
  const setPolling = useFreshness((s) => s.setPolling);

  useEffect(() => {
    let cancelled = false;
    let intervalId: number | undefined;

    const probe = async () => {
      try {
        const { latest } = await fetchLatestTimestamp();
        if (cancelled) return;
        const previous = lastLatestRef.current;
        const moved = !!latest && !!previous && latest > previous;
        if (moved) {
          for (const prefix of TRANSACTION_DEPENDENT_PREFIXES) {
            queryClient.invalidateQueries({ queryKey: [prefix] });
          }
        }
        // Track the latest seen value even on the first probe so subsequent
        // polls can detect deltas without re-invalidating on mount.
        lastLatestRef.current = latest;
        setSync(latest, moved);
      } catch {
        // Swallow — transient API errors shouldn't crash the dashboard.
      }
    };

    const start = () => {
      if (intervalId !== undefined) return;
      setPolling(true);
      probe();
      intervalId = window.setInterval(probe, POLL_INTERVAL_MS);
    };

    const stop = () => {
      if (intervalId === undefined) return;
      window.clearInterval(intervalId);
      intervalId = undefined;
      setPolling(false);
    };

    const handleVisibility = () => {
      if (document.visibilityState === "visible") start();
      else stop();
    };

    if (document.visibilityState === "visible") start();
    document.addEventListener("visibilitychange", handleVisibility);

    return () => {
      cancelled = true;
      document.removeEventListener("visibilitychange", handleVisibility);
      stop();
    };
  }, [queryClient, setSync, setPolling]);
}
