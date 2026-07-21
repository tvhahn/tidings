import { Link } from "react-router-dom";
import { formatCurrency, formatPercent, titleCase } from "@/lib/format";
import type { CategoryDelta } from "@/types/api";

interface MomentumCardProps {
  deltas: CategoryDelta[];
  /** Active month — used to build drill-through links into Transactions. */
  month: string;
}

/** Quiet two-column list of the categories whose spend moved most month over
 *  month. Backed by the `category_deltas` field on the insights context.
 *
 *  Entries where current or previous is 0 are dropped here — those land in
 *  AnomaliesCard as "no activity this month — usually averages …" with
 *  calmer copy, and showing a duplicate "−100%" delta beside that anomaly
 *  was just noise.
 *
 *  Each row links to /transactions filtered to that category for the month. */
export function MomentumCard({ deltas, month }: MomentumCardProps) {
  const visible = deltas.filter(
    (d) => d.current > 0 && d.previous > 0 && Math.abs(d.delta_amount) >= 0.5
  );

  return (
    <div className="rounded-[14px] border border-border bg-card px-5 py-6 sm:px-6">
      <div className="text-[10.5px] font-medium uppercase tracking-[0.06em] text-fg-muted">
        Categories that moved
      </div>
      {visible.length === 0 ? (
        <p className="mt-3 text-[13px] text-fg-muted">Spending held steady this month.</p>
      ) : (
        <ul className="mt-3 divide-y divide-border">
          {visible.map((d) => {
            const sign = d.delta_amount > 0 ? "+" : "";
            return (
              <li key={d.category}>
                <Link
                  to={`/transactions?month=${month}&category=${encodeURIComponent(d.category)}`}
                  className="-mx-2 flex items-baseline justify-between gap-3 rounded-md px-2 py-2 text-[13px] transition-colors hover:bg-muted/40 focus-visible:bg-muted/40 focus-visible:outline-none"
                >
                  <span className="text-fg">{titleCase(d.category)}</span>
                  <span className="text-right tabular-nums">
                    <span className="text-fg">
                      {sign}
                      {formatCurrency(d.delta_amount)}
                    </span>
                    {d.delta_pct !== null && d.delta_pct !== undefined && (
                      <span className="ml-2 text-fg-muted">{formatPercent(d.delta_pct)}</span>
                    )}
                  </span>
                </Link>
              </li>
            );
          })}
        </ul>
      )}
    </div>
  );
}
