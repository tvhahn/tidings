import { ChevronDown, ChevronRight } from "lucide-react";
import { useState } from "react";
import { Button } from "@/components/ui/button";
import { Collapsible, CollapsibleContent, CollapsibleTrigger } from "@/components/ui/collapsible";
import { Separator } from "@/components/ui/separator";
import { formatCurrency, titleCase } from "@/lib/format";
import type { UnbudgetedCategory } from "@/types/api";

interface UnbudgetedSectionProps {
  categories: UnbudgetedCategory[];
  onSetBudget: (category: string) => void;
}

export function UnbudgetedSection({ categories, onSetBudget }: UnbudgetedSectionProps) {
  const [open, setOpen] = useState(false);

  if (categories.length === 0) return null;

  const ytdTotal = categories.reduce((sum, c) => sum + c.ytd_spent, 0);
  const sorted = [...categories].sort((a, b) => b.ytd_spent - a.ytd_spent);

  return (
    <Collapsible open={open} onOpenChange={setOpen}>
      <CollapsibleTrigger className="flex w-full items-center gap-2 rounded-xl border border-border/50 bg-muted/20 px-4 py-3 text-left hover:bg-muted/40 transition-colors">
        <span className="text-sm text-muted-foreground">
          {categories.length} unbudgeted categories — {formatCurrency(ytdTotal)} YTD
        </span>
        {open ? (
          <ChevronDown className="ml-auto h-4 w-4 text-muted-foreground" />
        ) : (
          <ChevronRight className="ml-auto h-4 w-4 text-muted-foreground" />
        )}
      </CollapsibleTrigger>
      <CollapsibleContent className="mt-2 space-y-0 rounded-xl border border-border/50 px-4">
        {sorted.map((cat, i) => (
          <div key={cat.category}>
            {i > 0 && <Separator />}
            <div className="flex items-center gap-3 py-2.5">
              <div className="flex-1 min-w-0">
                <div className="flex flex-col gap-0.5 sm:flex-row sm:items-center sm:gap-3">
                  <span className="text-sm">{titleCase(cat.category)}</span>
                  <span className="text-xs text-muted-foreground">
                    {formatCurrency(cat.current_month_spent)} this month
                    {cat.monthly_avg_historical > 0 && (
                      <> (avg {formatCurrency(cat.monthly_avg_historical)}/mo)</>
                    )}
                  </span>
                </div>
              </div>
              <Button
                variant="ghost"
                size="sm"
                className="shrink-0 text-xs"
                onClick={() => onSetBudget(cat.category)}
              >
                Set Budget
              </Button>
            </div>
          </div>
        ))}
      </CollapsibleContent>
    </Collapsible>
  );
}
