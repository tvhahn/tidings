import { formatCurrency, titleCase } from "@/lib/format";
import type { MerchantIntelligenceSummary } from "@/types/api";

interface Props {
  summary: MerchantIntelligenceSummary;
}

interface CardProps {
  label: string;
  value: string;
  hint?: string;
}

function StatCard({ label, value, hint }: CardProps) {
  return (
    <div className="rounded-[14px] border border-border bg-card px-5 py-4">
      <div className="text-[10.5px] font-medium uppercase tracking-[0.06em] text-fg-muted">
        {label}
      </div>
      <div className="mt-1 text-[20px] font-semibold leading-tight tracking-[-0.01em] text-fg tabular-nums">
        {value}
      </div>
      {hint && <div className="mt-1 text-[11.5px] text-fg-muted">{hint}</div>}
    </div>
  );
}

export function MerchantSummaryCards({ summary }: Props) {
  return (
    <div className="grid gap-3 sm:grid-cols-2 lg:grid-cols-4">
      <StatCard
        label="Committed"
        value={`${formatCurrency(summary.recurring_burn_rate)}/mo`}
        hint={`${summary.recurring_count} recurring merchant${summary.recurring_count === 1 ? "" : "s"}`}
      />
      <StatCard
        label="Discretionary"
        value={formatCurrency(summary.discretionary_this_month)}
        hint="this month, after committed"
      />
      <StatCard
        label="New this month"
        value={String(summary.new_merchants.length)}
        hint={summary.new_merchants.slice(0, 2).map(titleCase).join(", ") || "none"}
      />
      <StatCard
        label="Stopped"
        value={String(summary.churned_merchants.length)}
        hint={summary.churned_merchants.slice(0, 2).map(titleCase).join(", ") || "none"}
      />
    </div>
  );
}
