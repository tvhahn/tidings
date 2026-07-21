import { Link } from "react-router-dom";
import { formatCurrency, shiftMonth, titleCase } from "@/lib/format";
import type { MerchantRecord } from "@/types/api";

interface Props {
  merchants: MerchantRecord[];
  month: string;
  monthsAnalyzed: number;
}

const TYPE_LABEL: Record<string, string> = {
  fixed: "fixed",
  variable: "variable",
  lumpy: "lumpy",
  none: "none",
};

function merchantLinkTo(company: string, month: string, monthsAnalyzed: number): string {
  const from = shiftMonth(month, -(monthsAnalyzed - 1));
  const params = new URLSearchParams({ q: company, from, to: month, month });
  return `/transactions?${params.toString()}`;
}

export function RecurringMerchantsList({ merchants, month, monthsAnalyzed }: Props) {
  const recurring = merchants.filter((m) => m.is_recurring);
  const fixed = recurring.filter((m) => m.frequency_type === "fixed");
  const variable = recurring.filter((m) => m.frequency_type === "variable");

  return (
    <div className="rounded-[14px] border border-border bg-card px-5 py-6 sm:px-6">
      <div className="text-[10.5px] font-medium uppercase tracking-[0.06em] text-fg-muted">
        Recurring merchants
      </div>
      {recurring.length === 0 ? (
        <p className="mt-3 text-[13px] text-fg-muted">
          Still gathering history — recurring detection needs about six months of data.
        </p>
      ) : (
        <div className="mt-3 space-y-5">
          {fixed.length > 0 && (
            <Section
              title="Fixed (subscriptions and bills)"
              rows={fixed}
              month={month}
              monthsAnalyzed={monthsAnalyzed}
            />
          )}
          {variable.length > 0 && (
            <Section
              title="Variable (regular but uneven)"
              rows={variable}
              month={month}
              monthsAnalyzed={monthsAnalyzed}
            />
          )}
        </div>
      )}
    </div>
  );
}

function Section({
  title,
  rows,
  month,
  monthsAnalyzed,
}: {
  title: string;
  rows: MerchantRecord[];
  month: string;
  monthsAnalyzed: number;
}) {
  return (
    <div>
      <div className="text-[11.5px] text-fg-muted">{title}</div>
      <ul className="mt-2 divide-y divide-border">
        {rows.map((m) => (
          <li
            key={m.company}
            className="grid grid-cols-[1fr_auto_auto] items-baseline gap-3 py-2 text-[13px]"
          >
            <Link
              to={merchantLinkTo(m.company, month, monthsAnalyzed)}
              className="truncate text-fg hover:underline"
            >
              {titleCase(m.company)}
            </Link>
            <span className="text-fg-muted">{m.category}</span>
            <span className="text-right tabular-nums text-fg">
              {formatCurrency(m.avg_amount)}/mo
              <span className="ml-2 text-fg-muted">{TYPE_LABEL[m.frequency_type] ?? ""}</span>
            </span>
          </li>
        ))}
      </ul>
    </div>
  );
}
