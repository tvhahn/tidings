import { ShieldOff } from "lucide-react";
import { Link } from "react-router-dom";
import { useConfig, useUpdateConfig } from "@/hooks/useConfig";

/**
 * Yellow banner shown when the API has no app password set (TOFU mode).
 * Voice is observational, not alarmist — it states what's true and points at
 * the fix without scolding. "Stay passwordless" records the operator's choice
 * (`passwordless_acknowledged`) and retires the banner; the switch in
 * Settings → Access brings it back.
 */
export function SetupBanner() {
  const { data: config } = useConfig();
  const updateConfig = useUpdateConfig();

  // Wait for config before rendering so an acknowledged banner never flashes.
  if (!config || config.passwordless_acknowledged) return null;

  return (
    <div
      role="status"
      className="flex items-center gap-x-3 gap-y-1 flex-wrap bg-status-warning-muted border-b border-status-warning/30 px-4 py-2 text-sm text-status-warning-accent"
    >
      <div className="flex items-center gap-2 min-w-0">
        <ShieldOff className="h-4 w-4 shrink-0" aria-hidden />
        <span className="font-medium">No password set</span>
        <span className="opacity-80 truncate">— anyone on this network can read your data.</span>
      </div>
      <div className="ml-auto flex items-center gap-4">
        <Link
          to="/settings#access"
          className="inline-flex items-center gap-1 font-semibold underline underline-offset-2 hover:no-underline"
        >
          Set a password
          <span aria-hidden>&rarr;</span>
        </Link>
        <button
          type="button"
          onClick={() => updateConfig.mutate({ passwordless_acknowledged: true })}
          disabled={updateConfig.isPending}
          className="text-xs opacity-80 underline underline-offset-2 hover:no-underline disabled:opacity-50"
        >
          Stay passwordless
        </button>
      </div>
    </div>
  );
}
