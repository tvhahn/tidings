import { Check } from "lucide-react";
import { Sheet, SheetContent, SheetDescription, SheetTitle } from "@/components/ui/sheet";
import {
  buildProjectionBreakdown,
  type MonthPace,
  type SheetChargeRow,
  type SheetSection,
} from "@/lib/projectionBreakdown";
import { cn } from "@/lib/utils";

/** L12 — the one shared detail surface. Opened from the Journal headline (both
 *  variants) and the Summary pace card; there is no per-item popover and no
 *  nested sheet. Content mirrors the V5 mockup: spent so far, statement-awaiting
 *  charges, still-committed rows, the everyday-spending estimate, and the total.
 *
 *  All figures arrive pre-formatted from `buildProjectionBreakdown` — this file
 *  is a thin renderer. */
export interface ProjectionBreakdownSheetProps {
  open: boolean;
  onOpenChange: (open: boolean) => void;
  /** The current-month pace; `breakdown` is non-null whenever the sheet opens. */
  pace: MonthPace;
  /** Part of the locked props contract; not needed for the sheet's content. */
  budget: number | null;
  /** "March 2026". */
  monthLabel: string;
}

/** A label + right-aligned amount, at section weight. */
function SectionTotal({ label, amount }: { label: string; amount: string }) {
  return (
    <div className="flex items-baseline justify-between gap-3">
      <span className="font-medium text-fg-2">{label}</span>
      <span className="shrink-0 tabular-nums font-medium text-fg-2">{amount}</span>
    </div>
  );
}

function ChargeRow({ row }: { row: SheetChargeRow }) {
  return (
    <div
      className={cn(
        "flex items-baseline justify-between gap-3 py-1",
        row.penciled && "border-l-2 border-dashed border-fg-muted/40 pl-3"
      )}
    >
      <div className="min-w-0">
        <span className={cn("font-medium", row.muted ? "text-fg-muted" : "text-fg-2")}>
          {row.arrived && (
            <Check className="mr-1 inline-block h-3 w-3 align-[-1px] text-status-success" />
          )}
          {row.displayName}
        </span>
        <span className="text-fg-muted"> · {row.whenText}</span>
        {row.priceMemory && <div className="text-meta text-fg-muted">{row.priceMemory}</div>}
      </div>
      {row.amountText && (
        <span
          className={cn("shrink-0 tabular-nums", row.muted ? "text-fg-muted" : "text-fg-secondary")}
        >
          {row.amountText}
        </span>
      )}
    </div>
  );
}

function Rows({ section }: { section: SheetSection }) {
  return (
    <div className="mt-1.5 flex flex-col gap-0.5">
      {section.rows.map((row) => (
        <ChargeRow key={row.key} row={row} />
      ))}
    </div>
  );
}

export function ProjectionBreakdownSheet({
  open,
  onOpenChange,
  pace,
  monthLabel,
}: ProjectionBreakdownSheetProps) {
  const model = buildProjectionBreakdown(pace, monthLabel);

  return (
    <Sheet open={open} onOpenChange={onOpenChange}>
      <SheetContent className="mx-auto max-h-[85vh] max-w-lg overflow-y-auto rounded-t-[var(--radius-tidings-md)]">
        <SheetTitle className="text-base font-medium">
          {model ? `Expected by ${model.monthEndLabel} · how it adds up` : "How it adds up"}
        </SheetTitle>
        <SheetDescription className="sr-only">
          A breakdown of the projected month-end total: spent so far, the charges still committed
          this month, and estimated everyday spending.
        </SheetDescription>

        {model && (
          <div className="mt-2 flex flex-col gap-5 text-small">
            <SectionTotal label="Spent so far" amount={model.spentSoFarText} />

            {model.assumed && (
              <section>
                <SectionTotal label="Awaiting your statement" amount={model.assumed.totalText} />
                <p className="mt-1 text-meta text-fg-muted">
                  These land when your next statement is imported — counted in the projection, not
                  in spent so far.
                </p>
                <Rows section={model.assumed} />
              </section>
            )}

            <section>
              <SectionTotal label="Still committed this month" amount={model.committed.totalText} />
              <Rows section={model.committed} />
            </section>

            <section>
              <SectionTotal
                label="Everyday spending, estimated"
                amount={model.everyday.amountText}
              />
              {model.everyday.subLine && (
                <p className="mt-1 text-meta text-fg-muted">{model.everyday.subLine}</p>
              )}
            </section>

            <div className="flex items-baseline justify-between gap-3 border-t border-border/60 pt-3">
              <span className="font-medium text-fg-2">{model.totalLabel}</span>
              <span className="font-serif text-lg font-semibold tabular-nums text-fg">
                {model.totalText}
              </span>
            </div>

            <p className="text-meta text-fg-muted">
              Estimates come from your own history · arrived rows are counted in &ldquo;spent so
              far&rdquo;, shown here for the story
            </p>
          </div>
        )}
      </SheetContent>
    </Sheet>
  );
}
