import { useState, useRef, useCallback, useMemo } from "react";
import { CategoryPicker } from "@/components/CategoryPicker";
import { ReviewSection, type ReviewColumn } from "@/components/ReviewSection";
import { Badge } from "@/components/ui/badge";
import { Button } from "@/components/ui/button";
import { Card, CardContent } from "@/components/ui/card";
import { Input } from "@/components/ui/input";
import { useUpdateTransactionAction } from "@/hooks/useStatement";
import { titleCase, formatCurrency } from "@/lib/format";
import {
  assembleImportActions,
  bulkSetSectionAction,
  classifyUpdate,
  countAction,
  initRowStates,
  mergeRow,
  someActionNot,
  summarizeStates,
  type RowUpdate,
  type SectionKey,
} from "@/lib/statementReviewRows";
import type {
  StatementUploadResponse,
  ImportAction,
  TransactionActionUpdate,
  AmbiguousItem,
  MatchedItem,
  NewItem,
  PreviouslyImportedItem,
  SuspectedDuplicateItem,
} from "@/types/api";

type RowActionType = TransactionActionUpdate["action"];

interface StatementReviewProps {
  data: StatementUploadResponse;
  onImport: (actions: ImportAction[]) => void;
  isImporting: boolean;
  statementId?: string | null;
}

interface RowSelectCheckboxProps {
  checked: boolean;
  onChange: (checked: boolean) => void;
  label: string;
}

function RowSelectCheckbox({ checked, onChange, label }: RowSelectCheckboxProps) {
  return (
    <label className="inline-flex cursor-pointer items-center gap-2 select-none">
      <input
        type="checkbox"
        checked={checked}
        onChange={(e) => onChange(e.target.checked)}
        className="h-4 w-4 cursor-pointer accent-brand"
        aria-label={checked ? `Deselect (will skip)` : `Select (${label.toLowerCase()})`}
      />
      <span
        className={`text-xs font-medium ${checked ? "text-foreground" : "text-muted-foreground"}`}
      >
        {checked ? label : "Skip"}
      </span>
    </label>
  );
}

export function StatementReview({
  data,
  onImport,
  isImporting,
  statementId,
}: StatementReviewProps) {
  // Index-to-row_id translation. The internal state keys remain the
  // positional `index` (cheap, doesn't shift between save calls within
  // the review session), but every API call goes through `row_id` —
  // the canonical, drift-resistant id from the Tier 2 migration.
  const rowIdByIndex = useMemo(() => {
    const map = new Map<number, string>();
    for (const bucket of [
      data.matched,
      data.ambiguous,
      data.new,
      data.previously_imported || [],
      data.suspected_duplicates || [],
    ]) {
      for (const item of bucket) {
        map.set(item.index, item.row_id);
      }
    }
    return map;
  }, [data]);

  const [matchedOpen, setMatchedOpen] = useState(false);
  const [prevImportedOpen, setPrevImportedOpen] = useState(false);
  // Single flat row-state map keyed by positional index (unique across buckets);
  // each value carries its `section` discriminant. See lib/statementReviewRows.
  const [states, setStates] = useState(() => initRowStates(data));

  // Auto-save mutation
  const autoSave = useUpdateTransactionAction(statementId ?? null);
  const debounceTimers = useRef<Record<string, ReturnType<typeof setTimeout>>>({});

  const saveAction = useCallback(
    (txIndex: number, action: RowActionType, company?: string, category?: string) => {
      if (!statementId) return;
      const rowId = rowIdByIndex.get(txIndex);
      if (!rowId) return;
      autoSave.mutate({
        rowId,
        data: {
          action,
          ...(company !== undefined ? { company } : {}),
          ...(category !== undefined ? { category } : {}),
        },
      });
    },
    [statementId, autoSave, rowIdByIndex]
  );

  const debouncedSave = useCallback(
    (txIndex: number, action: RowActionType, company?: string, category?: string) => {
      if (!statementId) return;
      const key = `${txIndex}`;
      if (debounceTimers.current[key]) {
        clearTimeout(debounceTimers.current[key]);
      }
      debounceTimers.current[key] = setTimeout(() => {
        saveAction(txIndex, action, company, category);
        Reflect.deleteProperty(debounceTimers.current, key);
      }, 300);
    },
    [statementId, saveAction]
  );

  // Merge `updates` into the row at `index`, dispatch the save keyed to which
  // field changed (action/category → immediate, company → 300ms debounce), and
  // return the new state. `prev[index]` is only undefined for invalid callers.
  const updateRow = useCallback(
    (index: number, updates: RowUpdate) => {
      setStates((prev) => {
        const current = prev[index];
        if (!current) return prev;
        const row = mergeRow(current, updates);
        const mode = classifyUpdate(updates);
        if (mode === "immediate") {
          saveAction(index, row.action, row.company, row.category);
        } else if (mode === "debounced") {
          debouncedSave(index, row.action, row.company, row.category);
        }
        return { ...prev, [index]: row };
      });
    },
    [saveAction, debouncedSave]
  );

  // Bulk-set a section's rows to `action`. For each row whose action actually
  // changes, fire saveAction so the backend stays in sync — the per-row
  // updateRow path is bypassed by setState, so saves are dispatched explicitly.
  const bulkSet = useCallback(
    (section: SectionKey, action: RowActionType) => {
      setStates((prev) => {
        const { next, changed } = bulkSetSectionAction(prev, section, action);
        for (const idx of changed) {
          const row = prev[idx];
          if (row) saveAction(idx, action, row.company, row.category);
        }
        return next;
      });
    },
    [saveAction]
  );

  const handleSubmit = () => onImport(assembleImportActions(data, states));

  const { importCount, enrichCount, updateCount } = summarizeStates(states);
  const matchedEnrichable = countAction(states, "matched", "enrich");
  const hasActions = importCount > 0 || enrichCount > 0 || updateCount > 0;

  const buttonLabel = (() => {
    const parts: string[] = [];
    if (importCount > 0) parts.push(`Import ${importCount}`);
    if (enrichCount > 0) parts.push(`Enrich ${enrichCount}`);
    if (updateCount > 0) parts.push(`Update ${updateCount}`);
    return parts.join(" / ") || "Nothing selected";
  })();

  // --- Per-section column configs -----------------------------------------
  const editableCompanyCategory = <Item extends { index: number }>(): ReviewColumn<Item>[] => [
    {
      header: "New Company",
      render: (item, state) => (
        <Input
          value={state.company}
          onChange={(e) => updateRow(item.index, { company: e.target.value })}
          className="h-7 text-sm w-[180px]"
          disabled={state.action === "skip"}
        />
      ),
    },
    {
      header: "New Category",
      render: (item, state) => (
        <CategoryPicker
          value={state.category ? titleCase(state.category) : null}
          onSelect={(cat) => updateRow(item.index, { category: cat.toLowerCase() })}
          disabled={state.action === "skip"}
        />
      ),
    },
  ];

  const prevColumns: ReviewColumn<PreviouslyImportedItem>[] = [
    {
      header: "Date",
      cellClassName: "text-xs text-muted-foreground whitespace-nowrap",
      render: (p) => p.statement_txn.date,
    },
    { header: "Statement Description", cellClassName: "text-sm", render: (p) => p.raw_description },
    {
      header: "Amount",
      headerClassName: "text-right",
      cellClassName: "text-right font-mono text-sm",
      render: (p) => formatCurrency(p.statement_txn.amount),
    },
    { header: "DB Company", cellClassName: "text-sm", render: (p) => p.db_match.company },
    {
      header: "Category",
      render: (p) => (
        <Badge variant="secondary" className="text-xs font-normal">
          {p.db_match.category}
        </Badge>
      ),
    },
    ...editableCompanyCategory<PreviouslyImportedItem>(),
    {
      header: "Action",
      render: (p, state) => (
        <RowSelectCheckbox
          checked={state.action === "update"}
          onChange={(c) => updateRow(p.index, { action: c ? "update" : "skip" })}
          label="Update"
        />
      ),
    },
  ];

  const matchedColumns: ReviewColumn<MatchedItem>[] = [
    {
      header: "Date",
      cellClassName: "text-xs text-muted-foreground whitespace-nowrap",
      render: (m) => m.statement_txn.date,
    },
    { header: "Statement Description", cellClassName: "text-sm", render: (m) => m.raw_description },
    {
      header: "Amount",
      headerClassName: "text-right",
      cellClassName: "text-right font-mono text-sm",
      render: (m) => formatCurrency(m.statement_txn.amount),
    },
    { header: "DB Company", cellClassName: "text-sm", render: (m) => m.db_match.company },
    {
      header: "Category",
      render: (m) => (
        <Badge variant="secondary" className="text-xs font-normal">
          {m.db_match.category}
        </Badge>
      ),
    },
    ...editableCompanyCategory<MatchedItem>(),
    {
      header: "Action",
      render: (m, state) => (
        <RowSelectCheckbox
          checked={state.action === "enrich"}
          onChange={(c) => updateRow(m.index, { action: c ? "enrich" : "skip" })}
          label="Enrich"
        />
      ),
    },
  ];

  const ambiguousColumns: ReviewColumn<AmbiguousItem>[] = [
    {
      header: "Date",
      cellClassName: "text-xs text-muted-foreground whitespace-nowrap",
      render: (a) => a.statement_txn.date,
    },
    {
      header: "Description",
      cellClassName: "text-sm",
      render: (a) => a.raw_description || a.statement_txn.description,
    },
    {
      header: "Amount",
      headerClassName: "text-right",
      cellClassName: "text-right font-mono text-sm",
      render: (a) => formatCurrency(a.statement_txn.amount),
    },
    {
      header: "DB Company",
      cellClassName: "text-xs",
      render: (a) => a.candidates.map((c) => c.company || "—").join(", "),
    },
    {
      header: "Reason",
      render: (a) => (
        <Badge variant="outline" className="text-xs">
          {a.reason}
        </Badge>
      ),
    },
    {
      header: "New Company",
      render: (a, state) => (
        <Input
          value={state.company}
          onChange={(e) => updateRow(a.index, { company: e.target.value })}
          className="h-7 text-sm w-[180px]"
          disabled={state.action === "skip"}
        />
      ),
    },
    {
      header: "Category",
      render: (a, state) => (
        <CategoryPicker
          value={state.category ? titleCase(state.category) : null}
          onSelect={(cat) => updateRow(a.index, { category: cat.toLowerCase() })}
          disabled={state.action === "skip"}
        />
      ),
    },
    {
      header: "Action",
      render: (a, state) => (
        <RowSelectCheckbox
          checked={state.action === "enrich"}
          onChange={(c) => updateRow(a.index, { action: c ? "enrich" : "skip" })}
          label="Enrich"
        />
      ),
    },
  ];

  const suspectedDupColumns: ReviewColumn<SuspectedDuplicateItem>[] = [
    {
      header: "Date",
      cellClassName: "text-xs text-muted-foreground whitespace-nowrap",
      render: (sd) => sd.statement_txn.date,
    },
    {
      header: "Statement Description",
      cellClassName: "text-sm",
      render: (sd) => sd.raw_description,
    },
    {
      header: "Amount",
      headerClassName: "text-right",
      cellClassName: "text-right font-mono text-sm",
      render: (sd) => formatCurrency(sd.statement_txn.amount),
    },
    { header: "DB Company", cellClassName: "text-sm", render: (sd) => sd.db_match.company },
    {
      header: "DB Type",
      render: (sd) => (
        <Badge variant="secondary" className="bg-status-warning-muted text-status-warning text-xs">
          {sd.db_match.transaction_type}
        </Badge>
      ),
    },
    {
      header: "DB Category",
      render: (sd) => (
        <Badge variant="secondary" className="text-xs font-normal">
          {sd.db_match.category}
        </Badge>
      ),
    },
    {
      header: "Reason",
      render: (sd) => (
        <Badge variant="outline" className="text-xs">
          {sd.reason}
        </Badge>
      ),
    },
    {
      header: "Action",
      render: (sd, state) => (
        <RowSelectCheckbox
          checked={state.action === "import"}
          onChange={(c) => updateRow(sd.index, { action: c ? "import" : "skip" })}
          label="Import"
        />
      ),
    },
  ];

  const newColumns: ReviewColumn<NewItem>[] = [
    {
      header: "Date",
      cellClassName: "text-xs text-muted-foreground whitespace-nowrap",
      render: (n) => n.statement_txn.date,
    },
    {
      header: "Raw Description",
      cellClassName: "text-xs text-muted-foreground max-w-[200px] truncate",
      render: (n) => n.raw_description,
    },
    {
      header: "Company Name",
      render: (n, state) => (
        <Input
          value={state.company}
          onChange={(e) => updateRow(n.index, { company: e.target.value })}
          className="h-7 text-sm w-[180px]"
        />
      ),
    },
    {
      header: "Amount",
      headerClassName: "text-right",
      cellClassName: "text-right font-mono text-sm",
      render: (n) => formatCurrency(n.statement_txn.amount),
    },
    {
      header: "Type",
      render: (n) => (
        <Badge variant="outline" className="text-xs">
          {n.statement_txn.type}
        </Badge>
      ),
    },
    {
      header: "Category",
      render: (n, state) => (
        <CategoryPicker
          value={state.category ? titleCase(state.category) : null}
          onSelect={(cat) => updateRow(n.index, { category: cat.toLowerCase() })}
        />
      ),
    },
    {
      header: "Action",
      render: (n, state) => (
        <RowSelectCheckbox
          checked={state.action === "import"}
          onChange={(c) => updateRow(n.index, { action: c ? "import" : "skip" })}
          label="Import"
        />
      ),
    },
  ];

  return (
    <div className="space-y-4">
      {/* Summary card */}
      <Card className="border-border/50">
        <CardContent className="p-4 space-y-3">
          <div className="flex flex-wrap items-center gap-3">
            <span className="text-sm font-medium">Reconciliation Summary</span>
            <Badge variant="secondary">{data.summary.matched_count} matched</Badge>
            {data.summary.ambiguous_count > 0 && (
              <Badge variant="secondary" className="bg-status-warning-muted text-status-warning">
                {data.summary.ambiguous_count} ambiguous
              </Badge>
            )}
            {(data.summary.suspected_duplicate_count || 0) > 0 && (
              <Badge variant="secondary" className="bg-status-warning-muted text-status-warning">
                {data.summary.suspected_duplicate_count} suspected dups
              </Badge>
            )}
            <Badge variant="secondary">{data.summary.new_count} new</Badge>
            {(data.summary.previously_imported_count || 0) > 0 && (
              <Badge variant="secondary">
                {data.summary.previously_imported_count} previously imported
              </Badge>
            )}
            <span className="text-xs text-muted-foreground">
              {data.summary.total_parsed} total parsed
            </span>
          </div>
          {(() => {
            const s = data.summary;
            const importedN = s.imported_count ?? 0;
            const enrichedN = s.enriched_count ?? 0;
            const updatedN = s.updated_count ?? 0;
            const skippedN = s.skipped_count ?? 0;
            const dupN = s.duplicate_count ?? 0;
            if (importedN + enrichedN + updatedN + skippedN + dupN === 0) return null;
            return (
              <div className="flex flex-wrap items-center gap-3 border-t pt-3">
                <span className="text-sm font-medium">Import outcome</span>
                {importedN > 0 && (
                  <Badge
                    variant="secondary"
                    className="bg-status-success-muted text-status-success"
                  >
                    {importedN} imported
                  </Badge>
                )}
                {enrichedN > 0 && (
                  <Badge variant="secondary" className="bg-status-info-muted text-status-info">
                    {enrichedN} enriched
                  </Badge>
                )}
                {updatedN > 0 && (
                  <Badge variant="secondary" className="bg-status-info-muted text-status-info">
                    {updatedN} updated
                  </Badge>
                )}
                {skippedN > 0 && <Badge variant="secondary">{skippedN} skipped</Badge>}
                {dupN > 0 && (
                  <Badge
                    variant="secondary"
                    className="bg-status-warning-muted text-status-warning"
                  >
                    {dupN} duplicate
                  </Badge>
                )}
              </div>
            );
          })()}
        </CardContent>
      </Card>

      {/* Previously Imported section */}
      <ReviewSection
        title="Previously Imported"
        count={(data.previously_imported || []).length}
        items={data.previously_imported || []}
        states={states}
        columns={prevColumns}
        rowClassName={(_p, state) => (state.action === "skip" ? "" : "bg-status-warning-muted/50")}
        collapsible={{
          open: prevImportedOpen,
          onOpenChange: setPrevImportedOpen,
          badge: updateCount > 0 && (
            <Badge
              variant="secondary"
              className="bg-status-warning-muted text-status-warning text-xs ml-1"
            >
              {updateCount} to update
            </Badge>
          ),
        }}
      />

      {/* Matched section */}
      <ReviewSection
        title="Matched Transactions"
        count={data.matched.length}
        items={data.matched}
        states={states}
        columns={matchedColumns}
        rowClassName={(m) => (m.company_differs ? "bg-status-warning-muted/50" : "")}
        collapsible={{
          open: matchedOpen,
          onOpenChange: setMatchedOpen,
          badge: matchedEnrichable > 0 && (
            <Badge
              variant="secondary"
              className="bg-status-info-muted text-status-info text-xs ml-1"
            >
              {matchedEnrichable} enrichable
            </Badge>
          ),
        }}
      />

      {/* Ambiguous section */}
      <ReviewSection
        title="Ambiguous Transactions"
        count={data.ambiguous.length}
        items={data.ambiguous}
        states={states}
        columns={ambiguousColumns}
        rowClassName={(_a, state) => (state.action === "skip" ? "opacity-40" : "")}
        bulk={
          countAction(states, "ambiguous", "enrich") + countAction(states, "ambiguous", "skip") >
            0 && (
            <div className="flex gap-1">
              <Button
                variant="outline"
                size="sm"
                onClick={() => bulkSet("ambiguous", "enrich")}
                disabled={!someActionNot(states, "ambiguous", "enrich")}
              >
                Enrich All
              </Button>
              <Button
                variant="ghost"
                size="sm"
                onClick={() => bulkSet("ambiguous", "skip")}
                disabled={!someActionNot(states, "ambiguous", "skip")}
              >
                Skip All
              </Button>
            </div>
          )
        }
      />

      {/* Suspected Duplicates section */}
      <ReviewSection
        title="Suspected Duplicates"
        count={(data.suspected_duplicates || []).length}
        items={data.suspected_duplicates || []}
        states={states}
        columns={suspectedDupColumns}
        rowClassName={(_sd, state) => (state.action === "skip" ? "bg-status-warning-muted/50" : "")}
        bulk={
          <div className="flex gap-1">
            <Button
              variant="outline"
              size="sm"
              onClick={() => bulkSet("suspected_duplicates", "import")}
              disabled={!someActionNot(states, "suspected_duplicates", "import")}
            >
              Import All
            </Button>
            <Button
              variant="ghost"
              size="sm"
              onClick={() => bulkSet("suspected_duplicates", "skip")}
              disabled={!someActionNot(states, "suspected_duplicates", "skip")}
            >
              Skip All
            </Button>
          </div>
        }
      />

      {/* New transactions section */}
      <ReviewSection
        title="New Transactions"
        count={data.new.length}
        items={data.new}
        states={states}
        columns={newColumns}
        rowClassName={(_n, state) => (state.action === "skip" ? "opacity-40" : "")}
        bulk={
          <div className="flex gap-1">
            <Button
              variant="outline"
              size="sm"
              onClick={() => bulkSet("new", "import")}
              disabled={!someActionNot(states, "new", "import")}
            >
              Import All
            </Button>
            <Button
              variant="ghost"
              size="sm"
              onClick={() => bulkSet("new", "skip")}
              disabled={!someActionNot(states, "new", "skip")}
            >
              Skip All
            </Button>
          </div>
        }
      />

      {/* Sticky submit bar */}
      {hasActions && (
        <div className="sticky bottom-0 z-10 bg-background border-t p-4 -mx-4">
          <div className="flex items-center justify-between">
            <div className="flex items-center gap-3 text-sm text-muted-foreground">
              {importCount > 0 && (
                <span className="flex items-center gap-1.5">
                  <span className="h-2 w-2 rounded-full bg-status-success" />
                  {importCount} to import
                </span>
              )}
              {enrichCount > 0 && (
                <span className="flex items-center gap-1.5">
                  <span className="h-2 w-2 rounded-full bg-status-info" />
                  {enrichCount} to enrich
                </span>
              )}
              {updateCount > 0 && (
                <span className="flex items-center gap-1.5">
                  <span className="h-2 w-2 rounded-full bg-status-warning" />
                  {updateCount} to update
                </span>
              )}
            </div>
            <Button onClick={handleSubmit} disabled={isImporting} size="lg">
              {isImporting ? "Processing..." : buttonLabel}
            </Button>
          </div>
        </div>
      )}
    </div>
  );
}
