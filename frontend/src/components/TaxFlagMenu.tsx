import { Tag } from "lucide-react";
import { useState } from "react";
import { toast } from "sonner";
import { Popover, PopoverContent, PopoverTrigger } from "@/components/ui/popover";
import { Tooltip, TooltipTrigger, TooltipContent } from "@/components/ui/tooltip";
import { useSetTaxOverride } from "@/hooks/useSetTaxOverride";
import { useTaxLines } from "@/hooks/useTaxLines";
import { useTaxTrackingEnabled } from "@/hooks/useTaxTrackingEnabled";
import { txIdFromComposite } from "@/lib/api";
import { cn } from "@/lib/utils";
import type { Transaction } from "@/types/api";

/**
 * "Flag as tax item" menu for one row. A small Popover listing the tax claim
 * lines; picking one adds this transaction to the tax pack under that line.
 * Add-only / stateless — the row never displays current flag state; managing or
 * removing a flag happens on the Tax page. Shared across the Journal row, the
 * Transactions table cluster (`size="sm"`), and the Transactions mobile card
 * (`size="md"`). Renders nothing when tax tracking is disabled in Settings, so
 * all three call sites are gated from one place.
 */
export function TaxFlagMenu({ txn, size = "sm" }: { txn: Transaction; size?: "sm" | "md" }) {
  const [open, setOpen] = useState(false);
  const taxEnabled = useTaxTrackingEnabled();
  const { data, isLoading } = useTaxLines();
  const setTaxOverride = useSetTaxOverride();
  const txId = txIdFromComposite(txn.forwarded_to, txn.date_file_name);
  const lines = data?.lines ?? [];

  if (!taxEnabled) return null;

  return (
    <Popover open={open} onOpenChange={setOpen}>
      <Tooltip>
        <TooltipTrigger asChild>
          <PopoverTrigger asChild>
            <button
              aria-label="Flag as tax item"
              className={cn(
                "rounded text-muted-foreground hover:text-foreground hover:bg-muted/60 transition-colors focus-visible:outline-none focus-visible:ring-1 focus-visible:ring-border-strong",
                size === "sm" ? "p-0.5" : "p-1"
              )}
            >
              <Tag className="h-4 w-4" />
            </button>
          </PopoverTrigger>
        </TooltipTrigger>
        <TooltipContent>Flag as tax item</TooltipContent>
      </Tooltip>
      <PopoverContent align="end" className="w-auto min-w-44 p-1.5">
        <p className="px-2 py-1 text-xs text-muted-foreground">Add to tax line</p>
        {isLoading ? (
          <p className="px-2 py-1.5 text-xs text-muted-foreground">Loading…</p>
        ) : (
          <div className="flex flex-col">
            {lines.map((line) => (
              <button
                key={line.key}
                onClick={() => {
                  setTaxOverride.mutate(
                    { txId, mode: "include", lineKey: line.key },
                    {
                      onSuccess: () => toast(`Added to ${line.label}`),
                      onError: (err) =>
                        toast(err instanceof Error ? err.message : "Couldn't add to tax pack"),
                    }
                  );
                  setOpen(false);
                }}
                className="rounded px-2 py-1.5 text-left text-sm text-foreground hover:bg-muted/60 transition-colors focus-visible:outline-none focus-visible:ring-1 focus-visible:ring-border-strong"
              >
                {line.label}
              </button>
            ))}
          </div>
        )}
      </PopoverContent>
    </Popover>
  );
}
