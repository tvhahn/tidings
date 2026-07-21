import { useQuery, useQueryClient } from "@tanstack/react-query";
import { Check, ChevronDown } from "lucide-react";
import { useMemo, useState } from "react";
import { Badge } from "@/components/ui/badge";
import {
  Command,
  CommandEmpty,
  CommandGroup,
  CommandInput,
  CommandItem,
  CommandList,
  CommandSeparator,
} from "@/components/ui/command";
import { Popover, PopoverContent, PopoverTrigger } from "@/components/ui/popover";
import { useCategories } from "@/hooks/useCategories";
import { suggestFromHistory, type TransactionLike } from "@/lib/categorySuggest";
import { queries } from "@/lib/queryConfigs";
import { cn } from "@/lib/utils";

interface CategoryPickerProps {
  value: string | null;
  onSelect: (category: string) => void;
  edited?: boolean | undefined;
  needsAttention?: boolean | undefined;
  disabled?: boolean | undefined;
  variant?: "badge" | "inline" | undefined;
  placeholder?: string | undefined;
  tourAnchor?: string | undefined;
  /** Transaction merchant text. When provided, the picker surfaces a
   *  "Suggested" entry sourced first from the user's own history of this
   *  merchant in the React Query cache, falling back to the backend
   *  `/overrides/match` endpoint for novel merchants. Omit on bulk pickers
   *  where there's no single merchant context. */
  merchant?: string | null | undefined;
}

const RECENT_KEY = "tidings.categoryPicker.recent.v1";
const MAX_RECENT = 6;

// Module-level mirror so multiple picker instances stay in sync within a session.
// Initialized lazily from localStorage on first read.
let recentCache: string[] | null = null;

function readRecent(): string[] {
  if (recentCache !== null) return recentCache;
  try {
    const raw = typeof localStorage !== "undefined" ? localStorage.getItem(RECENT_KEY) : null;
    if (!raw) {
      recentCache = [];
      return recentCache;
    }
    const parsed: unknown = JSON.parse(raw);
    if (!Array.isArray(parsed)) {
      recentCache = [];
      return recentCache;
    }
    recentCache = parsed.filter((x): x is string => typeof x === "string").slice(0, MAX_RECENT);
    return recentCache;
  } catch {
    recentCache = [];
    return recentCache;
  }
}

function pushRecent(category: string): string[] {
  const current = readRecent();
  const next = current.filter((c) => c !== category);
  next.unshift(category);
  recentCache = next.slice(0, MAX_RECENT);
  try {
    if (typeof localStorage !== "undefined") {
      localStorage.setItem(RECENT_KEY, JSON.stringify(recentCache));
    }
  } catch {
    // Private mode / quota exceeded — module cache still holds the value for the session.
  }
  return recentCache;
}

export function CategoryPicker({
  value,
  onSelect,
  edited,
  needsAttention,
  disabled,
  variant = "badge",
  // "Uncategorized" is a real category name, not a dash — docs/brand/voice.md
  // ("Uncategorized" — not "—", not "No category").
  placeholder = "Uncategorized",
  tourAnchor,
  merchant,
}: CategoryPickerProps) {
  const [open, setOpen] = useState(false);
  // Bump on every select so all picker instances re-render off the shared cache.
  const [, setRecentRev] = useState(0);
  const recent = readRecent();
  const { data } = useCategories();
  const categories = data?.categories ?? [];
  const queryClient = useQueryClient();

  // Local suggestion: scan cached transaction queries for prior categorizations
  // of `merchant`. Cheap, sync, only computed when the popover is open.
  const localSuggestion = useMemo(() => {
    if (!open || !merchant) return null;
    const buckets = queryClient.getQueriesData<unknown>({
      predicate: (q) => {
        const k = q.queryKey;
        if (!Array.isArray(k) || typeof k[0] !== "string") return false;
        return (
          k[0] === "transactions" ||
          k[0] === "transactions-combined" ||
          k[0] === "transaction-search" ||
          k[0] === "journal"
        );
      },
    });

    const all: TransactionLike[] = [];
    for (const [, payload] of buckets) {
      if (!payload || typeof payload !== "object") continue;
      const obj = payload as Record<string, unknown>;
      if (Array.isArray(obj.transactions)) {
        all.push(...(obj.transactions as TransactionLike[]));
      }
      if (Array.isArray(obj.days)) {
        for (const day of obj.days as Array<Record<string, unknown>>) {
          if (Array.isArray(day.transactions)) {
            all.push(...(day.transactions as TransactionLike[]));
          }
        }
      }
    }
    return suggestFromHistory(merchant, value, all);
  }, [open, merchant, queryClient, value]);

  // Backend fallback: only fires when the popover is open, we have a merchant,
  // and local history didn't produce a confident pick.
  const backendQuery = useQuery({
    ...queries.overrideMatchForPicker(merchant ?? ""),
    enabled: open && !!merchant && merchant.trim().length >= 3 && !localSuggestion,
  });

  // Suggester output is lowercase (server canonicalizes via .lower()), but the
  // categories list returns display casing ("Misc. Car Expense", "Restaurant/Dining",
  // etc.). Canonicalize lowercase candidates back to their display form so the
  // Suggested row matches the All Categories row visually.
  const canonicalize = (lc: string): string => categories.find((c) => c.toLowerCase() === lc) ?? lc;

  const valueLower = value?.toLowerCase() ?? null;
  // Drop the current value AND any "miscellaneous" candidate. The latter
  // shouldn't happen now that the server filters miscellaneous out of the
  // override corpus, but a stale corpus or a future change could leak it back —
  // suggesting "miscellaneous" is never useful (it's the bucket users escape).
  const backendCandidates = (backendQuery.data?.candidates ?? []).filter((c) => {
    const lc = c.category.toLowerCase();
    return lc !== valueLower && lc !== "miscellaneous";
  });
  // The backend returns one candidate per matched override rule, so multiple
  // rules sharing a category (e.g. several distinct merchants all categorized
  // as Restaurant/Dining) produce duplicate category rows here. The picker
  // selects a category, not a rule — collapse to first-wins, which preserves
  // backend confidence ordering.
  const seenCategory = new Set<string>();
  const dedupedCandidates = backendCandidates.filter((c) => {
    const lc = c.category.toLowerCase();
    if (seenCategory.has(lc)) return false;
    seenCategory.add(lc);
    return true;
  });
  const suggested = localSuggestion
    ? { category: canonicalize(localSuggestion.category), source: "local" as const }
    : dedupedCandidates[0]
      ? { category: canonicalize(dedupedCandidates[0].category), source: "ai" as const }
      : null;
  const didYouMean =
    suggested && !localSuggestion
      ? dedupedCandidates.slice(1, 4).map((c) => canonicalize(c.category))
      : [];

  // Hide the suggestion in the lower groups so it doesn't render twice.
  const suggestedLower = suggested?.category.toLowerCase() ?? null;
  const dymLower = new Set(didYouMean.map((c) => c.toLowerCase()));

  const handleSelect = (category: string) => {
    pushRecent(category);
    setRecentRev((n) => n + 1);
    onSelect(category);
    setOpen(false);
  };

  const renderItem = (cat: string, key: string, prefix?: React.ReactNode) => {
    const selected = value?.toLowerCase() === cat.toLowerCase();
    return (
      <CommandItem key={key} onSelect={() => handleSelect(cat)}>
        <Check className={cn("mr-2 h-4 w-4", selected ? "opacity-100" : "opacity-0")} />
        {prefix}
        {cat}
      </CommandItem>
    );
  };

  return (
    <Popover open={disabled ? false : open} {...(disabled ? {} : { onOpenChange: setOpen })}>
      <PopoverTrigger asChild>
        <button
          data-tour={tourAnchor}
          aria-label="Edit category"
          className={cn(
            "flex items-center gap-1.5 text-left",
            disabled && "opacity-50 cursor-not-allowed"
          )}
        >
          {variant === "inline" ? (
            <span
              className={cn(
                "inline-flex items-center gap-0.5 text-xs font-medium rounded-full px-2 py-0.5 transition-colors cursor-pointer",
                needsAttention
                  ? "text-status-warning bg-status-warning-muted hover:bg-status-warning/20"
                  : "text-muted-foreground bg-muted hover:bg-muted-foreground/15 hover:text-foreground"
              )}
            >
              {value || "Uncategorized"}
              {!needsAttention && (
                <ChevronDown className="h-2.5 w-2.5 text-muted-foreground/60" aria-hidden />
              )}
            </span>
          ) : (
            <Badge
              variant="secondary"
              className={cn(
                "cursor-pointer text-xs font-normal",
                needsAttention &&
                  "bg-status-warning-muted text-status-warning border-status-warning/50"
              )}
            >
              {value || placeholder}
            </Badge>
          )}
          {edited && <span className="h-2 w-2 rounded-full bg-status-info shrink-0" />}
        </button>
      </PopoverTrigger>
      <PopoverContent className="w-[240px] p-0" align="start">
        <Command>
          <CommandInput placeholder="Search categories..." />
          <CommandList>
            <CommandEmpty>No category found.</CommandEmpty>
            {suggested && (
              <>
                <CommandGroup heading="Suggested">
                  {renderItem(suggested.category, `suggested-${suggested.category}`)}
                </CommandGroup>
                {didYouMean.length > 0 && (
                  <CommandGroup heading="Did you mean?">
                    {didYouMean.map((cat) => renderItem(cat, `dym-${cat}`))}
                  </CommandGroup>
                )}
                <CommandSeparator />
              </>
            )}
            {recent.length > 0 && (
              <>
                <CommandGroup heading="Recent">
                  {recent
                    .filter(
                      (cat) =>
                        cat.toLowerCase() !== suggestedLower && !dymLower.has(cat.toLowerCase())
                    )
                    .map((cat) => renderItem(cat, `recent-${cat}`))}
                </CommandGroup>
                <CommandSeparator />
              </>
            )}
            <CommandGroup heading="All Categories">
              {categories.map((cat) => renderItem(cat, cat))}
            </CommandGroup>
          </CommandList>
        </Command>
      </PopoverContent>
    </Popover>
  );
}
