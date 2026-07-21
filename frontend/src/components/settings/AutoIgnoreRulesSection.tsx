import { Check, ChevronRight, EyeOff, Lightbulb } from "lucide-react";
import { useMemo, useState } from "react";
import { toast } from "sonner";
import {
  AddRowButton,
  DeleteRowButton,
  ListSearchInput,
  ShowAllToggle,
} from "@/components/settings/managedListPrimitives";
import { SettingsSectionHeader } from "@/components/settings/SettingsSectionHeader";
import { Badge } from "@/components/ui/badge";
import { Input } from "@/components/ui/input";
import { Skeleton } from "@/components/ui/skeleton";
import {
  Table,
  TableBody,
  TableCell,
  TableHead,
  TableHeader,
  TableRow,
} from "@/components/ui/table";
import {
  useAddIgnoreRule,
  useApplyIgnoreRules,
  useDeleteIgnoreRule,
  useDismissIgnoreRuleSuggestion,
  useIgnoreRuleDismissedSuggestions,
  useIgnoreRules,
  useIgnoreRuleSuggestions,
  useUndismissIgnoreRuleSuggestion,
} from "@/hooks/useIgnoreRules";
import { formatRelativeTime } from "@/lib/format";

const COLLAPSED_LIMIT = 4;

export function AutoIgnoreRulesSection() {
  const { data, isLoading } = useIgnoreRules();
  const { data: suggestionsData } = useIgnoreRuleSuggestions();
  const { data: dismissedData } = useIgnoreRuleDismissedSuggestions();
  const addMutation = useAddIgnoreRule();
  const deleteMutation = useDeleteIgnoreRule();
  const applyMutation = useApplyIgnoreRules();
  const dismissMutation = useDismissIgnoreRuleSuggestion();
  const undismissMutation = useUndismissIgnoreRuleSuggestion();

  const [search, setSearch] = useState("");
  const [newPattern, setNewPattern] = useState("");
  const [rulesExpanded, setRulesExpanded] = useState(false);
  const [dismissedExpanded, setDismissedExpanded] = useState(false);

  const rules = useMemo(() => data?.rules ?? [], [data?.rules]);
  const suggestions = suggestionsData?.suggestions ?? [];
  const dismissed = dismissedData?.dismissed ?? [];

  const filtered = useMemo(() => {
    if (!search) return rules;
    const q = search.toLowerCase();
    return rules.filter((r) => r.pattern.toLowerCase().includes(q));
  }, [rules, search]);

  // Add a rule, then backfill history and report the count calmly.
  const addRuleAndBackfill = (pattern: string) => {
    const p = pattern.trim();
    if (!p) return;
    addMutation.mutate(p, {
      onSuccess: () => {
        setNewPattern("");
        applyMutation.mutate(p, {
          onSuccess: (res) => {
            const n = res.total_updated;
            toast(
              n > 0
                ? `${n} ${n === 1 ? "transaction" : "transactions"} marked ignored`
                : "No past transactions matched this rule"
            );
          },
        });
      },
    });
  };

  const mutating = addMutation.isPending || applyMutation.isPending;
  const isSearching = search.length > 0;
  const showAll = isSearching || rulesExpanded;
  const visible = showAll ? filtered : filtered.slice(0, COLLAPSED_LIMIT);
  const hiddenCount = filtered.length - COLLAPSED_LIMIT;

  return (
    <section className="space-y-4">
      {suggestions.length > 0 && (
        <div className="space-y-2 rounded-xl border border-border/50 bg-muted/20 p-3">
          <div className="flex items-center gap-2">
            <Lightbulb className="h-4 w-4 text-status-warning" />
            <h3 className="text-sm font-medium">Suggested rules</h3>
            <Badge variant="secondary" className="text-xs">
              {suggestions.length}
            </Badge>
          </div>
          <p className="text-sm text-muted-foreground">Merchants you usually ignore by hand.</p>
          <div className="space-y-1.5">
            {suggestions.map((s) => (
              <div
                key={s.merchant}
                className="flex items-center justify-between gap-3 rounded-lg bg-background px-3 py-2"
              >
                <div className="min-w-0">
                  <p className="truncate text-sm">
                    You usually ignore <span className="font-medium">{s.merchant}</span>
                  </p>
                  <p className="text-xs text-muted-foreground">
                    {s.ignored_count} of {s.total_count} ignored
                  </p>
                </div>
                <div className="flex shrink-0 items-center gap-1">
                  <button
                    type="button"
                    title="Dismiss suggestion"
                    aria-label={`Dismiss suggestion for ${s.merchant}`}
                    onClick={() => dismissMutation.mutate(s.merchant)}
                    disabled={mutating || dismissMutation.isPending}
                    className="rounded p-1 text-muted-foreground transition-colors hover:bg-status-warning/10 hover:text-status-warning disabled:opacity-50"
                  >
                    <EyeOff className="h-4 w-4" />
                  </button>
                  <button
                    type="button"
                    title="Add rule"
                    aria-label={`Add rule for ${s.merchant}`}
                    onClick={() => addRuleAndBackfill(s.merchant)}
                    disabled={mutating || dismissMutation.isPending}
                    className="rounded p-1 text-muted-foreground transition-colors hover:bg-status-success/10 hover:text-status-success disabled:opacity-50"
                  >
                    <Check className="h-4 w-4" />
                  </button>
                </div>
              </div>
            ))}
          </div>
        </div>
      )}

      {dismissed.length > 0 && (
        <div className="text-sm">
          <button
            type="button"
            onClick={() => setDismissedExpanded((v) => !v)}
            aria-expanded={dismissedExpanded}
            className="flex items-center gap-1.5 text-muted-foreground transition-colors hover:text-foreground"
          >
            <ChevronRight
              className={`h-3.5 w-3.5 transition-transform ${dismissedExpanded ? "rotate-90" : ""}`}
            />
            {dismissed.length} dismissed {dismissed.length === 1 ? "suggestion" : "suggestions"}
          </button>
          {dismissedExpanded && (
            <ul className="mt-2 space-y-1.5 pl-5">
              {dismissed.map((d) => (
                <li key={d.merchant} className="flex items-center justify-between gap-3">
                  <div className="flex min-w-0 items-baseline gap-2">
                    <span className="truncate">{d.merchant}</span>
                    {d.dismissed_at && (
                      <span className="shrink-0 text-xs text-muted-foreground">
                        dismissed {formatRelativeTime(d.dismissed_at)}
                      </span>
                    )}
                  </div>
                  <button
                    type="button"
                    aria-label={`Restore suggestion for ${d.merchant}`}
                    onClick={() => undismissMutation.mutate(d.merchant)}
                    disabled={undismissMutation.isPending}
                    className="shrink-0 text-xs text-muted-foreground underline-offset-2 transition-colors hover:text-foreground hover:underline disabled:opacity-50"
                  >
                    Restore
                  </button>
                </li>
              ))}
            </ul>
          )}
        </div>
      )}

      <SettingsSectionHeader
        title="Auto-ignore rules"
        infoHint={{
          label: "About auto-ignore rules",
          content:
            "Merchant patterns pinned to ignored. A new transaction whose merchant matches a rule arrives ignored, so it stays out of monthly totals, budget pace, and briefings — the same way credit-card payments and investment transfers are usually handled by hand. Existing transactions are unchanged unless you apply a rule to your history.",
        }}
        count={data?.count}
        countLabel="auto-ignore rules"
        toolbar={
          <ListSearchInput
            id="settings-ignore-rules-search"
            value={search}
            onChange={setSearch}
            ariaLabel="Search auto-ignore rules"
            placeholder="Search rules…"
          />
        }
      />

      {/* Add rule form */}
      <div className="flex flex-col gap-2 rounded-lg border border-border/50 bg-muted/20 px-3 py-2 sm:flex-row sm:items-center">
        <Input
          id="settings-ignore-rules-new"
          placeholder="Merchant name"
          value={newPattern}
          onChange={(e) => setNewPattern(e.target.value)}
          className="h-8 flex-1 bg-background"
          onKeyDown={(e) => {
            if (e.key === "Enter") addRuleAndBackfill(newPattern);
          }}
        />
        <AddRowButton
          onClick={() => addRuleAndBackfill(newPattern)}
          disabled={!newPattern.trim() || mutating}
          label="Add rule"
        />
      </div>

      {isLoading && (
        <div className="space-y-2">
          {Array.from({ length: 3 }).map((_, i) => (
            <Skeleton key={i} className="h-10 w-full" />
          ))}
        </div>
      )}

      {!isLoading && filtered.length === 0 && (
        <p className="py-6 text-center text-muted-foreground">
          {search ? "No rules match your search" : "No auto-ignore rules configured"}
        </p>
      )}

      {!isLoading && visible.length > 0 && (
        <div className="space-y-2">
          <div className="rounded-xl border border-border/50">
            <Table>
              <TableHeader>
                <TableRow>
                  <TableHead>Merchant</TableHead>
                  <TableHead className="w-12" />
                </TableRow>
              </TableHeader>
              <TableBody>
                {visible.map((r) => (
                  <TableRow key={r.pattern}>
                    <TableCell>
                      <span className="text-sm font-medium">{r.pattern}</span>
                    </TableCell>
                    <TableCell>
                      <DeleteRowButton
                        onClick={() => deleteMutation.mutate(r.pattern)}
                        disabled={deleteMutation.isPending}
                        label="Delete rule"
                      />
                    </TableCell>
                  </TableRow>
                ))}
              </TableBody>
            </Table>
          </div>
          {!isSearching && hiddenCount > 0 && (
            <ShowAllToggle
              expanded={rulesExpanded}
              onToggle={() => setRulesExpanded(!rulesExpanded)}
              totalCount={filtered.length}
              entityPlural="rules"
            />
          )}
        </div>
      )}
    </section>
  );
}
