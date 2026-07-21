import { AlertTriangle, CheckCircle2, Loader2 } from "lucide-react";
import { useState } from "react";
import { Button } from "@/components/ui/button";
import {
  Dialog,
  DialogContent,
  DialogDescription,
  DialogFooter,
  DialogHeader,
  DialogTitle,
} from "@/components/ui/dialog";
import { cn } from "@/lib/utils";
import type { ImportPreviewResponse, ImportResult, ImportStrategy } from "@/types/api";

type Props = {
  preview: ImportPreviewResponse | null;
  open: boolean;
  onOpenChange: (open: boolean) => void;
  onApply: (strategy: ImportStrategy, applyConfig: boolean) => Promise<ImportResult>;
  onSuccess: (result: ImportResult) => void;
};

type UiStrategy = {
  value: ImportStrategy;
  label: string;
  description: string;
  recommended?: boolean;
};

const STRATEGIES: UiStrategy[] = [
  {
    value: "skip",
    label: "Skip duplicates",
    description: "Leave existing transactions untouched. Only new rows are inserted.",
    recommended: true,
  },
  {
    value: "overwrite",
    label: "Overwrite existing with imported",
    description: "For duplicates, replace the stored row with the one from the file.",
  },
  {
    value: "keep_both",
    label: "Keep both",
    description: "Insert every row as a new record, even when it matches an existing one.",
  },
];

export function ImportPreviewModal({ preview, open, onOpenChange, onApply, onSuccess }: Props) {
  const [strategy, setStrategy] = useState<ImportStrategy>("skip");
  const [applyConfig, setApplyConfig] = useState(true);
  const [isApplying, setIsApplying] = useState(false);
  const [error, setError] = useState<string | null>(null);

  if (!preview) return null;
  const counts = preview.counts;
  const cfg = preview.config ?? null;
  const cfgCount =
    (cfg?.categories_count ?? 0) +
    (cfg?.overrides_count ?? 0) +
    (cfg?.merchant_aliases_count ?? 0) +
    (cfg?.budget_years_count ?? 0);
  const hasConfig = cfgCount > 0;

  const handleApply = async () => {
    setIsApplying(true);
    setError(null);
    try {
      const result = await onApply(strategy, applyConfig);
      onSuccess(result);
      onOpenChange(false);
    } catch (e) {
      setError(e instanceof Error ? e.message : String(e));
    } finally {
      setIsApplying(false);
    }
  };

  return (
    <Dialog open={open} onOpenChange={onOpenChange}>
      <DialogContent className="max-w-xl">
        <DialogHeader>
          <DialogTitle>Import preview</DialogTitle>
          <DialogDescription>
            Review what will be imported from <span className="font-mono">{preview.filename}</span>.
          </DialogDescription>
        </DialogHeader>

        <div className="space-y-5 py-2">
          <section className="rounded-md border bg-muted/30 p-4">
            <h3 className="mb-2 text-sm font-medium">Transactions</h3>
            <ul className="space-y-1 text-sm text-muted-foreground">
              <li className="flex justify-between">
                <span>New rows</span>
                <span className="font-mono text-foreground">{counts.new}</span>
              </li>
              <li className="flex justify-between">
                <span>Duplicates</span>
                <span className="font-mono text-foreground">{counts.duplicates}</span>
              </li>
              <li className="flex justify-between">
                <span>Invalid / skipped</span>
                <span className="font-mono text-foreground">{counts.invalid}</span>
              </li>
            </ul>
          </section>

          {hasConfig && cfg && (
            <section className="rounded-lg border border-status-warning/30 bg-status-warning/[0.04] p-4">
              <div className="mb-2 flex items-start gap-2">
                <AlertTriangle className="mt-0.5 h-4 w-4 text-status-warning" aria-hidden="true" />
                <div>
                  <h3 className="text-sm font-medium">Configuration will be replaced</h3>
                  <p className="text-xs text-muted-foreground">
                    Importing this backup will overwrite your current categories, overrides,
                    merchant aliases, and budgets.
                  </p>
                </div>
              </div>
              <ul className="ml-6 space-y-0.5 text-xs text-muted-foreground">
                {cfg.categories_count != null && <li>{cfg.categories_count} categories</li>}
                {cfg.overrides_count != null && <li>{cfg.overrides_count} overrides</li>}
                {cfg.merchant_aliases_count != null && (
                  <li>{cfg.merchant_aliases_count} merchant aliases</li>
                )}
                {cfg.budget_years_count != null && <li>{cfg.budget_years_count} budget year(s)</li>}
              </ul>
              <label className="mt-3 flex items-center gap-2 text-xs">
                <input
                  type="checkbox"
                  checked={applyConfig}
                  onChange={(e) => setApplyConfig(e.target.checked)}
                />
                Apply configuration changes
              </label>
            </section>
          )}

          <section>
            <h3 className="mb-2 text-sm font-medium">Duplicate strategy</h3>
            <div className="space-y-2">
              {STRATEGIES.map((s) => (
                <label
                  key={s.value}
                  className={cn(
                    "flex cursor-pointer gap-3 rounded-md border p-3 text-sm transition-colors",
                    strategy === s.value
                      ? "border-primary bg-primary/5"
                      : "border-border hover:bg-accent/40"
                  )}
                >
                  <input
                    type="radio"
                    name="strategy"
                    value={s.value}
                    checked={strategy === s.value}
                    onChange={() => setStrategy(s.value)}
                    className="mt-0.5"
                    aria-label={s.label}
                  />
                  <div>
                    <div className="font-medium">
                      {s.label}
                      {s.recommended && (
                        <span className="ml-2 text-xs text-muted-foreground">(recommended)</span>
                      )}
                    </div>
                    <p className="mt-0.5 text-xs text-muted-foreground">{s.description}</p>
                  </div>
                </label>
              ))}
            </div>
          </section>

          {preview.sample_invalid.length > 0 && (
            <section className="rounded-md border border-status-danger/30 bg-status-danger/5 p-4">
              <h3 className="mb-2 text-sm font-medium">
                Invalid rows (first {preview.sample_invalid.length})
              </h3>
              <ul className="space-y-1 text-xs text-muted-foreground">
                {preview.sample_invalid.map((s, i) => (
                  <li key={i}>
                    <span className="font-mono">{s.date ?? "?"}</span> · {s.company ?? "?"} —{" "}
                    <span className="italic">{s.reason ?? "invalid"}</span>
                  </li>
                ))}
              </ul>
            </section>
          )}

          {error && (
            <div className="rounded-md border border-status-danger/40 bg-status-danger/5 p-3 text-xs text-status-danger">
              {error}
            </div>
          )}
        </div>

        <DialogFooter>
          <Button variant="outline" onClick={() => onOpenChange(false)} disabled={isApplying}>
            Cancel
          </Button>
          <Button onClick={handleApply} disabled={isApplying}>
            {isApplying ? (
              <>
                <Loader2 className="mr-2 h-4 w-4 animate-spin" /> Applying…
              </>
            ) : (
              <>
                <CheckCircle2 className="mr-2 h-4 w-4" /> Apply import
              </>
            )}
          </Button>
        </DialogFooter>
      </DialogContent>
    </Dialog>
  );
}
