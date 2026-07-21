import { Link } from "react-router-dom";
import { formatCurrency, formatMonthLabel, shiftMonth, titleCase } from "@/lib/format";
import type { MerchantIntelligenceSummary, MerchantRecord } from "@/types/api";

interface Props {
  summary: MerchantIntelligenceSummary;
  merchants: MerchantRecord[];
  /** Window the parent merchants page is showing (current month, lookback). */
  month: string;
  monthsAnalyzed: number;
}

const MAX_NEW_VISIBLE = 10;

function merchantLinkTo(company: string, month: string, monthsAnalyzed: number): string {
  const to = month;
  const from = shiftMonth(month, -(monthsAnalyzed - 1));
  const params = new URLSearchParams({ q: company, from, to, month: to });
  return `/transactions?${params.toString()}`;
}

export function MerchantAlerts({ summary, merchants, month, monthsAnalyzed }: Props) {
  const newOnes = merchants.filter((m) => m.is_new);
  const churned = merchants.filter((m) => m.is_churned);
  const priceChanges = summary.price_changes;
  const empty = newOnes.length + churned.length + priceChanges.length === 0;
  const newVisible = newOnes.slice(0, MAX_NEW_VISIBLE);
  const newOverflow = newOnes.length - newVisible.length;

  return (
    <div className="rounded-[14px] border border-border bg-card px-5 py-6 sm:px-6">
      <div className="text-[10.5px] font-medium uppercase tracking-[0.06em] text-fg-muted">
        Notable changes
      </div>
      {empty ? (
        <p className="mt-3 text-[13px] text-fg-muted">Nothing notable this window.</p>
      ) : (
        <div className="mt-3 space-y-5">
          {priceChanges.length > 0 && (
            <div>
              <div className="text-[11.5px] text-fg-muted">Price changes</div>
              <ul className="mt-2 space-y-1.5">
                {priceChanges.map((p) => (
                  <li key={p.merchant} className="text-[13px] text-fg">
                    <Link
                      to={merchantLinkTo(p.merchant, month, monthsAnalyzed)}
                      className="font-medium hover:underline"
                    >
                      {titleCase(p.merchant)}
                    </Link>
                    <span className="text-fg-muted">
                      {" "}
                      — {formatCurrency(p.old_amount)} → {formatCurrency(p.new_amount)} since{" "}
                      {formatMonthLabel(p.since_month, true)}
                    </span>
                  </li>
                ))}
              </ul>
            </div>
          )}
          {newOnes.length > 0 && (
            <div>
              <div className="text-[11.5px] text-fg-muted">New merchants</div>
              <ul className="mt-2 space-y-1.5">
                {newVisible.map((m) => (
                  <li key={m.company} className="text-[13px] text-fg">
                    <Link
                      to={merchantLinkTo(m.company, month, monthsAnalyzed)}
                      className="font-medium hover:underline"
                    >
                      {titleCase(m.company)}
                    </Link>
                    <span className="text-fg-muted">
                      {" "}
                      — {formatCurrency(m.total)} this window, first appearance
                    </span>
                  </li>
                ))}
                {newOverflow > 0 && (
                  <li className="text-[12px] text-fg-muted">+{newOverflow} more</li>
                )}
              </ul>
            </div>
          )}
          {churned.length > 0 && (
            <div>
              <div className="text-[11.5px] text-fg-muted">Stopped</div>
              <ul className="mt-2 space-y-1.5">
                {churned.map((m) => (
                  <li key={m.company} className="text-[13px] text-fg">
                    <Link
                      to={merchantLinkTo(m.company, month, monthsAnalyzed)}
                      className="font-medium hover:underline"
                    >
                      {titleCase(m.company)}
                    </Link>
                    <span className="text-fg-muted">
                      {" "}
                      — was {formatCurrency(m.avg_amount)}/mo, silent recently
                    </span>
                  </li>
                ))}
              </ul>
            </div>
          )}
        </div>
      )}
    </div>
  );
}
