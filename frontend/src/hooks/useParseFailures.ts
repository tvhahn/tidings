import { useQuery } from "@tanstack/react-query";
import { queries } from "@/lib/queryConfigs";
import type { ParseFailureStatus } from "@/types/api";

/** The "Needs review" queue. `status` undefined → the full list (the "All" filter). */
export function useParseFailures(status?: ParseFailureStatus) {
  return useQuery(queries.parseFailures(status));
}

/**
 * Lazy per-row detail. The detail endpoint carries the raw email body (PII), so
 * pass `null` until the row is expanded — the query stays disabled until then.
 */
export function useParseFailureDetail(id: string | null) {
  return useQuery(queries.parseFailureDetail(id));
}
