import { ArrowLeft, ChevronDown, ChevronRight, Loader2, Plus } from "lucide-react";
import { useCallback, useEffect, useMemo, useRef, useState } from "react";
import { useNavigate, useSearchParams } from "react-router-dom";
import { toast } from "sonner";
import { BudgetEditRow } from "@/components/BudgetEditRow";
import { CeilingBar } from "@/components/CeilingBar";
import { PageHeader } from "@/components/PageHeader";
import { Button } from "@/components/ui/button";
import {
  Command,
  CommandEmpty,
  CommandGroup,
  CommandInput,
  CommandItem,
  CommandList,
} from "@/components/ui/command";
import { Popover, PopoverContent, PopoverTrigger } from "@/components/ui/popover";
import { Skeleton } from "@/components/ui/skeleton";
import {
  Table,
  TableBody,
  TableCell,
  TableFooter,
  TableHead,
  TableHeader,
  TableRow,
} from "@/components/ui/table";
import { useBudgetConfig } from "@/hooks/useBudgetConfig";
import { useBudgetStatus } from "@/hooks/useBudgetStatus";
import { useCategories } from "@/hooks/useCategories";
import { useCategoryGroups } from "@/hooks/useCategoryGroups";
import { useHistoricalAverages } from "@/hooks/useHistoricalAverages";
import { useUpdateBudget } from "@/hooks/useUpdateBudget";
import {
  buildAvgMap,
  buildPrefillEntries,
  buildSpendingMap,
  buildSuggestedMap,
  computeGroupSubtotals,
  groupEntries,
  recalculateEntry,
} from "@/lib/budgetCalc";
import type { AvgMap, CategoryFormEntry, SpendingMap, SuggestedMap } from "@/lib/budgetCalc";
import { currentYear, formatCurrencyRounded } from "@/lib/format";
import type { BudgetGroupConfig } from "@/types/api";

const formatNum = formatCurrencyRounded;

export function BudgetEditPage() {
  const navigate = useNavigate();
  const [searchParams] = useSearchParams();
  const year = parseInt(searchParams.get("year") ?? String(currentYear()), 10);
  const prefillParam = searchParams.get("prefill");
  const addParam = searchParams.get("add");

  // Data sources
  const { data: config, isLoading: configLoading } = useBudgetConfig(year);
  const { data: status } = useBudgetStatus(year, config != null);
  const { data: hist3 } = useHistoricalAverages(3, true);
  const { data: hist12, isLoading: histLoading } = useHistoricalAverages(12, true);
  const { data: allCategories } = useCategories();
  const { groups: dynamicGroups } = useCategoryGroups(year);
  const mutation = useUpdateBudget(year);

  // Form state
  const [ceiling, setCeiling] = useState("");
  const [entries, setEntries] = useState<CategoryFormEntry[]>([]);
  const [showSpending, setShowSpending] = useState(false);
  const [collapsedGroups, setCollapsedGroups] = useState<Set<string>>(new Set());
  const [addOpen, setAddOpen] = useState(false);
  const [dirty, setDirty] = useState(false);
  const initialized = useRef(false);
  // `prefillApplied` is read in render (to hide the prefill button) AND written
  // in an effect, so it needs to be state rather than a ref.
  const [prefillApplied, setPrefillApplied] = useState(false);
  const addApplied = useRef(false);

  // Initialize from config
  useEffect(() => {
    if (configLoading) return;
    if (initialized.current) return;

    if (config) {
      setCeiling(String(config.spending_ceiling));
      setEntries(
        Object.entries(config.categories).map(([key, cat]) => ({
          key,
          target: cat.target,
          inputMode: cat.input_mode,
          categoryType: cat.category_type,
          displayAmount:
            cat.input_mode === "monthly" ? String(cat.monthly_amount) : String(cat.target),
        }))
      );
      initialized.current = true;
    } else {
      initialized.current = true;
    }
  }, [config, configLoading]);

  // Pre-fill from history (use 12mo data for pre-fill)
  useEffect(() => {
    if (prefillParam !== "history" || !hist12 || prefillApplied) return;
    setPrefillApplied(true);

    const { entries: newEntries, ceiling: newCeiling } = buildPrefillEntries(hist12);
    setEntries(newEntries);
    setCeiling(newCeiling);
    setDirty(true);
  }, [prefillParam, hist12, prefillApplied]);

  // Add single category from query param
  useEffect(() => {
    if (!addParam || addApplied.current) return;
    if (entries.some((e) => e.key === addParam)) {
      addApplied.current = true;
      return;
    }
    if (histLoading) return;
    addApplied.current = true;

    const hist = hist12?.categories[addParam];
    setEntries((prev) => [
      ...prev,
      {
        key: addParam,
        target: hist?.suggested_annual ?? 0,
        inputMode: "monthly",
        categoryType: (hist?.suggested_type as "fixed" | "variable" | "lumpy") ?? "variable",
        displayAmount: String(hist?.suggested_monthly ?? 0),
      },
    ]);
    setDirty(true);
  }, [addParam, entries, hist12, histLoading]);

  // Lookup maps
  const spendingMap = useMemo(() => buildSpendingMap(status), [status]);

  const avg3Map = useMemo(() => buildAvgMap(hist3), [hist3]);
  const avg12Map = useMemo(() => buildAvgMap(hist12), [hist12]);

  // Suggested monthly from 12mo data (for placeholders and add category)
  const suggestedMap = useMemo(() => buildSuggestedMap(hist12), [hist12]);

  // Group entries for display
  const groupedEntries = useMemo(
    () => groupEntries(entries, config?.groups ?? dynamicGroups),
    [entries, config?.groups, dynamicGroups]
  );

  // Unbudgeted categories with spending but no target
  const unbudgetedWithSpending = useMemo(() => {
    const budgetedKeys = new Set(entries.map((e) => e.key));
    return (status?.unbudgeted ?? [])
      .filter((c) => !budgetedKeys.has(c.category))
      .sort((a, b) => b.ytd_spent - a.ytd_spent);
  }, [entries, status?.unbudgeted]);

  // Handlers
  const updateEntry = useCallback((key: string, patch: Partial<CategoryFormEntry>) => {
    setEntries((prev) => prev.map((e) => (e.key !== key ? e : recalculateEntry(e, patch))));
    setDirty(true);
  }, []);

  const removeCategory = useCallback((key: string) => {
    setEntries((prev) => prev.filter((e) => e.key !== key));
    setDirty(true);
  }, []);

  const addCategory = useCallback(
    (cat: string) => {
      if (entries.some((e) => e.key === cat)) return;
      const s = suggestedMap[cat];
      setEntries((prev) => [
        ...prev,
        {
          key: cat,
          target: s ? Math.round(s.suggestedMonthly) * 12 : 0,
          inputMode: "monthly",
          categoryType: (s?.suggestedType as "fixed" | "variable" | "lumpy") ?? "variable",
          displayAmount: s ? String(Math.round(s.suggestedMonthly)) : "0",
        },
      ]);
      setAddOpen(false);
      setDirty(true);
    },
    [entries, suggestedMap]
  );

  const toggleGroup = useCallback((name: string) => {
    setCollapsedGroups((prev) => {
      const next = new Set(prev);
      if (next.has(name)) next.delete(name);
      else next.add(name);
      return next;
    });
  }, []);

  const handleCeilingChange = useCallback((value: string) => {
    setCeiling(value);
    setDirty(true);
  }, []);

  const handleSave = () => {
    const groups: BudgetGroupConfig[] = (config?.groups ?? dynamicGroups).map((g) => ({
      name: g.name,
      categories: g.categories,
    }));

    mutation.mutate(
      {
        spending_ceiling: parseFloat(ceiling) || 0,
        categories: Object.fromEntries(
          entries.map((e) => [
            e.key,
            { target: e.target, input_mode: e.inputMode, category_type: e.categoryType },
          ])
        ),
        groups: config?.groups ?? groups,
        targets_version: config?.targets_version ?? null,
        groups_version: config?.groups_version ?? null,
      },
      {
        onSuccess: () => {
          setDirty(false);
          toast.success("Budget saved");
          navigate("/budgets");
        },
        onError: (err) => {
          if ((err as Error & { status?: number }).status === 409) {
            toast.error("Budget was modified in another tab — please reload");
          } else {
            toast.error(`Failed to save: ${err.message}`);
          }
        },
      }
    );
  };

  // Unsaved changes guard — mirror `dirty` into a ref for event handlers
  // that need the latest value without re-registering on every keystroke.
  const dirtyRef = useRef(false);
  useEffect(() => {
    dirtyRef.current = dirty;
  }, [dirty]);

  useEffect(() => {
    const handler = (e: BeforeUnloadEvent) => {
      if (dirtyRef.current) e.preventDefault();
    };
    window.addEventListener("beforeunload", handler);
    return () => window.removeEventListener("beforeunload", handler);
  }, []);

  const navigateBack = useCallback(() => {
    if (dirtyRef.current) {
      if (!window.confirm("You have unsaved changes. Discard them?")) return;
    }
    navigate("/budgets");
  }, [navigate]);

  // Totals
  const allocatedTotal = entries.reduce((s, e) => s + e.target, 0);
  const ceilingNum = parseFloat(ceiling) || 0;
  const totalAvg3 = entries.reduce((s, e) => s + (avg3Map[e.key] ?? 0), 0);
  const totalAvg12 = entries.reduce((s, e) => s + (avg12Map[e.key] ?? 0), 0);
  const totalCurrentMonth = entries.reduce(
    (s, e) => s + (spendingMap[e.key]?.currentMonth ?? 0),
    0
  );
  const totalYtd = entries.reduce((s, e) => s + (spendingMap[e.key]?.ytd ?? 0), 0);

  const usedKeys = new Set(entries.map((e) => e.key));
  const availableCategories = (allCategories?.categories ?? []).filter(
    (c) => !usedKeys.has(c.toLowerCase())
  );

  const colCount = showSpending ? 9 : 7;

  if (configLoading) {
    return (
      <div className="space-y-4">
        <Skeleton className="h-8 w-48" />
        <Skeleton className="h-20 w-full rounded-xl" />
        <Skeleton className="h-64 w-full rounded-xl" />
      </div>
    );
  }

  return (
    <div className="space-y-4 pb-24">
      {/* Header */}
      <div className="flex items-start gap-3">
        <Button variant="ghost" size="icon" onClick={navigateBack} className="mt-1">
          <ArrowLeft className="h-4 w-4" />
        </Button>
        <div className="flex-1">
          <PageHeader
            title={`Edit ${year} category budgets`}
            subtitle="Adjust per-category targets. Changes save when you press Save."
            actions={
              <>
                {!config && !prefillApplied && (
                  <Button
                    variant="outline"
                    size="sm"
                    onClick={() => {
                      if (hist12) {
                        const { entries: newEntries, ceiling: newCeiling } =
                          buildPrefillEntries(hist12);
                        setEntries(newEntries);
                        setCeiling(newCeiling);
                        setDirty(true);
                      }
                    }}
                    disabled={histLoading || !hist12}
                  >
                    {histLoading && <Loader2 className="mr-1 h-3 w-3 animate-spin" />}
                    Pre-fill History
                  </Button>
                )}
                <Button onClick={handleSave} disabled={mutation.isPending} size="sm">
                  {mutation.isPending && <Loader2 className="mr-1 h-3 w-3 animate-spin" />}
                  Save
                </Button>
              </>
            }
          />
        </div>
      </div>

      {/* Ceiling bar */}
      <CeilingBar
        ceiling={ceilingNum}
        allocated={allocatedTotal}
        onCeilingChange={handleCeilingChange}
        ceilingRaw={ceiling}
      />

      {/* Show spending toggle */}
      <div className="flex justify-end">
        <Button variant="outline" size="sm" onClick={() => setShowSpending((s) => !s)}>
          {showSpending ? "Hide spending" : "Show spending"}
        </Button>
      </div>

      {/* Main table */}
      <div className="rounded-lg border overflow-x-auto scroll-shadow-x">
        <Table className="min-w-[860px]">
          <TableHeader>
            <TableRow>
              <TableHead>Category</TableHead>
              <TableHead className="text-right">3mo Avg</TableHead>
              <TableHead className="text-right">12mo Avg</TableHead>
              {showSpending && <TableHead className="text-right">This Mo.</TableHead>}
              {showSpending && <TableHead className="text-right">YTD</TableHead>}
              <TableHead className="text-right">Monthly</TableHead>
              <TableHead className="text-right">Annual</TableHead>
              <TableHead>Type</TableHead>
              <TableHead className="w-[40px]" />
            </TableRow>
          </TableHeader>
          <TableBody>
            {groupedEntries.map((group) => {
              const collapsed = collapsedGroups.has(group.name);
              const sub = computeGroupSubtotals(group.entries, avg3Map, avg12Map, spendingMap);

              return (
                <GroupRows
                  key={group.name}
                  groupName={group.name}
                  collapsed={collapsed}
                  onToggle={() => toggleGroup(group.name)}
                  entries={group.entries}
                  avg3Map={avg3Map}
                  avg12Map={avg12Map}
                  suggestedMap={suggestedMap}
                  spendingMap={spendingMap}
                  showSpending={showSpending}
                  onUpdate={updateEntry}
                  onRemove={removeCategory}
                  subtotals={sub}
                  colCount={colCount}
                />
              );
            })}

            {/* Unbudgeted with spending */}
            {unbudgetedWithSpending.length > 0 && (
              <>
                <TableRow className="bg-muted/30">
                  <TableCell
                    colSpan={colCount}
                    className="text-xs font-medium text-muted-foreground py-2"
                  >
                    Unbudgeted (with spending, no target)
                  </TableCell>
                </TableRow>
                {unbudgetedWithSpending.map((cat) => (
                  <TableRow key={cat.category} className="text-muted-foreground">
                    <TableCell className="capitalize">{cat.category}</TableCell>
                    <TableCell className="text-right">
                      {formatNum(avg3Map[cat.category] ?? null)}
                    </TableCell>
                    <TableCell className="text-right">
                      {formatNum(avg12Map[cat.category] ?? null)}
                    </TableCell>
                    {showSpending && (
                      <TableCell className="text-right">
                        {formatNum(cat.current_month_spent)}
                      </TableCell>
                    )}
                    {showSpending && (
                      <TableCell className="text-right">{formatNum(cat.ytd_spent)}</TableCell>
                    )}
                    <TableCell className="text-right">-</TableCell>
                    <TableCell className="text-right">-</TableCell>
                    <TableCell>-</TableCell>
                    <TableCell>
                      <Button
                        variant="ghost"
                        size="sm"
                        className="h-6 text-xs"
                        onClick={() => addCategory(cat.category)}
                      >
                        + Add
                      </Button>
                    </TableCell>
                  </TableRow>
                ))}
              </>
            )}
          </TableBody>
          <TableFooter>
            {/* Label row */}
            <TableRow className="text-xs text-muted-foreground border-b-0">
              <TableCell />
              <TableCell className="text-right">3mo Avg</TableCell>
              <TableCell className="text-right">12mo Avg</TableCell>
              {showSpending && <TableCell className="text-right">This Mo.</TableCell>}
              {showSpending && <TableCell className="text-right">YTD</TableCell>}
              <TableCell className="text-right">Monthly</TableCell>
              <TableCell className="text-right">Annual</TableCell>
              <TableCell />
              <TableCell />
            </TableRow>
            {/* Totals row */}
            <TableRow className="font-semibold text-sm">
              <TableCell>GRAND TOTAL</TableCell>
              <TableCell className="text-right">{formatNum(totalAvg3)}</TableCell>
              <TableCell className="text-right">{formatNum(totalAvg12)}</TableCell>
              {showSpending && (
                <TableCell className="text-right">{formatNum(totalCurrentMonth)}</TableCell>
              )}
              {showSpending && <TableCell className="text-right">{formatNum(totalYtd)}</TableCell>}
              <TableCell className="text-right">
                {formatNum(Math.round(allocatedTotal / 12))}
              </TableCell>
              <TableCell className="text-right">{formatNum(allocatedTotal)}</TableCell>
              <TableCell />
              <TableCell />
            </TableRow>
          </TableFooter>
        </Table>
      </div>

      {/* Add category */}
      <div className="flex justify-start">
        <Popover open={addOpen} onOpenChange={setAddOpen}>
          <PopoverTrigger asChild>
            <Button variant="outline" size="sm">
              <Plus className="mr-1 h-3 w-3" /> Add Category
            </Button>
          </PopoverTrigger>
          <PopoverContent className="w-[240px] p-0" align="start">
            <Command>
              <CommandInput placeholder="Search categories..." />
              <CommandList>
                <CommandEmpty>No categories available.</CommandEmpty>
                <CommandGroup>
                  {availableCategories.map((cat) => (
                    <CommandItem key={cat} onSelect={() => addCategory(cat.toLowerCase())}>
                      {cat}
                    </CommandItem>
                  ))}
                </CommandGroup>
              </CommandList>
            </Command>
          </PopoverContent>
        </Popover>
      </div>
    </div>
  );
}

// --- Group rendering helper ---

interface GroupRowsProps {
  groupName: string;
  collapsed: boolean;
  onToggle: () => void;
  entries: CategoryFormEntry[];
  avg3Map: AvgMap;
  avg12Map: AvgMap;
  suggestedMap: SuggestedMap;
  spendingMap: SpendingMap;
  showSpending: boolean;
  onUpdate: (key: string, patch: Partial<CategoryFormEntry>) => void;
  onRemove: (key: string) => void;
  subtotals: {
    avg3: number;
    avg12: number;
    currentMonth: number;
    ytd: number;
    monthly: number;
    annual: number;
  };
  colCount: number;
}

function GroupRows({
  groupName,
  collapsed,
  onToggle,
  entries,
  avg3Map,
  avg12Map,
  suggestedMap,
  spendingMap,
  showSpending,
  onUpdate,
  onRemove,
  subtotals,
  colCount,
}: GroupRowsProps) {
  return (
    <>
      {/* Group header */}
      <TableRow className="bg-muted/30 cursor-pointer hover:bg-muted/50" onClick={onToggle}>
        <TableCell colSpan={colCount} className="py-2">
          <div className="flex items-center gap-1 text-sm font-medium">
            {collapsed ? <ChevronRight className="h-4 w-4" /> : <ChevronDown className="h-4 w-4" />}
            {groupName}
          </div>
        </TableCell>
      </TableRow>

      {/* Rows */}
      {!collapsed &&
        entries.map((entry) => (
          <BudgetEditRow
            key={entry.key}
            entry={entry}
            avg3={avg3Map[entry.key] ?? null}
            avg12={avg12Map[entry.key] ?? null}
            suggestedMonthly={suggestedMap[entry.key]?.suggestedMonthly ?? null}
            currentMonthSpent={spendingMap[entry.key]?.currentMonth ?? null}
            ytdSpent={spendingMap[entry.key]?.ytd ?? null}
            showSpending={showSpending}
            onUpdate={onUpdate}
            onRemove={onRemove}
          />
        ))}

      {/* Subtotal row */}
      <TableRow className="bg-muted/50 font-medium">
        <TableCell className="text-xs text-muted-foreground uppercase">
          {collapsed ? groupName : ""} Subtotal
        </TableCell>
        <TableCell className="text-right text-sm">{formatNum(subtotals.avg3)}</TableCell>
        <TableCell className="text-right text-sm">{formatNum(subtotals.avg12)}</TableCell>
        {showSpending && (
          <TableCell className="text-right text-sm">{formatNum(subtotals.currentMonth)}</TableCell>
        )}
        {showSpending && (
          <TableCell className="text-right text-sm">{formatNum(subtotals.ytd)}</TableCell>
        )}
        <TableCell className="text-right text-sm">
          {formatNum(Math.round(subtotals.monthly))}
        </TableCell>
        <TableCell className="text-right text-sm">{formatNum(subtotals.annual)}</TableCell>
        <TableCell />
        <TableCell />
      </TableRow>
    </>
  );
}
