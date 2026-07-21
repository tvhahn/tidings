/**
 * Centralized React Query configuration — the source of truth for all cache
 * keys, fetch functions, and stale times.
 *
 * Thin hook wrappers (useCategories, useSummary, etc.) delegate to these
 * configs. Use `queryKeys.*` (or `queryKeys.prefix(name)`) for invalidation
 * and `queries.*` for `useQuery()` options. The pattern is enforced by an
 * ESLint `no-restricted-syntax` rule scoped to inline `useQuery({...})` and
 * literal-keyed `invalidateQueries({ queryKey: ["foo", ...] })` — see
 * `frontend/CLAUDE.md` for the convention.
 */

import { keepPreviousData } from "@tanstack/react-query";
import type { InvalidateQueryFilters, QueryClient } from "@tanstack/react-query";
import {
  addCategory,
  addIgnoreRule,
  addManualTransaction,
  applyIgnoreRules,
  clearCategoryIcon,
  consolidateOverrides,
  deleteAttachment,
  deleteCategory,
  deleteIgnoreRule,
  deleteMerchantAlias,
  deleteOverride,
  deleteStatement,
  dismissIgnoreRuleSuggestion,
  dismissParseFailure,
  dismissSuggestion,
  fetchActivity,
  fetchAllTransactions,
  fetchAttentionQueue,
  fetchBudgetConfig,
  fetchBudgetStatus,
  fetchCategories,
  fetchCategoryIcons,
  fetchCategoryUsage,
  fetchConfig,
  fetchCoverage,
  fetchDismissedIgnoreRuleSuggestions,
  fetchGroups,
  fetchHealth,
  fetchHistoricalAverages,
  fetchIgnoreRules,
  fetchIgnoreRuleSuggestions,
  fetchIncomeStatement,
  fetchInsightsContext,
  fetchInsightsStatus,
  fetchJournal,
  fetchJournalSummaries,
  fetchJournalSummaryStatus,
  fetchManagedCategories,
  fetchMerchantAliases,
  fetchMerchantIntelligence,
  fetchOverrideDuplicates,
  fetchOverrideMatch,
  fetchOverrides,
  fetchOverrideSuggestions,
  fetchS3BackupStatus,
  fetchSavedInsight,
  fetchSavedInsightsList,
  fetchStatement,
  fetchStatements,
  fetchSummary,
  fetchTaxLines,
  fetchTaxPack,
  setTaxOverride,
  clearTaxOverride,
  fetchReceiptCandidates,
  fetchTransactionAttachments,
  fetchTransactionDetail,
  fetchTrash,
  fetchTrend,
  fetchUnlinkedAttachments,
  generateInsights,
  generateJournalSummaries,
  getParseFailure,
  importStatementTransactions,
  listParseFailures,
  markReviewed,
  permanentlyDeleteTransaction,
  putMerchantAlias,
  putOverride,
  renameCategory,
  reparseStatement,
  resolveParseFailure,
  revertActivity,
  linkAttachment,
  parseReceipt,
  retryAllParseFailures,
  retryParseFailure,
  searchTransactions,
  setCategoryIcon,
  setComment,
  setIgnored,
  softDeleteTransaction,
  undismissIgnoreRuleSuggestion,
  updateBudgetConfig,
  updateCategory,
  updateCategoryGroup,
  updateConfig,
  updateGroups,
  updateTransactionAction,
  updateTransactionFields,
  uploadAttachment,
  uploadStatement,
} from "@/lib/api";
import type { ActivityFilters, ManualTransactionRequest } from "@/lib/api";
import type {
  AppConfigUpdate,
  BudgetConfigUpdateRequest,
  CategoryIconsResponse,
  GroupsUpdateRequest,
  ImportRequest,
  InsightsStatus,
  JournalSummaryStatus,
  ManualResolveRequest,
  OverrideConsolidateRequest,
  ParseFailureStatus,
  RetryAllRequest,
  RetryAllResponse,
  RetryResponse,
  SearchParams,
  TransactionActionUpdate,
} from "@/types/api";

// ---------------------------------------------------------------------------
// Query key factories — use these everywhere for cache consistency
// ---------------------------------------------------------------------------

export const queryKeys = {
  journal: (month: string) => ["journal", month] as const,
  journalSummaries: (month: string) => ["journal-summaries", month] as const,
  journalSummaryStatus: () => ["journal-summary-status"] as const,
  categories: () => ["categories"] as const,
  managedCategories: () => ["managedCategories"] as const,
  categoryGroups: (year: number) => ["categoryGroups", year] as const,
  categoryUsage: (name: string | null) => ["categoryUsage", name] as const,
  categoryIcons: () => ["categoryIcons"] as const,
  budgetConfig: (year: number) => ["budgetConfig", year] as const,
  budgetStatus: (year: number, compareYear?: number) =>
    ["budgetStatus", year, compareYear ?? null] as const,
  summary: (month: string) => ["summary", month] as const,
  trend: (months: number, endMonth?: string) => ["trend", months, endMonth] as const,
  attention: (month: string) => ["attention", month] as const,
  trash: (month: string) => ["trash", month] as const,
  transactions: (month: string) => ["transactions", month] as const,
  transactionsCombined: (month: string) => ["transactions-combined", month] as const,
  historicalAverages: (months: number) => ["historicalAverages", months] as const,
  transactionDetail: (forwardedTo: string, dateFileName: string) =>
    ["transactionDetail", forwardedTo, dateFileName] as const,
  incomeStatement: (year: number) => ["incomeStatement", year] as const,
  taxPack: (year: number) => ["tax-pack", year] as const,
  taxLines: () => ["tax-lines"] as const,
  insightsList: (month: string) => ["insights-list", month] as const,
  insightsContent: (month: string, id: string | null) => ["insights-content", month, id] as const,
  insightsContext: (month: string) => ["insights-context", month] as const,
  insightsStatus: () => ["insights-status"] as const,
  merchantIntelligence: (month: string, months: number) =>
    ["merchant-intelligence", month, months] as const,
  merchantAliases: () => ["merchantAliases"] as const,
  transactionSearch: (params: SearchParams | null) => ["transaction-search", params] as const,
  overrideMatch: (company: string) => ["override-match", company] as const,
  overrideDuplicates: () => ["override-duplicates"] as const,
  overrides: () => ["overrides"] as const,
  overrideSuggestions: () => ["overrideSuggestions"] as const,
  ignoreRules: () => ["ignoreRules"] as const,
  ignoreRuleSuggestions: () => ["ignoreRuleSuggestions"] as const,
  ignoreRuleDismissed: () => ["ignoreRuleDismissed"] as const,
  statement: (id: string | null) => ["statement", id] as const,
  statements: () => ["statements"] as const,
  config: () => ["config"] as const,
  s3BackupStatus: () => ["s3-backup-status"] as const,
  health: () => ["health"] as const,
  coverage: () => ["coverage"] as const,
  parseFailures: (status?: ParseFailureStatus) => ["parse-failures", status ?? "all"] as const,
  parseFailureDetail: (id: string | null) => ["parse-failure-detail", id] as const,
  attachments: (txId: string) => ["attachments", txId] as const,
  unlinkedAttachments: () => ["unlinkedAttachments"] as const,
  receiptCandidates: (id: string) => ["receiptCandidates", id] as const,
  activity: (filters: ActivityFilters = {}) => ["activity", filters] as const,
  /**
   * Partial-key invalidation. Pass a plain string prefix (e.g. "transactions")
   * to invalidate every query starting with that key. Prefer the named
   * factories above when you have the parameters; reach for `prefix` when
   * you want to invalidate every variant at once (e.g. all months of a
   * monthly query after a global mutation).
   */
  prefix: (name: string) => [name] as const,
} as const;

// ---------------------------------------------------------------------------
// Cross-cutting cache topology
// ---------------------------------------------------------------------------

/**
 * Query-key prefixes whose data depends on transaction state. Invalidate this
 * list after any mutation that changes the underlying transaction set
 * (delete, restore, ignore, edit, manual-add) and on the freshness probe
 * when it sees newer DateFileName ticks.
 *
 * Union of the previously-divergent lists in `lib/queryUtils.ts` and
 * `hooks/useFreshnessProbe.ts`. Centralized here so adding a new
 * transaction-dependent query is a one-place change.
 *
 * `trash` is included so the freshness probe and explicit soft-delete /
 * restore paths converge; non-trash mutations should still pass
 * `{ includeTrash: false }` to the helper to skip it on hot paths.
 */
export const TRANSACTION_DEPENDENT_PREFIXES = [
  "transactions-combined",
  "transactions",
  "transaction-search",
  "attention",
  "journal",
  "journal-summaries",
  "summary",
  "trend",
  "budgetStatus",
  "incomeStatement",
  "insights-list",
  "tax-pack",
  "trash",
] as const;

type InvalidateOpts = {
  /** Also invalidate trash queries (for soft-delete / restore paths). */
  includeTrash?: boolean;
} & Pick<InvalidateQueryFilters, "refetchType">;

/**
 * Invalidate all queries that depend on transaction state.
 *
 * Use in `onSettled` (and undo handlers in `onSuccess`) for mutations that
 * change transaction data: delete, restore, ignore, edit fields, rename a
 * category, etc.
 *
 * Pass `refetchType: "none"` (mirrors React Query's option) for optimistic
 * mutations — marks queries stale without racing a refetch against the PATCH
 * commit. Window-focus / freshness-probe ticks pick up the fresh value next.
 *
 * @param includeTrash - also invalidate trash queries; off by default so
 *   hot-path mutations don't trigger an unnecessary trash refetch.
 */
export function invalidateTransactionDependents(
  queryClient: QueryClient,
  { includeTrash = false, ...filters }: InvalidateOpts = {}
): void {
  for (const prefix of TRANSACTION_DEPENDENT_PREFIXES) {
    if (prefix === "trash" && !includeTrash) continue;
    queryClient.invalidateQueries({ queryKey: [prefix], ...filters });
  }
}

/**
 * Everything a receipt link/unlink (or parse) can go stale: per-transaction
 * attachment lists, the "Receipts to file" count, candidate sets, and the tax
 * pack's per-line evidence coverage (linking a receipt flips a row's evidence
 * from email/statement to receipt, L15). Shared by the uploadAttachment/
 * deleteAttachment/linkAttachment/parseReceipt mutation factories (an
 * upload-with-txId auto-links and a delete un-links, same evidence/candidate
 * fallout as an explicit link). The single-strong-match auto-link (L8) now
 * runs through linkAttachment as well — the candidates GET is a pure read that
 * only signals eligibility (`auto_link_candidate`), so the mutation owns this
 * invalidation and no query observer refreshes on its own. Deliberately does
 * NOT touch transaction views (L15).
 */
export function invalidateAttachmentLinkCaches(queryClient: QueryClient): void {
  queryClient.invalidateQueries({ queryKey: queryKeys.prefix("attachments") });
  queryClient.invalidateQueries({ queryKey: queryKeys.unlinkedAttachments() });
  queryClient.invalidateQueries({ queryKey: queryKeys.prefix("receiptCandidates") });
  queryClient.invalidateQueries({ queryKey: queryKeys.prefix("tax-pack") });
}

// ---------------------------------------------------------------------------
// Query option factories — pass to useQuery() directly
// ---------------------------------------------------------------------------

export const queries = {
  journal: (month: string) => ({
    queryKey: queryKeys.journal(month),
    queryFn: () => fetchJournal(month),
    staleTime: 5 * 60 * 1000,
    placeholderData: keepPreviousData,
  }),

  journalSummaries: (month: string) => ({
    queryKey: queryKeys.journalSummaries(month),
    queryFn: () => fetchJournalSummaries(month),
    staleTime: 5 * 60 * 1000,
    // Hold the prior month's summaries during a month change so the day cards
    // don't blank their AI summaries while the new month loads.
    placeholderData: keepPreviousData,
  }),

  categories: () => ({
    queryKey: queryKeys.categories(),
    queryFn: fetchCategories,
    staleTime: Infinity,
  }),

  budgetConfig: (year: number) => ({
    queryKey: queryKeys.budgetConfig(year),
    queryFn: () => fetchBudgetConfig(year),
    staleTime: 5 * 60 * 1000,
    retry: false as const,
  }),

  budgetStatus: (year: number, compareYear?: number) => ({
    queryKey: queryKeys.budgetStatus(year, compareYear),
    queryFn: () => fetchBudgetStatus(year, compareYear),
    staleTime: 5 * 60 * 1000,
  }),

  summary: (month: string) => ({
    queryKey: queryKeys.summary(month),
    queryFn: () => fetchSummary(month),
    staleTime: 5 * 60 * 1000,
    placeholderData: keepPreviousData,
  }),

  trend: (months: number = 6, endMonth?: string) => ({
    queryKey: queryKeys.trend(months, endMonth),
    queryFn: () => fetchTrend(months, endMonth),
    staleTime: 5 * 60 * 1000,
    placeholderData: keepPreviousData,
  }),

  attention: (month: string) => ({
    queryKey: queryKeys.attention(month),
    queryFn: () => fetchAttentionQueue(month),
    staleTime: 30 * 60 * 1000,
    placeholderData: keepPreviousData,
  }),

  trash: (month: string) => ({
    queryKey: queryKeys.trash(month),
    queryFn: () => fetchTrash(month),
    staleTime: 30 * 60 * 1000,
    placeholderData: keepPreviousData,
  }),

  historicalAverages: (months: number = 6) => ({
    queryKey: queryKeys.historicalAverages(months),
    queryFn: () => fetchHistoricalAverages(months),
    staleTime: 10 * 60 * 1000,
  }),

  transactionDetail: (forwardedTo: string, dateFileName: string) => ({
    queryKey: queryKeys.transactionDetail(forwardedTo, dateFileName),
    queryFn: () => fetchTransactionDetail(forwardedTo, dateFileName),
    staleTime: 30 * 60 * 1000,
  }),

  incomeStatement: (year: number) => ({
    queryKey: queryKeys.incomeStatement(year),
    queryFn: () => fetchIncomeStatement(year),
    staleTime: 5 * 60 * 1000,
  }),

  taxPack: (year: number) => ({
    queryKey: queryKeys.taxPack(year),
    queryFn: () => fetchTaxPack(year),
    staleTime: 5 * 60 * 1000,
    placeholderData: keepPreviousData,
  }),

  // The selectable CRA claim lines are effectively static (seven seed lines
  // plus "other"); hold them like categories rather than refetch per view.
  taxLines: () => ({
    queryKey: queryKeys.taxLines(),
    queryFn: fetchTaxLines,
    staleTime: Infinity,
  }),

  savedInsightsList: (month: string) => ({
    queryKey: queryKeys.insightsList(month),
    queryFn: () => fetchSavedInsightsList(month),
    staleTime: 5 * 60 * 1000,
  }),

  savedInsight: (id: string, month: string) => ({
    queryKey: queryKeys.insightsContent(month, id),
    queryFn: () => fetchSavedInsight(id, month),
    staleTime: Infinity,
  }),

  insightsContext: (month: string) => ({
    queryKey: queryKeys.insightsContext(month),
    queryFn: () => fetchInsightsContext(month),
    staleTime: 5 * 60 * 1000,
    placeholderData: keepPreviousData,
  }),

  merchantIntelligence: (month: string, months: number = 6) => ({
    queryKey: queryKeys.merchantIntelligence(month, months),
    queryFn: () => fetchMerchantIntelligence(month, months),
    staleTime: 10 * 60 * 1000,
    placeholderData: keepPreviousData,
  }),

  transactionSearch: (params: SearchParams | null) => ({
    queryKey: queryKeys.transactionSearch(params),
    queryFn: () => searchTransactions(params as SearchParams),
    enabled: params !== null,
    staleTime: 5 * 60 * 1000,
    placeholderData: keepPreviousData,
  }),

  overrideMatch: (company: string) => ({
    queryKey: queryKeys.overrideMatch(company),
    queryFn: () => fetchOverrideMatch(company),
    // Debounced input already filters below 3 chars; cache hot results 30s
    // so rapid keystrokes in the add-rule form reuse the previous response.
    staleTime: 30 * 1000,
    // Skip the query entirely for short inputs — the endpoint 422s on empty
    // and we want to avoid firing on single-keystroke inputs.
    enabled: company.trim().length >= 3,
    retry: false as const,
  }),

  // Same backend as `overrideMatch`, but called from CategoryPicker for stable
  // transaction merchants (not a typing form). Embeddings for a fixed merchant
  // string don't change minute-to-minute, so a longer staleTime keeps the
  // dropdown snappy and avoids redundant backend trips. The server-side
  // EmbeddingCache means OpenAI cost is paid once per merchant regardless.
  //
  // Passes `includeHistory=true` so the corpus is built from the user's full
  // transaction history (not just overrides) — needed when local-cache months
  // don't have prior categorizations of the merchant. Distinct queryKey from
  // `overrideMatch` so it doesn't collide with the settings-form variant.
  //
  // Threshold lowered to 0.55 (vs the default 0.70 used by the settings form):
  // short merchant strings ("Thriftmart #0410", "The Hardware Barn #7702") cluster
  // loosely under text-embedding-3-small. A weak suggestion costs the user
  // nothing — they ignore it — while strict thresholds leave the picker silent.
  overrideMatchForPicker: (company: string) => ({
    queryKey: ["override-match-picker", company] as const,
    queryFn: () => fetchOverrideMatch(company, { includeHistory: true, minScore: 0.55 }),
    staleTime: 5 * 60 * 1000,
    enabled: company.trim().length >= 3,
    retry: false as const,
  }),

  overrideDuplicates: () => ({
    queryKey: queryKeys.overrideDuplicates(),
    queryFn: fetchOverrideDuplicates,
    staleTime: 5 * 60 * 1000,
  }),

  // Liveness / last-activity probe. Polls every 60s; cache stays fresh for 30s
  // so tab-switches within a minute reuse the previous response.
  health: () => ({
    queryKey: queryKeys.health(),
    queryFn: fetchHealth,
    staleTime: 30_000,
    refetchInterval: 60_000,
    // Keep polling even when the indicator isn't visible — a tooltip/popover
    // opening is instant, and a 30s cache already short-circuits re-fetches.
    refetchIntervalInBackground: false,
  }),

  // Per-institution alert cadence + passive capture rate. A calm monitoring
  // surface (Settings → System, a nav pill); no polling — a 5-minute cache is
  // plenty for a snapshot the backend refreshes on its own hourly TTL.
  coverage: () => ({
    queryKey: queryKeys.coverage(),
    queryFn: fetchCoverage,
    staleTime: 5 * 60 * 1000,
  }),

  // "Needs review" queue. Low-frequency maintenance surface; a short staleTime
  // keeps it light. Status undefined → the full queue (used by the "All" filter).
  parseFailures: (status?: ParseFailureStatus) => ({
    queryKey: queryKeys.parseFailures(status),
    queryFn: () => listParseFailures(status),
    staleTime: 30 * 1000,
  }),

  // Agent activity ledger (Settings → Activity). A receipt of recorded writes,
  // newest first; a 60s stale window keeps the settings sub-page light without
  // polling.
  activity: (filters: ActivityFilters = {}) => ({
    queryKey: queryKeys.activity(filters),
    queryFn: () => fetchActivity(filters),
    staleTime: 60_000,
  }),

  // Lazy per-row detail — carries the raw email body (PII), so it's only
  // fetched when a row is expanded (`enabled` gates on a non-null id).
  parseFailureDetail: (id: string | null) => ({
    queryKey: queryKeys.parseFailureDetail(id),
    queryFn: () => getParseFailure(id as string),
    enabled: !!id,
    staleTime: 5 * 60 * 1000,
  }),

  statement: (id: string | null) => ({
    queryKey: queryKeys.statement(id),
    queryFn: () => fetchStatement(id as string),
    enabled: !!id,
  }),

  statements: () => ({
    queryKey: queryKeys.statements(),
    queryFn: fetchStatements,
  }),

  // A transaction's linked receipts/documents. Fetched lazily — hooks pass
  // `enabled` so this only runs once a row's action cluster is revealed, never
  // as a bulk per-row sweep.
  attachments: (txId: string) => ({
    queryKey: queryKeys.attachments(txId),
    queryFn: () => fetchTransactionAttachments(txId),
    staleTime: 5 * 60 * 1000,
  }),

  // Receipts uploaded but not yet filed against a transaction. Drives the quiet
  // "Receipts to file (N)" affordance on the Transactions page.
  unlinkedAttachments: () => ({
    queryKey: queryKeys.unlinkedAttachments(),
    queryFn: fetchUnlinkedAttachments,
    staleTime: 60 * 1000,
  }),

  // Ranked match candidates for a parsed receipt. Hooks pass `enabled` so this
  // fires only after a parse succeeds (unparsed attachments 409). Never cached
  // long — the candidate set changes as transactions arrive.
  receiptCandidates: (id: string) => ({
    queryKey: queryKeys.receiptCandidates(id),
    queryFn: () => fetchReceiptCandidates(id),
    staleTime: 30 * 1000,
    retry: false as const,
  }),

  overrideSuggestions: () => ({
    queryKey: queryKeys.overrideSuggestions(),
    queryFn: () => fetchOverrideSuggestions(),
    staleTime: 5 * 60 * 1000,
    retry: false as const,
  }),

  categoryGroups: (year: number) => ({
    queryKey: queryKeys.categoryGroups(year),
    queryFn: () => fetchGroups(year),
    staleTime: 5 * 60 * 1000,
  }),

  transactionsCombined: (month: string) => ({
    queryKey: queryKeys.transactionsCombined(month),
    queryFn: () => fetchAllTransactions(month),
    staleTime: 30 * 60 * 1000,
    placeholderData: keepPreviousData,
  }),

  merchantAliases: () => ({
    queryKey: queryKeys.merchantAliases(),
    queryFn: fetchMerchantAliases,
    staleTime: 5 * 60 * 1000,
  }),

  overrides: () => ({
    queryKey: queryKeys.overrides(),
    queryFn: fetchOverrides,
    staleTime: 5 * 60 * 1000,
    retry: false as const,
  }),

  ignoreRules: () => ({
    queryKey: queryKeys.ignoreRules(),
    queryFn: fetchIgnoreRules,
    staleTime: 5 * 60 * 1000,
    retry: false as const,
  }),

  ignoreRuleSuggestions: () => ({
    queryKey: queryKeys.ignoreRuleSuggestions(),
    queryFn: () => fetchIgnoreRuleSuggestions(),
    staleTime: 5 * 60 * 1000,
    retry: false as const,
  }),

  ignoreRuleDismissed: () => ({
    queryKey: queryKeys.ignoreRuleDismissed(),
    queryFn: fetchDismissedIgnoreRuleSuggestions,
    staleTime: 5 * 60 * 1000,
    retry: false as const,
  }),

  managedCategories: () => ({
    queryKey: queryKeys.managedCategories(),
    queryFn: fetchManagedCategories,
    staleTime: 5 * 60 * 1000,
    retry: false as const,
  }),

  categoryUsage: (name: string | null) => ({
    queryKey: queryKeys.categoryUsage(name),
    queryFn: () => fetchCategoryUsage(name as string),
    enabled: !!name,
    staleTime: 30 * 1000,
  }),

  categoryIcons: () => ({
    queryKey: queryKeys.categoryIcons(),
    queryFn: fetchCategoryIcons,
    staleTime: 5 * 60 * 1000,
  }),

  config: () => ({
    queryKey: queryKeys.config(),
    queryFn: fetchConfig,
    staleTime: 5 * 60 * 1000,
  }),

  // Tracks the hourly background sync without a manual refresh: a 60s poll keeps
  // last-sync time and mirrored-file counts current while the section is open.
  s3BackupStatus: () => ({
    queryKey: queryKeys.s3BackupStatus(),
    queryFn: fetchS3BackupStatus,
    staleTime: 30_000,
    refetchInterval: 60_000,
  }),

  // Polls every 2s while the backend is generating; idle when not. The
  // refetchInterval predicate inspects the latest payload so the polling
  // self-deactivates as soon as status flips to "idle"/"error".
  insightsStatus: () => ({
    queryKey: queryKeys.insightsStatus(),
    queryFn: fetchInsightsStatus,
    refetchInterval: (query: { state: { data: InsightsStatus | undefined } }) =>
      query.state.data?.status === "running" ? 2000 : false,
  }),

  // Same polling pattern as `insightsStatus` but for the journal-summary
  // generator. Polls every 2s while running.
  journalSummaryStatus: () => ({
    queryKey: queryKeys.journalSummaryStatus(),
    queryFn: fetchJournalSummaryStatus,
    refetchInterval: (query: { state: { data: JournalSummaryStatus | undefined } }) =>
      query.state.data?.status === "running" ? 2000 : false,
  }),
};

// ---------------------------------------------------------------------------
// Mutation option factories — pass QueryClient, get full useMutation options
// ---------------------------------------------------------------------------
//
// Asymmetric with queries.* by design: a mutation's invalidation contract is
// half its semantics, and centralizing it here is the whole point. The
// canonical hook shape is:
//
//   export function useUpdateBudget(year: number) {
//     const qc = useQueryClient();
//     return useMutation(mutations.updateBudget(year, qc));
//   }
//
// Hooks with optimistic onMutate/onError spread the factory and override —
// the factory provides mutationFn + onSettled (the invalidation contract);
// the hook overlays cache-specific snapshot/rollback/toast logic:
//
//   return useMutation({
//     ...mutations.softDelete(qc),
//     onMutate: async (v) => { /* snapshot + optimistic update */ },
//     onError:  (_e, _v, ctx) => { /* rollback */ },
//     onSuccess: (_d, vars) => { /* toast + undo */ },
//   });

export const mutations = {
  // --- Budget ---
  updateBudget: (year: number, qc: QueryClient) => ({
    mutationFn: (data: BudgetConfigUpdateRequest) => updateBudgetConfig(year, data),
    onSuccess: () => {
      qc.invalidateQueries({ queryKey: queryKeys.prefix("budgetConfig") });
      qc.invalidateQueries({ queryKey: queryKeys.prefix("budgetStatus") });
    },
  }),

  updateGroups: (year: number, qc: QueryClient) => ({
    mutationFn: (data: GroupsUpdateRequest) => updateGroups(year, data),
    onSuccess: () => {
      qc.invalidateQueries({ queryKey: queryKeys.prefix("categoryGroups") });
      qc.invalidateQueries({ queryKey: queryKeys.prefix("budgetConfig") });
      qc.invalidateQueries({ queryKey: queryKeys.managedCategories() });
    },
  }),

  // --- Config ---
  updateConfig: (qc: QueryClient) => ({
    mutationFn: (data: AppConfigUpdate) => updateConfig(data),
    onSuccess: () => {
      qc.invalidateQueries({ queryKey: queryKeys.config() });
    },
  }),

  // --- Overrides ---
  consolidateOverrides: (qc: QueryClient) => ({
    mutationFn: (body: OverrideConsolidateRequest) => consolidateOverrides(body),
    onSuccess: () => {
      qc.invalidateQueries({ queryKey: queryKeys.overrides() });
      qc.invalidateQueries({ queryKey: queryKeys.overrideDuplicates() });
    },
  }),

  putOverride: (qc: QueryClient) => ({
    mutationFn: ({ company, category }: { company: string; category: string }) =>
      putOverride(company, category),
    onSuccess: () => {
      qc.invalidateQueries({ queryKey: queryKeys.overrides() });
      qc.invalidateQueries({ queryKey: queryKeys.overrideSuggestions() });
    },
  }),

  deleteOverride: (qc: QueryClient) => ({
    mutationFn: (company: string) => deleteOverride(company),
    onSuccess: () => {
      qc.invalidateQueries({ queryKey: queryKeys.overrides() });
      qc.invalidateQueries({ queryKey: queryKeys.overrideSuggestions() });
    },
  }),

  dismissSuggestion: (qc: QueryClient) => ({
    mutationFn: ({ company, category }: { company: string; category: string }) =>
      dismissSuggestion(company, category),
    onSuccess: () => {
      qc.invalidateQueries({ queryKey: queryKeys.overrideSuggestions() });
    },
  }),

  // --- Auto-ignore rules ---
  addIgnoreRule: (qc: QueryClient) => ({
    mutationFn: (pattern: string) => addIgnoreRule(pattern),
    onSuccess: () => {
      qc.invalidateQueries({ queryKey: queryKeys.ignoreRules() });
      qc.invalidateQueries({ queryKey: queryKeys.ignoreRuleSuggestions() });
    },
  }),

  deleteIgnoreRule: (qc: QueryClient) => ({
    mutationFn: (pattern: string) => deleteIgnoreRule(pattern),
    onSuccess: () => {
      qc.invalidateQueries({ queryKey: queryKeys.ignoreRules() });
      qc.invalidateQueries({ queryKey: queryKeys.ignoreRuleSuggestions() });
    },
  }),

  applyIgnoreRules: (qc: QueryClient) => ({
    // Backfilling Ignored changes existing transaction state, so every
    // transaction-derived view must refetch (unlike add/delete, which only
    // affect future ingestion).
    mutationFn: (pattern?: string) => applyIgnoreRules(pattern),
    onSuccess: () => {
      invalidateTransactionDependents(qc);
      qc.invalidateQueries({ queryKey: queryKeys.ignoreRuleSuggestions() });
    },
  }),

  // Dismissing only hides a suggestion — no transaction state changes, so the
  // hook overlays an Undo toast (see useDismissIgnoreRuleSuggestion) while the
  // factory owns the suggestion-list invalidation via onSettled.
  dismissIgnoreRuleSuggestion: (qc: QueryClient) => ({
    mutationFn: (merchant: string) => dismissIgnoreRuleSuggestion(merchant),
    onSettled: () => {
      qc.invalidateQueries({ queryKey: queryKeys.ignoreRuleSuggestions() });
      qc.invalidateQueries({ queryKey: queryKeys.ignoreRuleDismissed() });
    },
  }),

  // Restoring a dismissal removes it from the dismissed list and lets the
  // merchant resurface as a suggestion, so both lists refetch.
  undismissIgnoreRuleSuggestion: (qc: QueryClient) => ({
    mutationFn: (merchant: string) => undismissIgnoreRuleSuggestion(merchant),
    onSettled: () => {
      qc.invalidateQueries({ queryKey: queryKeys.ignoreRuleSuggestions() });
      qc.invalidateQueries({ queryKey: queryKeys.ignoreRuleDismissed() });
    },
  }),

  // --- Merchant aliases ---
  putMerchantAlias: (qc: QueryClient) => ({
    mutationFn: ({ rawName, canonicalName }: { rawName: string; canonicalName: string }) =>
      putMerchantAlias(rawName, canonicalName),
    onSuccess: () => {
      qc.invalidateQueries({ queryKey: queryKeys.merchantAliases() });
      qc.invalidateQueries({ queryKey: queryKeys.prefix("incomeStatement") });
    },
  }),

  deleteMerchantAlias: (qc: QueryClient) => ({
    mutationFn: (rawName: string) => deleteMerchantAlias(rawName),
    onSuccess: () => {
      qc.invalidateQueries({ queryKey: queryKeys.merchantAliases() });
      qc.invalidateQueries({ queryKey: queryKeys.prefix("incomeStatement") });
    },
  }),

  // --- Categories ---
  addCategory: (qc: QueryClient) => ({
    mutationFn: ({ name, group }: { name: string; group: string | null }) =>
      addCategory(name, group),
    onSuccess: () => {
      qc.invalidateQueries({ queryKey: queryKeys.managedCategories() });
      qc.invalidateQueries({ queryKey: queryKeys.categories() });
    },
  }),

  renameCategory: (qc: QueryClient) => ({
    mutationFn: ({ oldName, newName }: { oldName: string; newName: string }) =>
      renameCategory(oldName, newName),
    onSuccess: () => {
      qc.invalidateQueries({ queryKey: queryKeys.managedCategories() });
      qc.invalidateQueries({ queryKey: queryKeys.categories() });
      qc.invalidateQueries({ queryKey: queryKeys.categoryIcons() });
      qc.invalidateQueries({ queryKey: queryKeys.overrides() });
      qc.invalidateQueries({ queryKey: queryKeys.prefix("budgetConfig") });
      invalidateTransactionDependents(qc);
    },
  }),

  deleteCategory: (qc: QueryClient) => ({
    mutationFn: ({ name, reassignTo }: { name: string; reassignTo?: string | undefined }) =>
      deleteCategory(name, reassignTo),
    onSuccess: () => {
      qc.invalidateQueries({ queryKey: queryKeys.managedCategories() });
      qc.invalidateQueries({ queryKey: queryKeys.categories() });
      qc.invalidateQueries({ queryKey: queryKeys.categoryIcons() });
      qc.invalidateQueries({ queryKey: queryKeys.overrides() });
      qc.invalidateQueries({ queryKey: queryKeys.prefix("budgetConfig") });
      invalidateTransactionDependents(qc);
    },
  }),

  updateCategoryGroup: (qc: QueryClient) => ({
    mutationFn: ({ name, group }: { name: string; group: string | null }) =>
      updateCategoryGroup(name, group),
    onSuccess: () => {
      qc.invalidateQueries({ queryKey: queryKeys.managedCategories() });
      qc.invalidateQueries({ queryKey: queryKeys.prefix("budgetConfig") });
    },
  }),

  setCategoryIcon: (qc: QueryClient) => ({
    mutationFn: ({ name, icon }: { name: string; icon: string }) => setCategoryIcon(name, icon),
    onSuccess: (data: CategoryIconsResponse) => {
      qc.setQueryData(queryKeys.categoryIcons(), data);
    },
  }),

  clearCategoryIcon: (qc: QueryClient) => ({
    mutationFn: (name: string) => clearCategoryIcon(name),
    onSuccess: (data: CategoryIconsResponse) => {
      qc.setQueryData(queryKeys.categoryIcons(), data);
    },
  }),

  // --- Statements ---
  // No invalidation — caller decides what to do with the parsed result.
  uploadStatement: () => ({
    mutationFn: (file: File) => uploadStatement(file),
  }),

  importStatement: (qc: QueryClient) => ({
    mutationFn: (data: ImportRequest) => importStatementTransactions(data),
    onSettled: () => {
      invalidateTransactionDependents(qc);
      qc.invalidateQueries({ queryKey: queryKeys.statements() });
    },
  }),

  deleteStatement: (qc: QueryClient) => ({
    mutationFn: (id: string) => deleteStatement(id),
    onSettled: () => {
      qc.invalidateQueries({ queryKey: queryKeys.statements() });
    },
  }),

  updateTransactionAction: (statementId: string | null, qc: QueryClient) => ({
    mutationFn: ({ rowId, data }: { rowId: string; data: TransactionActionUpdate }) => {
      if (!statementId) throw new Error("No statement ID");
      return updateTransactionAction(statementId, rowId, data);
    },
    onSuccess: () => {
      if (statementId) {
        qc.invalidateQueries({ queryKey: queryKeys.statement(statementId) });
      }
    },
  }),

  reparseStatement: (qc: QueryClient) => ({
    mutationFn: (id: string) => reparseStatement(id),
    onSuccess: (_data: unknown, id: string) => {
      qc.invalidateQueries({ queryKey: queryKeys.statement(id) });
      qc.invalidateQueries({ queryKey: queryKeys.statements() });
    },
  }),

  // --- Attachments (receipts & documents) ---
  // Linking a file changes no transaction data (L15), so these deliberately do
  // NOT call invalidateTransactionDependents. But an upload-with-txId links the
  // receipt server-side immediately, and a delete un-links a linked one — both
  // flip tax-pack evidence and reopen candidate sets, so they share the full
  // invalidateAttachmentLinkCaches contract (attachments, unlinked count,
  // candidates, tax-pack). Invalidation lives in onSettled so a hook can add a
  // toast onSuccess without clobbering the refresh contract.
  uploadAttachment: (qc: QueryClient) => ({
    mutationFn: ({ file, txId, kind }: { file: File; txId?: string; kind?: string }) =>
      uploadAttachment(file, txId, kind),
    onSettled: () => invalidateAttachmentLinkCaches(qc),
  }),

  // A link resolves (or reopens) a receipt's candidate set too — the shared
  // helper refetches it so an undo/relink reflects `already_has_receipt`.
  linkAttachment: (qc: QueryClient) => ({
    mutationFn: ({ id, txId }: { id: string; txId: string | null }) => linkAttachment(id, txId),
    onSettled: () => invalidateAttachmentLinkCaches(qc),
  }),

  // Parsing enriches the row (parse_status/parse_json) and unlocks candidates —
  // an attachment write, so it stays off invalidateTransactionDependents (L15).
  parseReceipt: (qc: QueryClient) => ({
    mutationFn: (id: string) => parseReceipt(id),
    onSettled: () => invalidateAttachmentLinkCaches(qc),
  }),

  deleteAttachment: (qc: QueryClient) => ({
    mutationFn: (id: string) => deleteAttachment(id),
    onSettled: () => invalidateAttachmentLinkCaches(qc),
  }),

  // --- Tax-item overrides ---
  // Forcing a transaction onto/off a claim line only changes the tax pack's
  // per-line membership — journal/transaction lists don't surface the flag, so
  // these invalidate the tax-pack prefix alone (never invalidateTransactionDependents).
  setTaxOverride: (qc: QueryClient) => ({
    mutationFn: ({
      txId,
      mode,
      lineKey,
    }: {
      txId: string;
      mode: "include" | "exclude";
      lineKey?: string;
    }) => setTaxOverride(txId, mode, lineKey),
    onSettled: () => {
      qc.invalidateQueries({ queryKey: queryKeys.prefix("tax-pack") });
    },
  }),

  clearTaxOverride: (qc: QueryClient) => ({
    mutationFn: (txId: string) => clearTaxOverride(txId),
    onSettled: () => {
      qc.invalidateQueries({ queryKey: queryKeys.prefix("tax-pack") });
    },
  }),

  // --- Insights / journal generation ---
  generateInsights: (qc: QueryClient) => ({
    mutationFn: (month: string) => generateInsights(month),
    onSuccess: () => {
      qc.invalidateQueries({ queryKey: queryKeys.insightsStatus() });
    },
  }),

  generateJournalSummaries: (qc: QueryClient) => ({
    mutationFn: ({ month, dates, force }: { month: string; dates: string[]; force?: boolean }) =>
      generateJournalSummaries(month, dates, force),
    onSuccess: () => {
      qc.invalidateQueries({ queryKey: queryKeys.journalSummaryStatus() });
    },
  }),

  // --- Manual transactions ---
  addTransaction: (qc: QueryClient) => ({
    mutationFn: (data: ManualTransactionRequest) => addManualTransaction(data),
    onSuccess: () => {
      invalidateTransactionDependents(qc);
    },
  }),

  // --- Optimistic transaction mutations ---
  // Factory provides mutationFn + onSettled (the invalidation contract).
  // Hooks overlay onMutate/onError/onSuccess for snapshot, rollback, and
  // toast/undo. Spread the factory and override.
  permanentDelete: (qc: QueryClient) => ({
    mutationFn: ({ forwardedTo, dateFileName }: { forwardedTo: string; dateFileName: string }) =>
      permanentlyDeleteTransaction(forwardedTo, dateFileName),
    onSettled: () => {
      invalidateTransactionDependents(qc, { includeTrash: true });
    },
  }),

  softDelete: (qc: QueryClient) => ({
    mutationFn: ({ forwardedTo, dateFileName }: { forwardedTo: string; dateFileName: string }) =>
      softDeleteTransaction(forwardedTo, dateFileName, true),
    onSettled: () => {
      invalidateTransactionDependents(qc, { includeTrash: true });
    },
  }),

  restoreTransaction: (qc: QueryClient) => ({
    mutationFn: ({ forwardedTo, dateFileName }: { forwardedTo: string; dateFileName: string }) =>
      softDeleteTransaction(forwardedTo, dateFileName, false),
    onSettled: () => {
      invalidateTransactionDependents(qc, { includeTrash: true });
    },
  }),

  markReviewed: (qc: QueryClient) => ({
    mutationFn: ({ forwardedTo, dateFileName }: { forwardedTo: string; dateFileName: string }) =>
      markReviewed(forwardedTo, dateFileName),
    onSettled: () => {
      invalidateTransactionDependents(qc);
    },
  }),

  ignoreTransaction: (qc: QueryClient) => ({
    mutationFn: ({
      forwardedTo,
      dateFileName,
      ignored,
    }: {
      forwardedTo: string;
      dateFileName: string;
      ignored: boolean;
    }) => setIgnored(forwardedTo, dateFileName, ignored),
    onSettled: () => {
      invalidateTransactionDependents(qc);
    },
  }),

  updateComment: (qc: QueryClient) => ({
    mutationFn: ({
      forwardedTo,
      dateFileName,
      comment,
    }: {
      forwardedTo: string;
      dateFileName: string;
      comment: string | null;
    }) => setComment(forwardedTo, dateFileName, comment),
    onSettled: () => {
      invalidateTransactionDependents(qc);
    },
  }),

  updateTransactionFields: (qc: QueryClient) => ({
    mutationFn: ({
      forwardedTo,
      dateFileName,
      fields,
    }: {
      forwardedTo: string;
      dateFileName: string;
      fields: { company?: string; amount?: number; transaction_type?: string };
    }) => updateTransactionFields(forwardedTo, dateFileName, fields),
    onSettled: () => {
      invalidateTransactionDependents(qc);
    },
  }),

  // refetchType: "none" marks queries stale without racing a refetch against
  // the PATCH commit. Next window-focus or freshness-probe tick picks up the
  // fresh value. See useUpdateCategory.ts for the full optimistic flow.
  updateCategory: (qc: QueryClient) => ({
    mutationFn: ({
      forwardedTo,
      dateFileName,
      category,
    }: {
      forwardedTo: string;
      dateFileName: string;
      category: string;
      oldCategory: string;
    }) => updateCategory(forwardedTo, dateFileName, category),
    onSettled: () => {
      invalidateTransactionDependents(qc, { refetchType: "none" });
    },
  }),

  // --- Parse failures ("Needs review") ---
  // Retry runs the deterministic parsers only (no AI). It returns just the
  // synthetic outcome, not the row's new state, so we re-fetch the queue via
  // invalidation rather than patching the row. A `created` outcome stored a new
  // transaction, so transaction-dependent views (Journal/Transactions/attention)
  // must refresh too.
  // Invalidation lives in onSettled (not onSuccess) so a hook can spread this
  // factory and add a toast onSuccess without clobbering the refresh contract —
  // the useSoftDelete pattern.
  retryParseFailure: (qc: QueryClient) => ({
    mutationFn: (id: string) => retryParseFailure(id),
    onSettled: (res: RetryResponse | undefined) => {
      qc.invalidateQueries({ queryKey: queryKeys.prefix("parse-failures") });
      if (res?.status === "created") invalidateTransactionDependents(qc);
    },
  }),

  dismissParseFailure: (qc: QueryClient) => ({
    mutationFn: (id: string) => dismissParseFailure(id),
    onSettled: () => {
      qc.invalidateQueries({ queryKey: queryKeys.prefix("parse-failures") });
    },
  }),

  // Bulk retry recovers a backlog after a parser lands. Like single retry it may
  // create transactions, so refresh both the queue and transaction-dependent
  // views — but only fan out the transaction-dependent invalidation when the run
  // actually created rows. On error or a created===0 outcome nothing changed, so
  // refreshing the queue prefix alone is enough. Invalidation lives in onSettled
  // so the page can add its counts toast onSuccess without clobbering the refresh
  // contract.
  retryAllParseFailures: (qc: QueryClient) => ({
    mutationFn: (filter: RetryAllRequest) => retryAllParseFailures(filter),
    onSettled: (res: RetryAllResponse | undefined) => {
      qc.invalidateQueries({ queryKey: queryKeys.prefix("parse-failures") });
      if (res && res.created > 0) invalidateTransactionDependents(qc);
    },
  }),

  // Manual entry records a hand-typed transaction AND resolves the row in one
  // call. Either outcome (created or duplicate) moves the row out of the queue,
  // and a created row adds a transaction, so always refresh both the queue and
  // the transaction-dependent views. Invalidation lives in onSettled so the
  // hook can add toasts onSuccess without clobbering the refresh contract.
  resolveParseFailure: (qc: QueryClient) => ({
    mutationFn: ({ id, body }: { id: string; body: ManualResolveRequest }) =>
      resolveParseFailure(id, body),
    onSettled: () => {
      qc.invalidateQueries({ queryKey: queryKeys.prefix("parse-failures") });
      invalidateTransactionDependents(qc);
    },
  }),

  // --- Activity ledger ---
  // Reverting a recorded write appends its own ledger entry and restores the
  // affected resource, so refresh both the feed and every transaction-derived
  // view (a reverted categorization must reappear on the Transactions surfaces).
  revertActivity: (qc: QueryClient) => ({
    mutationFn: ({ id, force }: { id: string; force?: boolean }) => revertActivity(id, force),
    onSettled: () => {
      qc.invalidateQueries({ queryKey: queryKeys.prefix("activity") });
      invalidateTransactionDependents(qc);
    },
  }),
};
