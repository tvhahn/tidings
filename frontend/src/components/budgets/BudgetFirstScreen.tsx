import { useCategoryGroups } from "@/hooks/useCategoryGroups";
import { useChartTone } from "@/hooks/useChartTone";
import { getGroupColor } from "@/lib/categoryGroups";
import { BUDGET_TICK_PCT, budgetHero, groupTiles, splitCents, TILE_CARD } from "@/lib/firstScreen";
import { cn } from "@/lib/utils";
import type { BudgetStatusResponse } from "@/types/api";

/** A Budgets bar: ink up to the expected mark, calm red past it, and a tick
 *  where "expected by now" falls — the same place on every bar. */
function BudgetBar({
  bar,
  hero,
  label,
}: {
  bar: { fillPct: number; overPct: number };
  hero?: boolean;
  label?: string;
}) {
  return (
    <div
      role={label ? "img" : undefined}
      aria-label={label}
      aria-hidden={label ? undefined : true}
      className={cn("relative rounded-full bg-pace-track", hero ? "mt-[18px] h-1.5" : "mt-2.5 h-1")}
    >
      <span
        className={cn(
          "absolute inset-y-0 left-0 bg-meter-fill",
          bar.overPct > 0 ? "rounded-l-full" : "rounded-full"
        )}
        style={{ width: `${bar.fillPct}%` }}
      />
      {bar.overPct > 0 && (
        <span
          className="absolute inset-y-0 rounded-r-full bg-status-danger-calm"
          style={{ left: `${BUDGET_TICK_PCT}%`, width: `${bar.overPct}%` }}
        />
      )}
      <span
        className={cn(
          "absolute -ml-px w-0.5 rounded-[1px] bg-fg shadow-[0_0_0_1.5px_var(--card)]",
          hero ? "-top-1 h-3.5" : "-top-[3px] h-2.5"
        )}
        style={{ left: `${BUDGET_TICK_PCT}%` }}
      />
    </div>
  );
}

/** N8.2 — Budgets opens the way the Journal does: the spent figure for the
 *  year, one sentence against the pace, one bar, then a tile per group. */
export function BudgetFirstScreen({ status }: { status: BudgetStatusResponse }) {
  const hero = budgetHero(status);
  const tiles = groupTiles(status);
  const { groups: categoryGroups } = useCategoryGroups();
  const tone = useChartTone();
  const { whole, cents } = splitCents(hero.spent);

  return (
    <div className="grid grid-cols-2 gap-3 lg:grid-cols-4">
      <div className={cn(TILE_CARD, "col-span-2 px-5 pb-4 pt-5 lg:col-span-4")}>
        <div className="mb-2 text-meta font-medium text-fg-muted">{hero.eyebrow}</div>
        <div className="t-display leading-none text-fg tabular-nums">
          {whole}
          <span className="text-[0.65em] font-medium text-fg-muted">.{cents}</span>
        </div>
        <p className="t-prose mt-2.5 text-balance text-fg-secondary">{hero.sentence}</p>
        <BudgetBar bar={hero.bar} hero label={hero.ariaLabel} />
        <div className="relative mt-2.5 h-4 text-xs text-fg-muted tabular-nums" aria-hidden="true">
          <span
            className="absolute top-0 -translate-x-1/2 whitespace-nowrap"
            style={{ left: `${BUDGET_TICK_PCT}%` }}
          >
            {hero.key}
          </span>
        </div>
      </div>

      {tiles.map((t) => (
        <div key={t.name} className={cn(TILE_CARD, "p-4", t.wide && "col-span-2")}>
          <div className="flex items-center gap-2 whitespace-nowrap text-[13px] font-medium leading-[18px] text-fg-2">
            <span
              className="h-2 w-2 shrink-0 rounded-full"
              style={{ backgroundColor: getGroupColor(t.name, categoryGroups, tone) }}
            />
            <span className="truncate">{t.name}</span>
          </div>
          <div className="mt-1 whitespace-nowrap text-[17px] font-semibold leading-6 tracking-[-0.005em] text-fg tabular-nums">
            <span className="font-normal text-fg-secondary">{t.stateWords}</span>
            {t.stateAmount && <> {t.stateAmount}</>}
          </div>
          {t.bar && <BudgetBar bar={t.bar} />}
          <div className="mt-2 text-xs text-fg-muted tabular-nums">{t.caption}</div>
        </div>
      ))}
    </div>
  );
}
