import { TrendingUp, TrendingDown, ArrowRightLeft, Receipt, Gauge } from "lucide-react";
import type { KeyboardEvent } from "react";
import { buildSummaryCards } from "@/lib/summaryPace";
import type { SummaryCardModel } from "@/lib/summaryPace";
import { cn } from "@/lib/utils";
import type { SummaryComparisonResponse } from "@/types/api";

interface SummaryCardsProps {
  data: SummaryComparisonResponse;
  /** Opens the shared projection breakdown sheet — wired to the "Projected
   *  month end" card when its model is flagged `opensBreakdown` (L12). Absent
   *  in contexts with no sheet; the card then stays non-interactive. */
  onOpenBreakdown?: () => void;
}

const ICONS: Record<SummaryCardModel["icon"], typeof TrendingUp> = {
  up: TrendingUp,
  down: TrendingDown,
  receipt: Receipt,
  transfer: ArrowRightLeft,
  gauge: Gauge,
};

/** Mirrors `.sc` in design_handoff_tidings/design_system/app.css —
 *  hairline-bordered card, `--fg-muted` eyebrow + icon, 20px tabular amount,
 *  11.5px sub. Tone applies to the eyebrow icon only (semantic up/down).
 *  Card content comes from the pure `buildSummaryCards` (L4). */
export function SummaryCards({ data, onOpenBreakdown }: SummaryCardsProps) {
  const cards = buildSummaryCards(data);

  const gridCols = cards.length === 4 ? "lg:grid-cols-4" : "lg:grid-cols-3";

  const handleKeyDown = (e: KeyboardEvent<HTMLDivElement>) => {
    if (e.key === "Enter" || e.key === " ") {
      e.preventDefault();
      onOpenBreakdown?.();
    }
  };

  return (
    <div className={cn("grid grid-cols-2 gap-3", gridCols)}>
      {cards.map((c) => {
        const Icon = ICONS[c.icon];
        const interactive = !!c.opensBreakdown && onOpenBreakdown != null;
        return (
          <div
            key={c.label}
            className={cn(
              "rounded-[12px] border border-border bg-card px-4 py-[14px]",
              interactive &&
                "cursor-pointer transition-colors hover:border-border-strong focus-visible:outline-none focus-visible:ring-1 focus-visible:ring-border-strong"
            )}
            {...(interactive
              ? {
                  role: "button",
                  tabIndex: 0,
                  "aria-label": "Open the projection breakdown",
                  onClick: onOpenBreakdown,
                  onKeyDown: handleKeyDown,
                }
              : {})}
          >
            <div className="flex items-center justify-between text-[11.5px] text-fg-muted">
              <span>{c.label}</span>
              <Icon className={cn("h-3.5 w-3.5", c.tone)} aria-hidden />
            </div>
            <p className="mt-1.5 text-[20px] font-semibold leading-tight tracking-[-0.01em] text-fg tabular-nums">
              {c.value}
            </p>
            {c.sub && <p className="mt-0.5 text-[11.5px] text-fg-secondary">{c.sub}</p>}
          </div>
        );
      })}
    </div>
  );
}
