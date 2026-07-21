import { DEMO_MIN_MONTH, DEMO_MONTH } from "@/lib/demoConstants";

export function useDemoMode(): boolean {
  return import.meta.env.VITE_DEMO_MODE === "true";
}

export function isDemoMode(): boolean {
  return import.meta.env.VITE_DEMO_MODE === "true";
}

/**
 * Whether a month is safe to prefetch. The live backend returns an empty month
 * for any date, but the static demo only ships fixtures for
 * DEMO_MIN_MONTH..DEMO_MONTH — prefetching outside that range makes a real
 * request that 404s and logs a console error. Always true outside demo mode.
 */
export function isDemoPrefetchable(month: string): boolean {
  if (!isDemoMode()) return true;
  return month >= DEMO_MIN_MONTH && month <= DEMO_MONTH;
}
