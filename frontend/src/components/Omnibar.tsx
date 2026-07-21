import { Clock, Moon, Plus, Search, SlidersHorizontal } from "lucide-react";
import { useEffect, useMemo, useState } from "react";
import { useLocation, useNavigate } from "react-router-dom";
import { CategoryPill } from "@/components/CategoryPill";
import {
  Command,
  CommandEmpty,
  CommandGroup,
  CommandInput,
  CommandItem,
  CommandList,
} from "@/components/ui/command";
import { Dialog, DialogContent, DialogDescription, DialogTitle } from "@/components/ui/dialog";
import { Skeleton } from "@/components/ui/skeleton";
import { useBudgetStatus } from "@/hooks/useBudgetStatus";
import { useCategories } from "@/hooks/useCategories";
import { useConfig } from "@/hooks/useConfig";
import { useDebouncedValue } from "@/hooks/useDebouncedValue";
import { useMonthParam } from "@/hooks/useMonthParam";
import { useNavItems } from "@/hooks/useNavItems";
import { useOmnibarShortcut } from "@/hooks/useOmnibarShortcut";
import { useSummary } from "@/hooks/useSummary";
import { useTransactionSearch } from "@/hooks/useTransactionSearch";
import {
  currentMonth,
  formatCurrency,
  formatMonthLabelLong,
  parseYearMonth,
  shiftMonth,
  titleCase,
  todayLocalISO,
} from "@/lib/format";
import { aggregateMerchantAnswer, daysRemainingInMonth, parseOmniQuery } from "@/lib/omniQuery";
import { useOmnibarStore } from "@/stores/omnibar";
import { useTheme } from "@/stores/theme";
import type { SearchParams } from "@/types/api";

/**
 * Module-level open-request fan-out. The Omnibar owns its own `open` state and
 * is rendered once with no props (per the implementation plan), so Layout's
 * search buttons can't pass a setter down. Instead they call `openOmnibar()`,
 * and the mounted Omnibar subscribes to it. This keeps app state out of
 * `components/ui/` and leaves the Omnibar fully self-contained.
 */
const openListeners = new Set<() => void>();

// Exported alongside the component because the open-bus is intrinsic to the
// Omnibar's "rendered once, no props" contract; a separate module is disallowed
// by this packet's file scope. Only relaxes dev fast-refresh, never runtime.
// eslint-disable-next-line react-refresh/only-export-components
export function openOmnibar(): void {
  for (const listen of openListeners) listen();
}

/** Routes that read `?month=` via `useMonthParam`; on these, a month intent
 *  jumps in place rather than navigating to the journal. */
const MONTH_SCOPED_PATHS = new Set(["/", "/transactions", "/summary", "/insights", "/merchants"]);

export function Omnibar() {
  const [open, setOpen] = useState(false);
  const [input, setInput] = useState("");
  // Half-controlled cmdk selection. cmdk normally re-anchors to the first
  // enabled item only when the *currently selected* item unmounts; it otherwise
  // retains the selection across re-renders. Our list mutates as the user types
  // (Pages empty out at 1 char, the merchant answer mounts above Actions at >=3
  // chars), but "Add transaction" never unmounts — so without intervention the
  // selection sticks on it and Enter fires the wrong action. We drive cmdk's
  // `value` from this state and snap it to the visual top row whenever the input
  // or answer-presence flags change (see the effect below). Arrow keys still
  // mutate selection internally and report back via `onValueChange`, so manual
  // navigation keeps working between snaps.
  const [selectedValue, setSelectedValue] = useState("");
  const debounced = useDebouncedValue(input, 250);

  const navigate = useNavigate();
  const location = useLocation();
  const [, setMonth] = useMonthParam();
  const navItems = useNavItems();
  const setMode = useTheme((s) => s.setMode);
  const recents = useOmnibarStore((s) => s.recents);
  const addRecent = useOmnibarStore((s) => s.addRecent);

  const month = currentMonth();
  const [budgetYear, monthNumber] = parseYearMonth(month);

  const { data: categoriesData } = useCategories();
  const { data: summaryData } = useSummary(month);
  const { data: budgetData } = useBudgetStatus(budgetYear, open);
  const { data: config } = useConfig();

  useOmnibarShortcut(() => setOpen((prev) => !prev));

  // Let Layout's search affordances open the same dialog without props.
  useEffect(() => {
    const listener = () => setOpen(true);
    openListeners.add(listener);
    return () => {
      openListeners.delete(listener);
    };
  }, []);

  const categories = categoriesData?.categories;

  // `Transaction.category` is server-canonicalized to lowercase; the categories
  // corpus from `useCategories()` carries display casing. Map a lowercased name
  // back to its display form for the CategoryPill (mirrors CategoryPicker).
  const canonicalize = (lc: string): string =>
    (categories ?? []).find((c) => c.toLowerCase() === lc.toLowerCase()) ?? lc;

  const intent = useMemo(
    () =>
      parseOmniQuery(input, {
        categories: categories ?? [],
        now: { year: budgetYear, month: monthNumber },
      }),
    [input, categories, budgetYear, monthNumber]
  );

  const close = () => {
    setOpen(false);
    setInput("");
  };

  // ---- Answers: category ----
  const categoryAnswer = useMemo(() => {
    if (intent.kind !== "category") return null;
    const name = intent.name;
    // `by_category` keys and budget pace `category` are server-canonicalized to
    // lowercase, while `intent.name` keeps the display casing from
    // `useCategories()` (e.g. "Restaurant/Dining"). Match on the lowercased key,
    // but keep `name` for display. See CategoryPicker.tsx for the same hazard.
    const key = name.toLowerCase();
    const spent = summaryData?.current.by_category[key]?.amount ?? 0;

    let target: number | null = null;
    for (const group of budgetData?.groups ?? []) {
      const detail = group.categories.find((c) => c.category.toLowerCase() === key);
      if (detail) {
        target = detail.target;
        break;
      }
    }

    const todayLocal = todayLocalISO(config?.timezone);
    const daysLeft = daysRemainingInMonth({ todayLocal }, month);

    return { name, spent, target, daysLeft };
  }, [intent, summaryData, budgetData, config, month]);

  // ---- Answers: merchant (debounced search) ----
  // Fire only for a settled merchant intent of >= 3 chars while open. The memo
  // is load-bearing: the query key is `["transaction-search", params]`, so an
  // unmemoized object literal would mint a fresh cache entry every render.
  const merchantQuery =
    open && intent.kind === "merchant" && debounced.trim().length >= 3 ? debounced.trim() : null;
  const merchantIntentActive = merchantQuery !== null;

  const searchParams = useMemo<SearchParams | null>(
    () =>
      merchantQuery ? { from: shiftMonth(month, -11), to: month, company: merchantQuery } : null,
    [merchantQuery, month]
  );
  const { data: searchData, isFetching: searchFetching } = useTransactionSearch(searchParams);

  const merchantAnswer = useMemo(
    () => (searchData ? aggregateMerchantAnswer(searchData, month) : null),
    [searchData, month]
  );

  // ---- Answers: amount ----
  // An amount intent may carry a single-month token; otherwise the range is the
  // same trailing-12-month window the merchant search uses.
  const amountAnswer = useMemo(() => {
    if (intent.kind !== "amount") return null;
    const from = intent.month ?? shiftMonth(month, -11);
    const to = intent.month ?? month;
    return {
      minAmount: intent.minAmount,
      maxAmount: intent.maxAmount,
      from,
      to,
    };
  }, [intent, month]);

  // ---- Pages ----
  const needle = input.trim().toLowerCase();
  const pages = useMemo(
    () =>
      navItems.filter(
        (item) => item.active && (needle === "" || item.label.toLowerCase().includes(needle))
      ),
    [navItems, needle]
  );

  // ---- Months ----
  const monthIntent = intent.kind === "month" ? intent.month : null;

  // The value cmdk should select for "Enter with no arrow keys": the value of
  // the visually top-most enabled row, mirroring the render order below
  // (Answers → Pages → Actions; Months always render last and so are never the
  // default — reachable only via arrows). Computed eagerly so the snap effect
  // can read a fresh value rather than a stale closure.
  const firstPageValue = pages[0] ? `page-${pages[0].href}` : null;
  const topValue =
    (categoryAnswer && `answer-category-${categoryAnswer.name}`) ||
    (amountAnswer && "answer-amount") ||
    (merchantIntentActive && "answer-merchant") ||
    firstPageValue ||
    "action-add-transaction";

  // Re-anchor the selection to the top row whenever the *input* or the
  // answer-presence flags change — i.e. whenever the set of rendered rows could
  // have shifted under the cursor. We deliberately exclude `selectedValue` and
  // arrow-key state from the deps: between these snaps cmdk owns the selection,
  // so arrow navigation (which flows back through `onValueChange`) survives.
  // `topValue` itself is excluded because it is derived from the same inputs and
  // would re-fire the effect mid-arrow-navigation if a later render recomputed
  // an equal string; the flags below are the true triggers.
  const hasCategoryAnswer = categoryAnswer !== null;
  const hasAmountAnswer = amountAnswer !== null;
  useEffect(() => {
    if (!open) return;
    setSelectedValue(topValue);
    // eslint-disable-next-line react-hooks/exhaustive-deps
  }, [open, input, hasCategoryAnswer, hasAmountAnswer, merchantIntentActive, firstPageValue]);

  // Record a Recent entry, then navigate and close. Recents are deduped by `to`
  // in the store (most-recent-first, capped at 8) and surfaced in the empty-input
  // "Recent" group. `at` is read from the wall clock at interaction time — the
  // store and parser stay clock-free; only this UI layer touches `Date.now()`.
  const recordAndGo = (entry: { kind: "query" | "destination"; label: string; to: string }) => {
    addRecent({ ...entry, at: Date.now() });
    navigate(entry.to);
    close();
  };

  const handleCategorySelect = () => {
    if (!categoryAnswer) return;
    // Answer rows record the original input the user typed as the label so the
    // Recent group reads "dining", not the resolved category route.
    recordAndGo({
      kind: "query",
      label: input.trim() || categoryAnswer.name,
      to: `/transactions?category=${encodeURIComponent(categoryAnswer.name)}`,
    });
  };

  const handleMonthSelect = () => {
    if (!monthIntent) return;
    const label = `Go to ${formatMonthLabelLong(monthIntent)}`;
    if (MONTH_SCOPED_PATHS.has(location.pathname)) {
      // In-place month jumps don't change the route, so there's no stable `to`
      // to store; record the canonical /journal target so the recent is
      // re-navigable from any page.
      addRecent({
        kind: "destination",
        label,
        to: `/journal?month=${monthIntent}`,
        at: Date.now(),
      });
      setMonth(monthIntent);
      close();
    } else {
      recordAndGo({ kind: "destination", label, to: `/journal?month=${monthIntent}` });
    }
  };

  const handleMerchantSelect = () => {
    if (!merchantQuery) return;
    // The Transactions range view hydrates `q` (free-text), `from`, `to`; `month`
    // anchors the header MonthPicker on the range's end month.
    const params = new URLSearchParams({
      q: merchantQuery,
      from: shiftMonth(month, -11),
      to: month,
      month,
    });
    recordAndGo({
      kind: "query",
      label: input.trim() || merchantQuery,
      to: `/transactions?${params.toString()}`,
    });
  };

  const handleNoMatchSearch = () => {
    const query = input.trim();
    if (!query) return;
    // Range mode needs both from/to; carry a 12-month lookback and anchor the
    // header on the end month.
    const params = new URLSearchParams({
      q: query,
      from: shiftMonth(month, -11),
      to: month,
      month,
    });
    recordAndGo({
      kind: "query",
      label: query,
      to: `/transactions?${params.toString()}`,
    });
  };

  // The merchant slot is one stable `value="answer-merchant"` item across the
  // loading → loaded transition (see render below). cmdk selects the first
  // enabled item when the list first renders and keeps that selection across
  // re-renders; if the slot swapped values (loading → answer/nomatch) or was
  // disabled while fetching, selection would land on "Add transaction" instead
  // and Enter would fire the wrong action. Keeping one value lets cmdk's
  // selection land on the merchant row from the start and stay there, so Enter
  // (no arrow keys) routes here. This dispatcher then picks the right behavior
  // for the current fetch state: no-op while fetching, drill-down when the
  // merchant has visits, full search on zero matches.
  const handleMerchantAnswerSelect = () => {
    if (searchFetching || !merchantAnswer) return;
    if (merchantAnswer.visitCount > 0) handleMerchantSelect();
    else handleNoMatchSearch();
  };

  const handleRecentSelect = (to: string) => {
    navigate(to);
    close();
  };

  const handleAmountSelect = () => {
    if (!amountAnswer) return;
    // The Transactions range view reads `min`/`max` (not min_amount/max_amount)
    // alongside from/to; `month` anchors the header on the range's end month.
    const params = new URLSearchParams({ from: amountAnswer.from, to: amountAnswer.to });
    params.set("month", amountAnswer.to);
    if (amountAnswer.minAmount !== undefined) {
      params.set("min", String(amountAnswer.minAmount));
    }
    if (amountAnswer.maxAmount !== undefined) {
      params.set("max", String(amountAnswer.maxAmount));
    }
    const label =
      amountAnswer.minAmount !== undefined
        ? `Transactions over ${formatCurrency(amountAnswer.minAmount)}`
        : `Transactions under ${formatCurrency(amountAnswer.maxAmount ?? 0)}`;
    recordAndGo({
      kind: "query",
      label: input.trim() || label,
      to: `/transactions?${params.toString()}`,
    });
  };

  return (
    <Dialog
      open={open}
      onOpenChange={(next) => {
        if (next) setOpen(true);
        else close();
      }}
    >
      <DialogContent className="overflow-hidden p-0">
        <DialogTitle className="sr-only">Search</DialogTitle>
        <DialogDescription className="sr-only">
          Search merchants, categories, or pages
        </DialogDescription>
        <Command
          shouldFilter={false}
          value={selectedValue}
          onValueChange={setSelectedValue}
          className="[&_[cmdk-group-heading]]:px-2 [&_[cmdk-group-heading]]:font-medium [&_[cmdk-group-heading]]:text-muted-foreground [&_[cmdk-group]:not([hidden])_~[cmdk-group]]:pt-0 [&_[cmdk-input-wrapper]_svg]:h-5 [&_[cmdk-input-wrapper]_svg]:w-5 [&_[cmdk-input]]:h-12 [&_[cmdk-item]]:px-2 [&_[cmdk-item]]:py-3 [&_[cmdk-item]_svg]:h-5 [&_[cmdk-item]_svg]:w-5"
        >
          <CommandInput
            placeholder="Search merchants, categories, or pages"
            value={input}
            onValueChange={setInput}
          />
          <CommandList>
            {needle === "" ? (
              <CommandEmpty>Type a merchant, a category, or a month</CommandEmpty>
            ) : (
              <CommandEmpty>No matches. Enter runs a full search.</CommandEmpty>
            )}

            {(categoryAnswer || amountAnswer || merchantIntentActive) && (
              <CommandGroup heading="Answers">
                {categoryAnswer && (
                  <CommandItem
                    value={`answer-category-${categoryAnswer.name}`}
                    onSelect={handleCategorySelect}
                  >
                    <span>{categoryAnswer.name}</span>
                    <span className="ml-auto text-sm text-muted-foreground tabular-nums">
                      {formatCurrency(categoryAnswer.spent)} this month
                      {categoryAnswer.target !== null && (
                        <>
                          {" · "}
                          {formatCurrency(categoryAnswer.target)} target · {categoryAnswer.daysLeft}{" "}
                          days left
                        </>
                      )}
                    </span>
                  </CommandItem>
                )}

                {amountAnswer && (
                  <CommandItem value="answer-amount" onSelect={handleAmountSelect}>
                    <span>
                      {amountAnswer.minAmount !== undefined
                        ? `Transactions over ${formatCurrency(amountAnswer.minAmount)}`
                        : `Transactions under ${formatCurrency(amountAnswer.maxAmount ?? 0)}`}
                    </span>
                  </CommandItem>
                )}

                {/* One stable value across loading → loaded so cmdk's initial
                    selection lands here and Enter routes to the merchant
                    answer, not "Add transaction". The body still renders the
                    skeleton while fetching, which guards against flashing a
                    previous query's totals. */}
                {merchantIntentActive && (
                  <CommandItem value="answer-merchant" onSelect={handleMerchantAnswerSelect}>
                    {searchFetching || !merchantAnswer ? (
                      <Skeleton className="h-4 w-56" />
                    ) : merchantAnswer.visitCount > 0 ? (
                      <>
                        {merchantAnswer.merchantName && (
                          <span className="font-medium">
                            {titleCase(merchantAnswer.merchantName)}
                            {merchantAnswer.merchantCount > 1 && (
                              <span className="font-normal text-muted-foreground">
                                {" "}
                                ({merchantAnswer.merchantCount} merchants)
                              </span>
                            )}
                          </span>
                        )}
                        <span className="tabular-nums">
                          {merchantAnswer.merchantName && "— "}
                          {merchantAnswer.visitCount} visits ·{" "}
                          {formatCurrency(merchantAnswer.currentMonthAmount)} this month ·{" "}
                          {formatCurrency(merchantAnswer.totalAmount)} this year
                          {merchantAnswer.capped && (
                            <>
                              {" · "}first {searchData?.transactions.length} of{" "}
                              {merchantAnswer.totalMatching}
                            </>
                          )}
                        </span>
                        {merchantAnswer.dominantCategory && (
                          <span className="ml-auto">
                            <CategoryPill chevron={false}>
                              {canonicalize(merchantAnswer.dominantCategory)}
                            </CategoryPill>
                          </span>
                        )}
                      </>
                    ) : (
                      <span>No matches. Enter runs a full search.</span>
                    )}
                  </CommandItem>
                )}
              </CommandGroup>
            )}

            {/* Pinned directly under the Answers — top row on an empty
                palette, second after any answer, so a typed query's result
                always sits right below the input. Deliberately NOT part of
                the `topValue` chain: the default highlight still lands on the
                smartest row (answer → page) and Enter keeps its contextual
                meaning. */}
            <CommandGroup>
              <CommandItem
                value="action-advanced-search"
                onSelect={() =>
                  recordAndGo({
                    kind: "destination",
                    label: "Advanced search",
                    to: "/transactions?advanced=1",
                  })
                }
              >
                <SlidersHorizontal className="h-4 w-4" />
                Advanced search
              </CommandItem>
            </CommandGroup>

            {pages.length > 0 && (
              <CommandGroup heading="Pages">
                {pages.map((item) => (
                  <CommandItem
                    key={item.href}
                    value={`page-${item.href}`}
                    onSelect={() =>
                      recordAndGo({ kind: "destination", label: item.label, to: item.href })
                    }
                  >
                    <item.icon className="h-4 w-4" />
                    {item.label}
                  </CommandItem>
                ))}
              </CommandGroup>
            )}

            <CommandGroup heading="Actions">
              <CommandItem
                value="action-add-transaction"
                onSelect={() =>
                  recordAndGo({
                    kind: "destination",
                    label: "Add transaction",
                    to: "/transactions",
                  })
                }
              >
                <Plus className="h-4 w-4" />
                Add transaction
              </CommandItem>
              <CommandItem
                value="action-review-queue"
                onSelect={() =>
                  recordAndGo({
                    kind: "destination",
                    label: "Go to review queue",
                    to: "/transactions",
                  })
                }
              >
                <Search className="h-4 w-4" />
                Go to review queue
              </CommandItem>
              <CommandItem
                value="action-switch-theme"
                onSelect={() => {
                  setMode(document.documentElement.classList.contains("dark") ? "light" : "dark");
                  close();
                }}
              >
                <Moon className="h-4 w-4" />
                Switch theme
              </CommandItem>
            </CommandGroup>

            {monthIntent && (
              <CommandGroup heading="Months">
                <CommandItem value={`month-${monthIntent}`} onSelect={handleMonthSelect}>
                  Go to {formatMonthLabelLong(monthIntent)}
                </CommandItem>
              </CommandGroup>
            )}

            {needle === "" && recents.length > 0 && (
              <CommandGroup heading="Recent">
                {recents.map((entry) => (
                  <CommandItem
                    key={entry.to}
                    value={`recent-${entry.to}`}
                    onSelect={() => handleRecentSelect(entry.to)}
                  >
                    {entry.kind === "query" ? (
                      <Search className="h-4 w-4" />
                    ) : (
                      <Clock className="h-4 w-4" />
                    )}
                    {entry.label}
                  </CommandItem>
                ))}
              </CommandGroup>
            )}
          </CommandList>
        </Command>
      </DialogContent>
    </Dialog>
  );
}
