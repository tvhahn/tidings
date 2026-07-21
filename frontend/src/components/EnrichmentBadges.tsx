import { Tooltip, TooltipContent, TooltipTrigger } from "@/components/ui/tooltip";
import { titleCase } from "@/lib/format";
import { paceSeverity, severityTextClass } from "@/lib/severity";
import type { TransactionContext } from "@/types/api";

interface Props {
  context: TransactionContext | null | undefined;
  category?: string | null | undefined;
}

export function EnrichmentBadges({ context, category }: Props) {
  if (!context) return null;

  const { category_budget_pct, merchant_month_count } = context;

  // Budget: notable-only. Only surface once a category is nearing its budget;
  // an unremarkable "57% of budget" on every row is noise, not signal.
  const showBudget = category_budget_pct != null && category_budget_pct >= 80;
  const severity = category_budget_pct != null ? paceSeverity(category_budget_pct) : "neutral";
  const budgetToneClass = severityTextClass[severity] || "text-muted-foreground";
  const budgetTooltip =
    category_budget_pct != null
      ? category
        ? `${titleCase(category)} is at ${Math.round(category_budget_pct)}% of its monthly budget`
        : `This category is at ${Math.round(category_budget_pct)}% of its monthly budget`
      : "";

  // Frequency: notable-only. "1st visit" fired on nearly every row; drop it and
  // keep only the genuinely repeat visits.
  const showFrequency = merchant_month_count != null && merchant_month_count > 1;

  return (
    <div className="flex items-center text-xs tabular-nums">
      {/* Fixed-width wrappers stay so desktop columns keep alignment even when
          a badge is empty. */}
      <span className="w-28 text-left">
        {showBudget && category_budget_pct != null ? (
          <Tooltip>
            <TooltipTrigger asChild>
              <span className={budgetToneClass}>{Math.round(category_budget_pct)}% of budget</span>
            </TooltipTrigger>
            <TooltipContent>{budgetTooltip}</TooltipContent>
          </Tooltip>
        ) : null}
      </span>
      <span className="w-28 text-left text-muted-foreground">
        {showFrequency ? `${merchant_month_count}× this month` : ""}
      </span>
    </div>
  );
}
