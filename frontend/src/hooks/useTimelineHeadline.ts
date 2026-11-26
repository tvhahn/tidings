import type { MonthPace } from "@/lib/projectionBreakdown";
import { usePreferences } from "@/stores/preferences";

/** True when the per-device Timeline headline preference applies: it needs the
 *  commitment-aware breakdown, a budget and a spent share. The Journal uses the
 *  same test to lay the Timeline strip out full width above the feed instead of
 *  putting the spent hero in the tile column. */
export function useTimelineHeadline({
  pace,
  budget,
  spentPct,
}: {
  pace: MonthPace | null;
  budget: number | null;
  spentPct: number | null;
}): boolean {
  const variant = usePreferences((s) => s.headlineVariant);
  return variant === "timeline" && pace?.breakdown != null && budget != null && spentPct != null;
}
