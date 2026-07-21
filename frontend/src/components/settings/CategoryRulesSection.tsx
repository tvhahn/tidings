import { Check, ChevronDown, ChevronUp, EyeOff, Lightbulb, Sparkles } from "lucide-react";
import { useState, useMemo } from "react";
import { CategoryPicker } from "@/components/CategoryPicker";
import {
  AddRowButton,
  DeleteRowButton,
  ListSearchInput,
  ShowAllToggle,
} from "@/components/settings/managedListPrimitives";
import { OverrideDuplicatesBanner } from "@/components/settings/OverrideDuplicatesBanner";
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
import { useDebouncedValue } from "@/hooks/useDebouncedValue";
import {
  useOverrides,
  usePutOverride,
  useDeleteOverride,
  useOverrideMatch,
} from "@/hooks/useOverrides";
import { useOverrideSuggestions, useDismissSuggestion } from "@/hooks/useOverrideSuggestions";
import type { OverrideMatchTier } from "@/types/api";

export function CategoryRulesSection() {
  const { data: overridesData, isLoading: overridesLoading } = useOverrides();
  const putOverrideMutation = usePutOverride();
  const deleteOverrideMutation = useDeleteOverride();
  const { data: suggestionsData } = useOverrideSuggestions();
  const dismissMutation = useDismissSuggestion();

  const [search, setSearch] = useState("");
  const [rulesExpanded, setRulesExpanded] = useState(false);
  const [newCompany, setNewCompany] = useState("");
  const [newCategory, setNewCategory] = useState<string | null>(null);
  const [hintExpanded, setHintExpanded] = useState(false);

  const debouncedCompany = useDebouncedValue(newCompany.trim(), 300);
  const { data: matchData } = useOverrideMatch(debouncedCompany);

  const overrides = useMemo(() => overridesData?.overrides ?? [], [overridesData?.overrides]);
  const suggestions = suggestionsData?.suggestions ?? [];

  const filteredOverrides = useMemo(() => {
    if (!search) return overrides;
    const q = search.toLowerCase();
    return overrides.filter(
      (o) => o.company.toLowerCase().includes(q) || o.category.toLowerCase().includes(q)
    );
  }, [overrides, search]);

  const handleAddRule = () => {
    const company = newCompany.trim();
    if (!company || !newCategory) return;
    putOverrideMutation.mutate(
      { company, category: newCategory },
      {
        onSuccess: () => {
          setNewCompany("");
          setNewCategory(null);
        },
      }
    );
  };

  const handleAcceptSuggestion = (company: string, category: string) => {
    putOverrideMutation.mutate({ company, category });
  };

  const handleDismissSuggestion = (company: string, category: string) => {
    dismissMutation.mutate({ company, category });
  };

  return (
    <>
      {/* Suggestions section */}
      {suggestions.length > 0 && (
        <section className="space-y-3">
          <div className="flex items-center gap-2">
            <Lightbulb className="h-4 w-4 text-status-warning" />
            <h3 className="text-lg font-medium">Suggested Rules</h3>
            <Badge variant="secondary" className="text-xs">
              {suggestions.length}
            </Badge>
          </div>
          <p className="text-sm text-muted-foreground">Based on your manual category corrections</p>
          <div className="grid gap-2">
            {suggestions.map((s) => (
              <div
                key={s.company}
                className="flex items-center justify-between rounded-lg border border-border/50 px-4 py-3"
              >
                <div className="flex-1 min-w-0">
                  <span className="font-medium text-sm truncate block">{s.company}</span>
                  <span className="text-xs text-muted-foreground">
                    <Badge variant="outline" className="text-xs font-normal mr-1.5">
                      {s.suggested_category}
                    </Badge>
                    Based on {s.correction_count} correction{s.correction_count === 1 ? "" : "s"}
                  </span>
                </div>
                <div className="flex items-center gap-1.5 ml-3 shrink-0">
                  <button
                    onClick={() => handleDismissSuggestion(s.company, s.suggested_category)}
                    disabled={dismissMutation.isPending || putOverrideMutation.isPending}
                    className="rounded p-1.5 text-muted-foreground hover:text-status-warning hover:bg-status-warning/10 transition-colors"
                    title="Dismiss suggestion"
                  >
                    <EyeOff className="h-4 w-4" />
                  </button>
                  <button
                    onClick={() => handleAcceptSuggestion(s.company, s.suggested_category)}
                    disabled={putOverrideMutation.isPending || dismissMutation.isPending}
                    className="rounded p-1.5 text-muted-foreground hover:text-status-success hover:bg-status-success/10 transition-colors"
                    title="Accept suggestion"
                  >
                    <Check className="h-4 w-4" />
                  </button>
                </div>
              </div>
            ))}
          </div>
        </section>
      )}

      {/* Duplicates banner (Phase 4) */}
      <OverrideDuplicatesBanner />

      {/* Category Rules section */}
      <section className="space-y-4">
        <SettingsSectionHeader
          title="Category Rules"
          infoHint={{
            label: "About Category Rules",
            content:
              "Company-name → category mappings learned from your manual corrections. Applied to new transactions as they're ingested, skipping the AI categorizer. Existing transactions keep whatever category they were saved with — they are not retroactively recategorized.",
          }}
          count={overridesData?.count}
          countLabel="category rules"
          toolbar={
            <ListSearchInput
              id="settings-rules-search"
              value={search}
              onChange={setSearch}
              ariaLabel="Search category rules"
              placeholder="Search rules…"
            />
          }
        />

        {/* Add new rule form */}
        <div className="space-y-2">
          <div className="flex flex-col gap-2 rounded-lg border border-border/50 bg-muted/20 px-3 py-2 sm:flex-row sm:items-center">
            <Input
              id="settings-rules-new-company"
              placeholder="Company name"
              value={newCompany}
              onChange={(e) => setNewCompany(e.target.value)}
              className="h-8 flex-1 bg-background"
              onKeyDown={(e) => {
                if (e.key === "Enter") handleAddRule();
              }}
            />
            <CategoryPicker
              value={newCategory}
              onSelect={setNewCategory}
              placeholder="Select category…"
            />
            <div className="self-end sm:self-auto">
              <AddRowButton
                onClick={handleAddRule}
                disabled={!newCompany.trim() || !newCategory || putOverrideMutation.isPending}
                label="Add rule"
              />
            </div>
          </div>

          {/* Match hint — appears when a similar rule already exists */}
          {matchData && matchData.category && matchData.tier && matchData.matched_rule && (
            <MatchHint
              matchedRule={matchData.matched_rule}
              category={matchData.category}
              tier={matchData.tier}
              confidence={matchData.confidence ?? 0}
              candidates={matchData.candidates.slice(1)}
              expanded={hintExpanded}
              onToggleExpanded={() => setHintExpanded((v) => !v)}
              onApply={() => setNewCategory(matchData.category)}
              disabled={newCategory === matchData.category}
            />
          )}
        </div>

        {overridesLoading && (
          <div className="space-y-2">
            {Array.from({ length: 5 }).map((_, i) => (
              <Skeleton key={i} className="h-10 w-full" />
            ))}
          </div>
        )}

        {!overridesLoading && filteredOverrides.length === 0 && (
          <p className="py-6 text-center text-muted-foreground">
            {search ? "No rules match your search" : "No category rules configured"}
          </p>
        )}

        {!overridesLoading &&
          filteredOverrides.length > 0 &&
          (() => {
            const COLLAPSED_LIMIT = 4;
            const isSearching = search.length > 0;
            const showAll = isSearching || rulesExpanded;
            const visibleOverrides = showAll
              ? filteredOverrides
              : filteredOverrides.slice(0, COLLAPSED_LIMIT);
            const hiddenCount = filteredOverrides.length - COLLAPSED_LIMIT;

            return (
              <div className="space-y-2">
                <div className="rounded-xl border border-border/50">
                  <Table>
                    <TableHeader>
                      <TableRow>
                        <TableHead>Company</TableHead>
                        <TableHead>Category</TableHead>
                        <TableHead className="w-12" />
                      </TableRow>
                    </TableHeader>
                    <TableBody>
                      {visibleOverrides.map((o) => (
                        <TableRow key={o.company}>
                          <TableCell>
                            <span className="font-medium text-sm">{o.company}</span>
                          </TableCell>
                          <TableCell>
                            <CategoryPicker
                              value={o.category}
                              onSelect={(cat) =>
                                putOverrideMutation.mutate({ company: o.company, category: cat })
                              }
                            />
                          </TableCell>
                          <TableCell>
                            <DeleteRowButton
                              onClick={() => deleteOverrideMutation.mutate(o.company)}
                              disabled={deleteOverrideMutation.isPending}
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
                    totalCount={filteredOverrides.length}
                    entityPlural="rules"
                  />
                )}
              </div>
            );
          })()}
      </section>
    </>
  );
}

const TIER_LABELS: Record<OverrideMatchTier, string> = {
  exact: "Exact match",
  normalized: "Matches existing rule",
  alias: "Alias match",
  fuzzy: "Similar to",
};

function MatchHint({
  matchedRule,
  category,
  tier,
  confidence,
  candidates,
  expanded,
  onToggleExpanded,
  onApply,
  disabled,
}: {
  matchedRule: string;
  category: string;
  tier: OverrideMatchTier;
  confidence: number;
  candidates: {
    category: string;
    matched_rule: string;
    confidence: number;
    tier: OverrideMatchTier;
  }[];
  expanded: boolean;
  onToggleExpanded: () => void;
  onApply: () => void;
  disabled: boolean;
}) {
  const confidencePct = Math.round(confidence * 100);
  return (
    <div className="rounded-lg border border-status-info/30 bg-status-info/[0.04] px-3 py-2 text-sm">
      <div className="flex items-center gap-2">
        <Sparkles className="h-3.5 w-3.5 shrink-0 text-status-info" />
        <span className="flex-1 min-w-0 truncate text-muted-foreground">
          <span className="font-medium text-foreground">{TIER_LABELS[tier]}:</span>{" "}
          <span className="font-medium text-foreground">{matchedRule}</span> →{" "}
          <Badge variant="outline" className="text-xs font-normal mr-1">
            {category}
          </Badge>
          {tier === "fuzzy" && <span className="text-xs">({confidencePct}%)</span>}
        </span>
        <button
          type="button"
          onClick={onApply}
          disabled={disabled}
          className="shrink-0 rounded px-2 py-0.5 text-xs font-medium text-status-info hover:bg-status-info/15 disabled:opacity-40 disabled:hover:bg-transparent"
          aria-label={`Apply category ${category}`}
        >
          Apply
        </button>
        {candidates.length > 0 && (
          <button
            type="button"
            onClick={onToggleExpanded}
            className="shrink-0 rounded p-0.5 text-muted-foreground hover:text-foreground"
            aria-label={
              expanded ? "Hide other candidates" : `Show ${candidates.length} more candidate(s)`
            }
          >
            {expanded ? (
              <ChevronUp className="h-3.5 w-3.5" />
            ) : (
              <ChevronDown className="h-3.5 w-3.5" />
            )}
          </button>
        )}
      </div>
      {expanded && candidates.length > 0 && (
        <ul className="mt-1.5 space-y-0.5 pl-5 text-xs text-muted-foreground">
          {candidates.map((c) => (
            <li key={c.matched_rule} className="flex items-center gap-1">
              <span className="truncate">{c.matched_rule}</span>
              <span>→</span>
              <span>{c.category}</span>
              <span className="ml-auto shrink-0">{Math.round(c.confidence * 100)}%</span>
            </li>
          ))}
        </ul>
      )}
    </div>
  );
}
