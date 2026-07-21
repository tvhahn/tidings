import { Link } from "react-router-dom";
import { titleCase } from "@/lib/format";
import type { CategoryAnomaly } from "@/types/api";

interface AnomaliesCardProps {
  anomalies: CategoryAnomaly[];
  /** Active month — used to build drill-through links into Transactions. */
  month: string;
}

/** Quiet "this month's notable changes" card. Renders the anomaly list as
 *  short observational sentences — never alarmist, never a notification.
 *  Each row links to /transactions filtered to that category for the month. */
export function AnomaliesCard({ anomalies, month }: AnomaliesCardProps) {
  return (
    <div className="rounded-[14px] border border-border bg-card px-5 py-6 sm:px-6">
      <div className="text-[10.5px] font-medium uppercase tracking-[0.06em] text-fg-muted">
        Notable changes
      </div>
      {anomalies.length === 0 ? (
        <p className="mt-3 text-[13px] text-fg-muted">Nothing notable this month.</p>
      ) : (
        <ul className="mt-3 space-y-1">
          {anomalies.map((a) => (
            <li key={a.category}>
              <Link
                to={`/transactions?month=${month}&category=${encodeURIComponent(a.category)}`}
                className="-mx-2 block rounded-md px-2 py-1 text-[13px] leading-relaxed transition-colors hover:bg-muted/40 focus-visible:bg-muted/40 focus-visible:outline-none"
              >
                <span className="font-medium text-fg">{titleCase(a.category)}</span>{" "}
                <span className="text-fg-muted">— {a.reason}.</span>
                {a.annotated_amount > 0 && (
                  <span className="mt-0.5 block text-[11.5px] text-fg-subtle">
                    A note explains part of this.
                  </span>
                )}
              </Link>
            </li>
          ))}
        </ul>
      )}
    </div>
  );
}
