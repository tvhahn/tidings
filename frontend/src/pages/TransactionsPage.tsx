import { Loader2, Paperclip, Trash2 } from "lucide-react";
import { useCallback, useEffect, useMemo, useState } from "react";
import { useSearchParams, useNavigate } from "react-router-dom";
import { toast } from "sonner";
import { AddTransactionDialog } from "@/components/AddTransactionDialog";
import { AdvancedSearchPanel, type RangeDraft } from "@/components/AdvancedSearchPanel";
import { ReceiptReview } from "@/components/AttachmentCaptureDialog";
import { AttachmentViewDialog } from "@/components/AttachmentViewDialog";
import { AttentionQueue } from "@/components/AttentionQueue";
import { CategoryPicker } from "@/components/CategoryPicker";
import { EmailPreviewDialog } from "@/components/EmailPreviewDialog";
import { FilterBar } from "@/components/FilterBar";
import { MobileSortControl } from "@/components/MobileSortControl";
import { MonthPicker } from "@/components/MonthPicker";
import { PageHeader } from "@/components/PageHeader";
import { QueryErrorNotice } from "@/components/QueryErrorNotice";
import { TransactionCard } from "@/components/TransactionCard";
import { TransactionTable } from "@/components/TransactionTable";
import {
  Dialog,
  DialogContent,
  DialogDescription,
  DialogHeader,
  DialogTitle,
} from "@/components/ui/dialog";
import { Skeleton } from "@/components/ui/skeleton";
import { useCategoryGroups } from "@/hooks/useCategoryGroups";
import { useDeleteAttachment } from "@/hooks/useDeleteAttachment";
import { useMarkReviewed } from "@/hooks/useMarkReviewed";
import { useMediaQuery } from "@/hooks/useMediaQuery";
import { useMonthParam } from "@/hooks/useMonthParam";
import { usePrefetchMonth } from "@/hooks/usePrefetchMonth";
import { useTransactions } from "@/hooks/useTransactions";
import { useTransactionSearch } from "@/hooks/useTransactionSearch";
import { useUnlinkedAttachments } from "@/hooks/useUnlinkedAttachments";
import { useUpdateCategory } from "@/hooks/useUpdateCategory";
import { formatBytes } from "@/lib/attachments";
import { applyFilters, DEFAULT_FILTERS, type Filters } from "@/lib/filters";
import { formatCurrency, formatRelativeTime } from "@/lib/format";
import { sortTransactions, DEFAULT_SORT, type SortConfig } from "@/lib/sort";
import { searchParamsFromUrl, toRangeUrlParams } from "@/lib/transactionSearchParams";
import { makeKey } from "@/stores/editedTransactions";
import type { AttachmentResponse, SearchParams, Transaction } from "@/types/api";

// Stable empty-array reference so the memoized filter/sort don't see a fresh []
// on every render while data is loading.
const EMPTY_TRANSACTIONS: Transaction[] = [];

export function TransactionsPage() {
  const [searchParams, setSearchParams] = useSearchParams();
  const categoryParam = searchParams.get("category");
  const groupParam = searchParams.get("group");
  const resetParam = searchParams.has("reset");

  // Range mode: the URL carries BOTH `from` and `to`, so the page swaps the
  // fast single-month view for a server-backed cross-month search. `rangeParams`
  // is null in month mode, which keeps `useTransactionSearch` disabled.
  const rangeParams = useMemo(() => searchParamsFromUrl(searchParams), [searchParams]);
  const rangeMode = rangeParams !== null;

  const [month, setMonth] = useMonthParam();
  // Urgent header mirror (see JournalPage): React Router v7 wraps the URL month
  // change in a transition, so `month` (which drives the table data) updates at
  // low priority; `displayMonth` updates urgently so the header + MonthPicker
  // flip on the click's first frame while the table catches up a beat later.
  const [displayMonth, setDisplayMonth] = useState(month);
  useEffect(() => {
    setDisplayMonth(month);
  }, [month]);
  // Advanced-search panel: auto-expanded in range mode or via `?advanced`;
  // otherwise collapsed until the user opens it. Export lives inside, so it is
  // reachable in both modes.
  const [advancedOpen, setAdvancedOpen] = useState(() => rangeMode || searchParams.has("advanced"));

  const changeMonth = useCallback(
    (next: string) => {
      setDisplayMonth(next);
      if (rangeMode) {
        // Changing the header month in range mode exits range mode for that
        // month (same effect as "Back to this month").
        setAdvancedOpen(false);
        setSearchParams(() => {
          const p = new URLSearchParams();
          p.set("month", next);
          return p;
        });
      } else {
        setMonth(next);
      }
    },
    [rangeMode, setMonth, setSearchParams]
  );
  const [filters, setFilters] = useState<Filters>(() => ({
    ...DEFAULT_FILTERS,
    category: groupParam ? "all" : categoryParam || "all",
    categoryGroup: groupParam || undefined,
    // Range mode hydrates its committed filters from the URL on mount.
    institution: searchParams.get("institution") || "all",
    search: searchParams.get("q") || "",
  }));

  // Sync drill-down filter params from URL (e.g. from Summary page). Skipped in
  // range mode, where `category` is a persistent server filter (not a one-shot
  // drill-down) and must survive in the URL.
  useEffect(() => {
    if (rangeMode) return;
    if (resetParam) {
      setFilters(DEFAULT_FILTERS);
    } else if (groupParam) {
      setFilters((f) => ({ ...f, category: "all", categoryGroup: groupParam }));
    } else if (categoryParam) {
      setFilters((f) => ({ ...f, category: categoryParam, categoryGroup: undefined }));
    }
    // Clear drill-down params after applying so back-navigation is clean
    if (categoryParam || groupParam || resetParam) {
      setSearchParams(
        (prev) => {
          const p = new URLSearchParams(prev);
          p.delete("category");
          p.delete("group");
          p.delete("reset");
          return p;
        },
        { replace: true }
      );
    }
  }, [rangeMode, categoryParam, groupParam, resetParam, setSearchParams]);

  const navigate = useNavigate();
  const { data, isLoading, isFetching, trashCount, isError, error, refetch } =
    useTransactions(month);
  const { groups } = useCategoryGroups();
  usePrefetchMonth(month);
  const [sort, setSort] = useState<SortConfig>(DEFAULT_SORT);
  const transactions = data?.transactions ?? EMPTY_TRANSACTIONS;
  // Memoized so the urgent header-flip render (displayMonth changed, URL `month`
  // not yet) yields stable refs → the memoized TransactionTable bails and stays
  // off the critical path; recomputed only when data/filters/sort change.
  const filtered = useMemo(
    () => applyFilters(transactions, filters, groups),
    [transactions, filters, groups]
  );
  const sorted = useMemo(() => sortTransactions(filtered, sort), [filtered, sort]);
  const isNavPending = displayMonth !== month || isFetching;
  // Render one layout at a time (table OR cards), not both CSS-hidden trees.
  const isDesktop = useMediaQuery("(min-width: 768px)");

  // Range mode: server-backed cross-month search. The server already applied
  // q/category/institution/type/amount/visibility; client-side we only run the
  // light FilterBar toggles (hide deposits / hide ignored) and the sort.
  const {
    data: searchData,
    isLoading: searchLoading,
    isError: searchIsError,
    error: searchError,
    refetch: searchRefetch,
  } = useTransactionSearch(rangeParams);
  const rangeLightFilters = useMemo<Filters>(
    () => ({
      ...DEFAULT_FILTERS,
      hideDeposits: filters.hideDeposits,
      hideIgnored: filters.hideIgnored,
    }),
    [filters.hideDeposits, filters.hideIgnored]
  );
  const rangeResults = searchData?.transactions ?? EMPTY_TRANSACTIONS;
  const rangeFiltered = useMemo(
    () => applyFilters(rangeResults, rangeLightFilters, groups),
    [rangeResults, rangeLightFilters, groups]
  );
  const rangeSorted = useMemo(() => sortTransactions(rangeFiltered, sort), [rangeFiltered, sort]);

  // Panel wiring. Month-mode export targets the current month + active filters;
  // range-mode export replays the committed (uncapped) query.
  const monthExportParams = useMemo<SearchParams>(() => {
    const p: SearchParams = { from: month, to: month, include_ignored: true };
    const q = filters.search.trim();
    if (q) p.q = q;
    if (filters.category !== "all") p.category = filters.category;
    if (filters.institution !== "all") p.institution = filters.institution;
    return p;
  }, [month, filters.search, filters.category, filters.institution]);
  const exportParams = rangeMode ? rangeParams : monthExportParams;
  const initialDraft = useMemo<RangeDraft>(
    () => ({
      // Seed the range from the month being viewed, not today, so opening the
      // panel in month mode offers "this month" as the default range.
      from: searchParams.get("from") ?? month,
      to: searchParams.get("to") ?? month,
      type: searchParams.get("type") ?? "all",
      min: searchParams.get("min") ?? "",
      max: searchParams.get("max") ?? "",
      includeIgnored: searchParams.get("ignored") === "1" || searchParams.get("ignored") === "true",
      includeTrash: searchParams.get("trash") === "1" || searchParams.get("trash") === "true",
    }),
    [searchParams, month]
  );
  const handleRangeCommit = useCallback(
    (params: SearchParams) => {
      setAdvancedOpen(true);
      setSearchParams(() => {
        const p = toRangeUrlParams(params);
        // Preserve the anchor month so "Back to this month" can restore it.
        p.set("month", month);
        return p;
      });
    },
    [month, setSearchParams]
  );
  const handleBackToMonth = useCallback(() => {
    setAdvancedOpen(false);
    setSearchParams(() => {
      const p = new URLSearchParams();
      p.set("month", month);
      return p;
    });
  }, [month, setSearchParams]);

  const { mutate: markReviewed } = useMarkReviewed();
  const handleConfirm = useCallback(
    (txn: Transaction) => {
      markReviewed({ forwardedTo: txn.forwarded_to, dateFileName: txn.date_file_name });
    },
    [markReviewed]
  );

  const [emailPreviewTxn, setEmailPreviewTxn] = useState<Transaction | null>(null);
  const [emailPreviewOpen, setEmailPreviewOpen] = useState(false);
  const handleEmailPreview = useCallback((txn: Transaction) => {
    setEmailPreviewTxn(txn);
    setEmailPreviewOpen(true);
  }, []);

  // Receipts uploaded but not yet filed against a transaction. A quiet
  // affordance, not a badge — surfaced only when the count is non-zero.
  const { data: unlinkedData } = useUnlinkedAttachments();
  const unlinked = unlinkedData?.attachments ?? [];
  const deleteAttachment = useDeleteAttachment();
  const [receiptsOpen, setReceiptsOpen] = useState(false);
  const [viewAttachment, setViewAttachment] = useState<AttachmentResponse | null>(null);
  // The receipt currently being filed (parse → match → link) from the list.
  const [fileAttachment, setFileAttachment] = useState<AttachmentResponse | null>(null);

  // Multi-select / bulk-categorize. Selection lives at page level so the
  // toolbar above the table can act on it. Resets when the visible-rows
  // identity changes (different month or filter).
  const updateCategory = useUpdateCategory();
  const [selected, setSelected] = useState<Set<string>>(new Set());
  const sortedKeys = useMemo(
    () => sorted.map((t) => makeKey(t.forwarded_to, t.date_file_name)),
    [sorted]
  );
  useEffect(() => {
    // Drop selections that no longer correspond to a visible row.
    setSelected((prev) => {
      const visible = new Set(sortedKeys);
      const next = new Set<string>();
      prev.forEach((k) => visible.has(k) && next.add(k));
      return next.size === prev.size ? prev : next;
    });
  }, [sortedKeys]);
  const onToggle = useCallback(
    (key: string) =>
      setSelected((prev) => {
        const next = new Set(prev);
        if (next.has(key)) next.delete(key);
        else next.add(key);
        return next;
      }),
    []
  );
  const onToggleAll = useCallback(
    () =>
      setSelected((prev) => (prev.size === sortedKeys.length ? new Set() : new Set(sortedKeys))),
    [sortedKeys]
  );
  // Stable object so the memoized TransactionTable can bail during a month flip.
  const selectionMode = useMemo(
    () => ({ selected, onToggle, onToggleAll }),
    [selected, onToggle, onToggleAll]
  );
  const handleBulkCategorize = (newCategory: string) => {
    const targets = sorted.filter((t) => selected.has(makeKey(t.forwarded_to, t.date_file_name)));
    if (targets.length === 0) return;
    targets.forEach((t) => {
      const oldCategory = t.category || "miscellaneous";
      if (newCategory.toLowerCase() === oldCategory.toLowerCase()) return;
      updateCategory.mutate({
        forwardedTo: t.forwarded_to,
        dateFileName: t.date_file_name,
        category: newCategory,
        oldCategory,
      });
    });
    toast(`Category updated to ${newCategory} for ${targets.length} transactions`);
    setSelected(new Set());
  };

  return (
    <div className="space-y-6">
      <PageHeader
        title="Transactions"
        titleAdornment={<AddTransactionDialog />}
        actions={
          <MonthPicker
            month={displayMonth}
            onChange={changeMonth}
            loading={isNavPending && !!data}
          />
        }
      />

      {/* Attention queue — anchored to the single month; hidden while browsing a
          cross-month range. */}
      {!rangeMode && <AttentionQueue month={month} onEmailPreview={handleEmailPreview} />}

      {/* Filters */}
      <FilterBar
        filters={filters}
        onChange={setFilters}
        transactions={rangeMode ? rangeResults : transactions}
      />

      {/* Advanced search — month range, power filters, and CSV export inline.
          Keyed by the committed range so the draft re-hydrates from the URL when
          the searched range changes (e.g. a deep-link navigation). */}
      <AdvancedSearchPanel
        key={`adv-${searchParams.get("from") ?? ""}-${searchParams.get("to") ?? ""}`}
        open={advancedOpen}
        onOpenChange={setAdvancedOpen}
        rangeMode={rangeMode}
        filters={filters}
        initialDraft={initialDraft}
        onCommit={handleRangeCommit}
        exportParams={exportParams}
        onBackToMonth={handleBackToMonth}
      />

      {/* Range summary strip — results count, total, average, months queried. */}
      {rangeMode && searchData && (
        <div className="rounded-[14px] border border-border bg-surface-muted px-5 py-3">
          <div className="flex flex-wrap items-center gap-6 text-[13px]">
            <div>
              <span className="text-muted-foreground">Results: </span>
              <span className="font-medium tabular-nums">
                {rangeSorted.length < rangeResults.length
                  ? `${rangeSorted.length} (of ${rangeResults.length})`
                  : rangeSorted.length}
              </span>
            </div>
            <div>
              <span className="text-muted-foreground">Total: </span>
              <span className="font-medium tabular-nums">
                {formatCurrency(searchData.summary.total_amount)}
              </span>
            </div>
            <div>
              <span className="text-muted-foreground">Average: </span>
              <span className="font-medium tabular-nums">
                {formatCurrency(searchData.summary.avg_amount)}
              </span>
            </div>
            <div>
              <span className="text-muted-foreground">Months: </span>
              <span className="font-medium tabular-nums">{searchData.summary.months_queried}</span>
            </div>
          </div>
        </div>
      )}

      {/* Capped notice — uses the live returned count, not a fixed cap. */}
      {rangeMode && searchData?.capped && (
        <div className="rounded-[14px] border border-border bg-card px-5 py-3">
          <p className="text-[10.5px] font-medium uppercase tracking-[0.08em] text-fg-muted">
            Notice
          </p>
          <p className="mt-1 text-[13px] text-fg">
            Showing {searchData.transactions.length.toLocaleString()} of{" "}
            {searchData.total_matching.toLocaleString()} results. Export CSV for the full set.
          </p>
        </div>
      )}

      {/* Transaction count + bulk-categorize toolbar */}
      {!rangeMode && data && (
        <div className="flex flex-wrap items-center justify-between gap-3">
          {selected.size > 0 ? (
            <div className="flex items-center gap-3">
              <p className="text-sm font-medium text-fg">{selected.size} selected</p>
              <CategoryPicker variant="inline" value={null} onSelect={handleBulkCategorize} />
              <button
                onClick={() => setSelected(new Set())}
                className="text-sm text-fg-muted hover:text-fg transition-colors"
              >
                Cancel
              </button>
            </div>
          ) : (
            <p className="text-sm text-fg-muted">
              {filtered.length} transaction{filtered.length !== 1 ? "s" : ""}
              {filtered.length !== transactions.length && ` (of ${transactions.length})`}
            </p>
          )}
          <div className="flex items-center gap-4">
            {unlinked.length > 0 && (
              <button
                onClick={() => setReceiptsOpen(true)}
                className="flex items-center gap-1 text-sm text-fg-muted hover:text-fg transition-colors"
              >
                <Paperclip className="h-3.5 w-3.5" />
                <span>Receipts to file ({unlinked.length})</span>
              </button>
            )}
            {trashCount > 0 && (
              <button
                onClick={() => navigate("/transactions/trash")}
                className="flex items-center gap-1 text-sm text-fg-muted hover:text-fg transition-colors"
              >
                <Trash2 className="h-3.5 w-3.5" />
                <span>{trashCount} in trash</span>
              </button>
            )}
          </div>
        </div>
      )}

      {/* Loading */}
      {!rangeMode && isLoading && !data && (
        <div className="space-y-2">
          {Array.from({ length: 8 }).map((_, i) => (
            <Skeleton key={i} className="h-12 w-full" />
          ))}
        </div>
      )}

      {/* Error state — a failed fetch must not look like an empty month. */}
      {!rangeMode && isError && !data && (
        <QueryErrorNotice error={error} onRetry={() => void refetch()} />
      )}

      {/* Desktop table — rendered only at md+ (one layout at a time, not a
          CSS-hidden duplicate tree). Keyed by the URL month so the transition
          render remounts it (re-runs the fade); unchanged in the urgent render,
          where the memoized table bails on stable props. */}
      {!rangeMode && data && isDesktop && (
        <div key={`desktop-${month}`} className="month-transition">
          <TransactionTable
            transactions={sorted}
            sort={sort}
            onSortChange={setSort}
            onConfirm={handleConfirm}
            onEmailPreview={handleEmailPreview}
            selectionMode={selectionMode}
          />
        </div>
      )}

      {/* Mobile — sort control + cards, rendered only below md. */}
      {!rangeMode && data && !isDesktop && (
        <>
          <MobileSortControl sort={sort} onSortChange={setSort} />
          <div key={`mobile-${month}`} className="space-y-3 month-transition">
            {sorted.map((txn) => (
              <TransactionCard
                key={`${txn.forwarded_to}|${txn.date_file_name}`}
                transaction={txn}
                onConfirm={handleConfirm}
                onEmailPreview={handleEmailPreview}
              />
            ))}
            {filtered.length === 0 && (
              <p className="py-8 text-center text-fg-muted">No transactions match.</p>
            )}
          </div>
        </>
      )}

      {/* Range mode — loading / error / empty, then the virtualized results
          (up to 1000 rows). The server already applied the heavy filters. */}
      {rangeMode && searchLoading && (
        <div className="space-y-2">
          {Array.from({ length: 8 }).map((_, i) => (
            <Skeleton key={i} className="h-12 w-full" />
          ))}
        </div>
      )}

      {rangeMode && searchIsError && (
        <QueryErrorNotice
          error={searchError}
          onRetry={() => void searchRefetch()}
          fallback="Search couldn't complete. Try a shorter date range."
        />
      )}

      {rangeMode && searchData && searchData.transactions.length === 0 && (
        <p className="py-12 text-center text-fg-muted">Nothing matches that search.</p>
      )}

      {rangeMode && searchData && searchData.transactions.length > 0 && isDesktop && (
        <TransactionTable
          virtualize
          transactions={rangeSorted}
          sort={sort}
          onSortChange={setSort}
          onEmailPreview={handleEmailPreview}
        />
      )}

      {rangeMode && searchData && searchData.transactions.length > 0 && !isDesktop && (
        <>
          <MobileSortControl sort={sort} onSortChange={setSort} />
          <div className="space-y-3">
            {rangeSorted.map((txn) => (
              <TransactionCard
                key={`${txn.forwarded_to}|${txn.date_file_name}`}
                transaction={txn}
                onEmailPreview={handleEmailPreview}
              />
            ))}
            {rangeSorted.length === 0 && (
              <p className="py-8 text-center text-fg-muted">No transactions match.</p>
            )}
          </div>
        </>
      )}

      <EmailPreviewDialog
        transaction={emailPreviewTxn}
        open={emailPreviewOpen}
        onOpenChange={setEmailPreviewOpen}
      />

      {/* Receipts to file — a compact list of unfiled uploads (name, date,
          file/view/delete). "File" runs the parse → match → link flow. */}
      <Dialog
        open={receiptsOpen}
        onOpenChange={(o) => {
          setReceiptsOpen(o);
          if (!o) setFileAttachment(null);
        }}
      >
        <DialogContent className="max-h-[85vh] max-w-md overflow-y-auto">
          <DialogHeader>
            <DialogTitle>Receipts to file</DialogTitle>
            <DialogDescription>
              Receipts you've uploaded that aren't linked to a transaction yet.
            </DialogDescription>
          </DialogHeader>
          {fileAttachment ? (
            <div className="space-y-3">
              <button
                type="button"
                onClick={() => setFileAttachment(null)}
                className="text-xs text-fg-muted underline-offset-2 hover:text-fg hover:underline"
              >
                ← Back to receipts
              </button>
              <p className="truncate text-sm font-medium">{fileAttachment.original_filename}</p>
              <ReceiptReview
                attachment={fileAttachment}
                matching
                onLinked={() => setFileAttachment(null)}
              />
            </div>
          ) : unlinked.length === 0 ? (
            <p className="py-8 text-center text-sm text-fg-muted">No receipts waiting.</p>
          ) : (
            <ul className="space-y-2">
              {unlinked.map((att) => {
                const isDeleting =
                  deleteAttachment.isPending && deleteAttachment.variables === att.id;
                return (
                  <li
                    key={att.id}
                    className="flex items-center gap-3 rounded-lg border border-border p-2.5"
                  >
                    <div className="min-w-0 flex-1">
                      <p className="truncate text-sm font-medium">{att.original_filename}</p>
                      <p className="text-xs text-fg-muted">
                        {formatBytes(att.size_bytes)} · added {formatRelativeTime(att.created_at)}
                      </p>
                    </div>
                    <button
                      type="button"
                      onClick={() => setFileAttachment(att)}
                      className="rounded px-2 py-1 text-xs text-fg-muted transition-colors hover:bg-accent hover:text-fg"
                    >
                      File
                    </button>
                    <button
                      type="button"
                      onClick={() => setViewAttachment(att)}
                      className="rounded px-2 py-1 text-xs text-fg-muted transition-colors hover:bg-accent hover:text-fg"
                    >
                      View
                    </button>
                    <button
                      type="button"
                      aria-label="Delete receipt"
                      disabled={isDeleting}
                      onClick={() => deleteAttachment.mutate(att.id)}
                      className="rounded p-1 text-fg-muted transition-colors hover:bg-status-danger/10 hover:text-status-danger disabled:opacity-50"
                    >
                      {isDeleting ? (
                        <Loader2 className="h-4 w-4 animate-spin" />
                      ) : (
                        <Trash2 className="h-4 w-4" />
                      )}
                    </button>
                  </li>
                );
              })}
            </ul>
          )}
        </DialogContent>
      </Dialog>

      <AttachmentViewDialog
        attachments={viewAttachment ? [viewAttachment] : []}
        open={viewAttachment !== null}
        onOpenChange={(o) => !o && setViewAttachment(null)}
      />
    </div>
  );
}
