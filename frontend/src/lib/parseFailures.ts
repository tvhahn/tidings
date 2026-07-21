import type {
  ParseFailureStatus,
  ParseFailureSummary,
  RetryAllRequest,
  RetryAllResponse,
} from "@/types/api";

// Human labels for the store-side failure_stage codes (VALID_FAILURE_STAGES in
// src/finance/parse_failure_store_local.py). The raw codes read as jargon and
// are never shown; an unknown code falls back to a calm generic.
const FAILURE_STAGE_LABELS: Record<string, string> = {
  no_parser_match: "Bank not recognized",
  extraction_empty: "No transaction details found",
  ai_extraction_failed: "Couldn't read the details",
  ai_validation_failed: "Details didn't check out",
  db_validation_failed: "Couldn't be saved",
};

/** Human label for a store-side failure_stage code; raw codes are never shown. */
export function failureStageLabel(stage: string): string {
  return FAILURE_STAGE_LABELS[stage] ?? "Couldn't read this email";
}

// Calm labels for the non-active statuses, shown as a muted pill in the "All"
// and "Set aside" views. `quarantined` is the active state — it carries the
// row actions instead of a pill, so it has no label here.
const STATUS_LABELS: Record<string, string> = {
  dismissed: "Set aside",
  recovered: "Recovered",
  retried: "Retried",
};

/** Muted pill label for a non-active status, or null for the active queue. */
export function statusLabel(status: string): string | null {
  return STATUS_LABELS[status] ?? null;
}

/**
 * Segmented status filter for the queue (spec D5). `status: undefined` is the
 * "All" view — the server returns every status, newest first. Each filter
 * carries its own empty-state line so an empty view names what's missing
 * without scolding.
 */
export const PARSE_FAILURE_FILTERS = [
  {
    key: "needs-review",
    label: "Needs review",
    status: "quarantined",
    empty: "Everything from your forwarder parsed cleanly.",
  },
  {
    key: "set-aside",
    label: "Set aside",
    status: "dismissed",
    empty: "Nothing set aside.",
  },
  {
    key: "all",
    label: "All",
    status: undefined,
    empty: "No emails captured for review.",
  },
] as const satisfies readonly {
  key: string;
  label: string;
  status: ParseFailureStatus | undefined;
  empty: string;
}[];

export type ParseFailureFilter = (typeof PARSE_FAILURE_FILTERS)[number];
export type ParseFailureFilterKey = ParseFailureFilter["key"];

// --- "Retry all" derivation (Needs review) ---------------------------------

/** Domain of a sender email, lowercased, or null. */
export function emailDomain(from: string | null | undefined): string | null {
  if (!from || !from.includes("@")) return null;
  const domain = from.split("@").pop()?.trim().replace(/>$/, "").toLowerCase();
  return domain || null;
}

/**
 * Derive a single retry-all filter from the quarantined rows. The filter must
 * cover *every* row, or the "Retry all" affordance would silently retry a
 * subset: the backend matches rows by the filter, so a filter that omits some
 * rows leaves them behind. Prefer one shared institution (only when every row
 * carries it); else one shared sender domain (only when every row resolves to
 * it); else there is no single covering filter and the affordance is hidden
 * (returns null).
 */
export function deriveRetryAllFilter(failures: ParseFailureSummary[]): RetryAllRequest | null {
  if (failures.length === 0) return null;
  // Every row must share one non-null institution for the filter to cover the queue.
  const institution = failures[0]?.detected_institution ?? null;
  if (institution && failures.every((f) => f.detected_institution === institution)) {
    return { institution };
  }
  // Otherwise every row must resolve to one shared sender domain.
  const domain = emailDomain(failures[0]?.from_email);
  if (domain && failures.every((f) => emailDomain(f.from_email) === domain)) {
    return { from_domain: domain };
  }
  return null;
}

/** Calm one-line summary of a bulk-retry outcome (sentence case, no exclamations). */
export function summarizeRetryAll(res: RetryAllResponse): string {
  const emails = res.retried === 1 ? "1 email" : `${res.retried} emails`;
  return `Retried ${emails} — ${res.created} added, ${res.duplicates} already recorded, ${res.still_failing} still need review`;
}
