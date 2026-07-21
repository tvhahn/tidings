import { SettingsSectionHeader } from "@/components/settings/SettingsSectionHeader";
import { Switch } from "@/components/ui/switch";
import { useConfig, useUpdateConfig } from "@/hooks/useConfig";

/**
 * Instance-level toggle for the tax receipts feature. Persists
 * `tax_tracking_enabled` to config; turning it off hides the Tax receipts tab,
 * its `/tax` workspace, and the per-row "Flag as tax item" control on the
 * Transactions and Journal pages. Existing flags are kept and reappear if
 * re-enabled — see `useTaxTrackingEnabled`.
 */
export function TaxTrackingSection() {
  const { data: config } = useConfig();
  const updateConfig = useUpdateConfig();
  const enabled = config?.tax_tracking_enabled ?? true;

  return (
    <section className="space-y-3">
      <SettingsSectionHeader
        title="Features"
        infoHint={{
          label: "About features",
          content:
            "Turn workspace features on or off for this instance. Hiding a feature keeps its data — nothing is deleted, and the feature returns exactly as it was when you turn it back on.",
        }}
      />

      <div className="flex flex-wrap items-center justify-between gap-3 rounded-lg border border-border/50 p-3">
        <div className="min-w-0 flex-1 space-y-0.5">
          <p className="text-sm font-medium">Tax receipts</p>
          <p className="text-xs text-muted-foreground">
            Track transactions against tax claim lines. When on, the Tax receipts tab is available
            and each transaction on the Transactions and Journal pages shows a tag control for
            flagging it. When off, all of that is hidden; any transactions you already flagged are
            kept.
          </p>
        </div>
        <Switch
          checked={enabled}
          onCheckedChange={(next) => updateConfig.mutate({ tax_tracking_enabled: next })}
          disabled={updateConfig.isPending}
          aria-label="Tax receipts"
        />
      </div>
    </section>
  );
}
