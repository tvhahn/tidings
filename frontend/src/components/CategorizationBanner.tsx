import { useQuery } from "@tanstack/react-query";
import { Tag } from "lucide-react";
import { useState } from "react";
import { queries } from "@/lib/queryConfigs";
import type { HealthStatus } from "@/types/api";

// Lead-in clauses keyed by the backend's ai_last_error_reason. Naming the cause
// tells the operator what to do (top up quota, fix the key) without scolding.
// Unmapped reasons (api_error, codex_*) fall back to the bare effect sentence.
const REASON_LEAD: Record<string, string> = {
  quota_exceeded: "the OpenAI quota is used up, so ",
  auth_error: "the OpenAI key was rejected, so ",
  rate_limited: "OpenAI is rate-limiting requests, so ",
};

/**
 * Calm banner shown when the backend reports AI categorization is degraded —
 * provider/transport errors (e.g. an exhausted OpenAI quota) are filing new
 * transactions as Miscellaneous instead of failing loudly. Observational, not
 * alarmist; dismissible for the session. The caller hides it in demo mode.
 */
export function CategorizationBanner() {
  const { data: health } = useQuery<HealthStatus>(queries.health());
  const [dismissed, setDismissed] = useState(false);

  if (dismissed || health?.ai_categorization_status !== "degraded") return null;

  const lead = REASON_LEAD[health.ai_last_error_reason ?? ""] ?? "";

  return (
    <div
      role="status"
      className="flex items-center gap-x-3 gap-y-1 flex-wrap bg-status-warning-muted border-b border-status-warning/30 px-4 py-2 text-sm text-status-warning-accent"
    >
      <div className="flex items-center gap-2 min-w-0">
        <Tag className="h-4 w-4 shrink-0" aria-hidden />
        <span className="font-medium">AI categorization is unavailable</span>
        <span className="opacity-80">
          — {lead}new transactions are filed as Miscellaneous for now.
        </span>
      </div>
      <button
        type="button"
        onClick={() => setDismissed(true)}
        className="ml-auto font-semibold underline underline-offset-2 hover:no-underline"
      >
        Dismiss
      </button>
    </div>
  );
}
