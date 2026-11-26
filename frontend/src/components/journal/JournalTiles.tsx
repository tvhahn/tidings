import {
  type CeilingTile,
  chargeDayLabel,
  splitCents,
  TILE_CARD,
  upcomingCharges,
} from "@/lib/firstScreen";
import { formatCurrency } from "@/lib/format";
import type { MonthPaceBreakdown } from "@/lib/projectionBreakdown";
import { cn } from "@/lib/utils";

/** A figure tile: a label, one figure with muted cents, one caption. When
 *  `onOpen` is given the whole tile is a button. */
function FigureTile({
  tile,
  wide,
  onOpen,
  openLabel,
}: {
  tile: CeilingTile;
  wide: boolean;
  onOpen?: (() => void) | null | undefined;
  openLabel?: string | undefined;
}) {
  const { whole, cents } = splitCents(tile.amount);
  const body = (
    <>
      <div className="text-xs font-medium text-fg-muted">{tile.label}</div>
      <div className="mt-1 whitespace-nowrap text-[22px] font-semibold leading-7 tracking-[-0.01em] text-fg tabular-nums">
        {whole}
        <span className="font-medium text-fg-muted">.{cents}</span>
      </div>
      <div className="mt-0.5 text-xs text-fg-muted">{tile.caption}</div>
    </>
  );
  const shell = cn(TILE_CARD, "p-4 text-left", wide && "col-span-2");
  if (onOpen) {
    return (
      <button
        type="button"
        onClick={onOpen}
        aria-label={openLabel}
        className={cn(
          shell,
          "transition-colors hover:bg-accent/40 focus-visible:outline-none focus-visible:ring-1 focus-visible:ring-border-strong"
        )}
      >
        {body}
      </button>
    );
  }
  return <div className={shell}>{body}</div>;
}

export interface JournalTilesProps {
  ceiling: CeilingTile | null;
  stillExpected: CeilingTile | null;
  /** Opens the projection breakdown — the "Still expected" tile's rows. */
  onOpenBreakdown: (() => void) | null;
}

/** N8.2 — the two figure tiles under the spent hero: room below the ceiling
 *  and the regular charges still expected. A lone tile spans the row. */
export function JournalTiles({ ceiling, stillExpected, onOpenBreakdown }: JournalTilesProps) {
  const both = ceiling != null && stillExpected != null;
  return (
    <>
      {ceiling && <FigureTile tile={ceiling} wide={!both} />}
      {stillExpected && (
        <FigureTile
          tile={stillExpected}
          wide={!both}
          onOpen={onOpenBreakdown}
          openLabel={`${formatCurrency(stillExpected.amount)} still expected from ${stillExpected.caption} — open the breakdown`}
        />
      )}
    </>
  );
}

/** Desktop rail only — the regular charges still to come this month, by day.
 *  Amounts are estimates from earlier months. */
export function UpcomingChargesCard({
  month,
  breakdown,
}: {
  month: string;
  breakdown: MonthPaceBreakdown;
}) {
  const rows = upcomingCharges(breakdown);
  if (rows.length === 0) return null;
  return (
    <section
      aria-label="Regular charges to come"
      className={cn(TILE_CARD, "col-span-2 px-4 pb-2 pt-4")}
    >
      <div className="flex justify-between pb-2.5 text-xs font-medium text-fg-muted">
        <h2>Regular charges to come</h2>
        <span>estimates</span>
      </div>
      <ul>
        {rows.map((c) => (
          <li
            key={`${c.merchant}:${c.expected_day}`}
            className="grid h-[34px] grid-cols-[48px_minmax(0,1fr)_auto] items-center gap-x-1.5 whitespace-nowrap border-t border-border/60 text-[13px]"
          >
            <span className="text-fg-muted">{chargeDayLabel(month, c.expected_day)}</span>
            <span className="truncate text-fg">{c.display_name}</span>
            <span className="text-right font-medium tabular-nums">
              {formatCurrency(c.amount_estimate)}
            </span>
          </li>
        ))}
      </ul>
    </section>
  );
}
