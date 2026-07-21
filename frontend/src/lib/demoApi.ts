import type {
  ActivityListResponse,
  AppConfig,
  AppConfigUpdate,
  AttachmentDeleteResponse,
  AttachmentListResponse,
  AttachmentResponse,
  AttentionListResponse,
  BudgetConfigResponse,
  BudgetConfigUpdateRequest,
  BudgetStatusResponse,
  BulkTransactionsResponse,
  CategoriesManagementResponse,
  CategoriesResponse,
  CategoryAnomaly,
  CategoryDeleteResponse,
  CategoryGroupUpdateResponse,
  CategoryIconsResponse,
  CategoryRenameResponse,
  CategoryUpdateResponse,
  CategoryUsageResponse,
  CombinedTransactionsResponse,
  CommentResponse,
  CoverageResponse,
  DeleteResponse,
  DismissResponse,
  GroupsResponse,
  GroupsUpdateRequest,
  HealthStatus,
  HistoricalAveragesResponse,
  IgnoreResponse,
  DismissedIgnoreRuleSuggestionsResponse,
  IgnoreRuleApplyResponse,
  IgnoreRuleListResponse,
  IgnoreRuleSuggestionsResponse,
  ImportRequest,
  ImportResponse,
  IncomeStatementResponse,
  InsightsContext,
  InsightsStatus,
  MerchantIntelligenceResponse,
  MerchantPriceChangeRow,
  MerchantRecord,
  JournalResponse,
  JournalSummariesResponse,
  JournalSummaryStatus,
  LatestTimestampResponse,
  ManualResolveRequest,
  ManualResolveResponse,
  OverrideConsolidateRequest,
  OverrideDuplicatesResponse,
  OverrideListResponse,
  OverrideMatchResponse,
  OverrideSuggestionsResponse,
  ParseFailureDetail,
  ParseFailureListResponse,
  ParseFailureStatus,
  ParseFailureSummary,
  PermanentDeleteResponse,
  ReceiptCandidatesResponse,
  ReviewResponse,
  RetryAllRequest,
  RetryAllResponse,
  RetryResponse,
  RevertResponse,
  S3BackupStatus,
  SavedInsight,
  SavedInsightSummary,
  SearchParams,
  SearchResponse,
  SearchSummary,
  StatementDetailResponse,
  StatementListResponse,
  StatementUploadResponse,
  SummaryComparisonResponse,
  TaxPackResponse,
  TestS3BackupResponse,
  Transaction,
  TransactionActionUpdate,
  TransactionDetail,
  TransactionFieldsUpdateResponse,
  TransactionListResponse,
  TrendResponse,
  WhoamiResponse,
} from "@/types/api";
import { txIdFromComposite } from "./api";
import type { ActivityFilters, TaxLineOption } from "./api";
import { computeCategoryAnomalies, inferMerchantType, topCategoryDeltas } from "./demoAnalytics";
import { DEMO_NOW_ISO } from "./demoConstants";
import { buildDemoEmail } from "./demoEmails";
import { loadFixture, DemoFixtureMissingError, DemoModeError } from "./demoFetch";
import {
  readOverlay,
  writeOverlay,
  listByPrefix,
  categoryOverrideKey,
  budgetOverrideKey,
  txStateKey,
  overrideKey,
  overrideDismissedKey,
  applyTxState,
  appendManualTransaction,
  readManualTransactions,
  type TxStateOverlay,
  type OverrideOverlay,
} from "./demoOverlay";
import { formatDate, shiftMonth } from "./format";

// The demo bundle aliases `@/lib/api` → this module, so any pure helper the app
// imports from "@/lib/api" must be exported here too. `txIdFromComposite` is a
// pure surrogate-id function with no backend dependency, so re-export the real
// one rather than reimplementing it.
export { txIdFromComposite };

// ---------------------------------------------------------------------------
// Contents (line numbers approximate; sections demarcated by `// ---` below)
//   Overlay application helpers ............ L126
//   App Config ............................. L196
//   Health / liveness probe ................ L208
//   Manual Transaction Entry ............... L228
//   Transactions ........................... L265
//   Category Groups ........................ L600
//   Insights context ....................... L625
//   Merchant intelligence .................. L723
//   Category Overrides ..................... L892
//   Category Management .................... L978
//   Statement Import ....................... L1039
//   Insights Generation .................... L1081
//   Merchant Aliases ....................... L1093
//   Income Statement ....................... L1123
//   Transaction Search ..................... L1131
//   Data backup (disabled in demo) ......... L1205
// ---------------------------------------------------------------------------

// Phase 4 auth surface — stubbed in the demo bundle. AuthBoundary always
// short-circuits to `tofu=false` in demo mode, so these are unreachable;
// they exist so the demo build can resolve the imports from LoginGate /
// AccessSection without a runtime null reference.
export const AUTH_REQUIRED_EVENT = "tidings:auth-required";
export const AUTH_STATE_CHANGED_EVENT = "tidings:auth-state-changed";

export type AuthOk = { status: string };

export function setAppPassword(_args: {
  password: string;
  current_password?: string;
}): Promise<AuthOk> {
  throw new DemoModeError("setAppPassword is disabled in the demo.");
}

export function loginWithPassword(_password: string): Promise<AuthOk> {
  throw new DemoModeError("loginWithPassword is disabled in the demo.");
}

export function logout(): Promise<AuthOk> {
  throw new DemoModeError("logout is disabled in the demo.");
}

export function signOutAllDevices(): Promise<AuthOk> {
  throw new DemoModeError("signOutAllDevices is disabled in the demo.");
}

// ---------------------------------------------------------------------------
// Overlay application helpers
// ---------------------------------------------------------------------------

function applyCategoryOverrides(transactions: Transaction[]): Transaction[] {
  const overlays = listByPrefix<string>("category-override:");
  if (overlays.length === 0) return transactions;
  const map = new Map<string, string>();
  for (const { key, value } of overlays) {
    // key = "category-override:{forwardedTo}:{dateFileName}"
    const rest = key.slice("category-override:".length);
    map.set(rest, value);
  }
  return transactions.map((t) => {
    const k = `${t.forwarded_to}:${t.date_file_name}`;
    const override = map.get(k);
    return override ? { ...t, category: override } : t;
  });
}

/**
 * Apply both the category-override and tx-state overlays, then drop tombstoned
 * and overlay-deleted rows. Use for any "active" view (Transactions, Journal,
 * Attention, Search) where soft-deleted items must not surface.
 */
function applyActiveOverlays(transactions: Transaction[]): Transaction[] {
  const withCategory = applyCategoryOverrides(transactions);
  const withState = applyTxState(withCategory);
  return withState.filter((t) => {
    const ov = readOverlay(txStateKey(t.forwarded_to, t.date_file_name));
    if (ov?.tombstone) return false;
    return !t.deleted_at;
  });
}

function applyBudgetOverlay(config: BudgetConfigResponse): BudgetConfigResponse {
  const overlay = readOverlay(budgetOverrideKey(config.year));
  if (!overlay) return config;
  const merged: BudgetConfigResponse = {
    ...config,
    spending_ceiling: overlay.spending_ceiling,
    groups: overlay.groups,
    targets_version: (config.targets_version ?? 0) + 1,
    groups_version: (config.groups_version ?? 0) + 1,
    categories: Object.fromEntries(
      Object.entries(overlay.categories).map(([name, input]) => {
        const existing = config.categories[name];
        const monthly_amount = input.input_mode === "monthly" ? input.target : input.target / 12;
        return [
          name,
          {
            target: input.target,
            input_mode: input.input_mode,
            monthly_amount,
            category_type: input.category_type,
            ...(existing ? {} : {}),
          },
        ];
      })
    ),
  };
  const allocated = Object.values(merged.categories).reduce(
    (sum, c) => sum + (c.input_mode === "monthly" ? c.target * 12 : c.target),
    0
  );
  merged.allocated_total = allocated;
  merged.unallocated = merged.spending_ceiling - allocated;
  return merged;
}

// ---------------------------------------------------------------------------
// App Config
// ---------------------------------------------------------------------------

export function fetchConfig(): Promise<AppConfig> {
  return loadFixture<AppConfig>("config");
}

export function updateConfig(_data: AppConfigUpdate): Promise<AppConfig> {
  throw new DemoModeError("Config updates are disabled in the demo.");
}

// The S3 backup section is hidden in the demo (`aws_available` is forced false),
// so these never render — but the parity gate requires a twin for every api.ts
// export. Both return inert, disabled values.
export function testS3Backup(
  _bucket: string,
  _prefix: string | null
): Promise<TestS3BackupResponse> {
  return Promise.resolve({ ok: false, error: "Not available in demo.", warnings: [] });
}

export function fetchS3BackupStatus(): Promise<S3BackupStatus> {
  return Promise.resolve({
    enabled: false,
    bucket: null,
    prefix: null,
    last_attempt_at: null,
    last_success_at: null,
    last_error: null,
    consecutive_failures: 0,
    uploaded_count: 0,
    deleted_count: 0,
    objects_total: 0,
  });
}

// ---------------------------------------------------------------------------
// Health / liveness probe
// ---------------------------------------------------------------------------

// The demo has no backend to poll, so return a synthetic "ok" snapshot pinned
// to the fixture month. Kept in sync with HealthResponse in the OpenAPI schema.
export function fetchHealth(): Promise<HealthStatus> {
  return Promise.resolve({
    status: "ok",
    version: "demo",
    backend: "sqlite",
    imap_last_poll: null,
    imap_poll_age_seconds: null,
    last_transaction_at: DEMO_NOW_ISO,
    last_transaction_age_seconds: null,
    parse_failures_7d: 0,
    checked_at: new Date().toISOString(),
    auth_required: false,
    ai_categorization_status: "ok",
    ai_last_error_reason: null,
    quiet_institutions: 0,
  });
}

// ---------------------------------------------------------------------------
// Manual Transaction Entry
// ---------------------------------------------------------------------------

export interface ManualTransactionRequest {
  date: string;
  amount: number;
  company: string;
  category?: string | undefined;
  transaction_type?: string | undefined;
  institution?: string | undefined;
  name?: string | undefined;
}

export interface ManualTransactionResponse {
  forwarded_to: string;
  date_file_name: string;
  category: string;
  status: string;
}

export function addManualTransaction(
  data: ManualTransactionRequest
): Promise<ManualTransactionResponse> {
  const month = data.date.slice(0, 7);
  const ymd = data.date.replaceAll("-", ".");
  const stamp = new Date().toISOString();
  const stampSlug = stamp.slice(11, 19).replaceAll(":", ".");
  const dateFileName = `${ymd}_${stampSlug}_demo_manual_${Date.now().toString(36)}.eml`;
  const forwardedTo = "mira.tidings@example.com";
  const tx: Transaction = {
    tx_id: txIdFromComposite(forwardedTo, dateFileName),
    forwarded_to: forwardedTo,
    date_file_name: dateFileName,
    date: `${data.date.slice(5, 7)}/${data.date.slice(8, 10)}/${data.date.slice(0, 4)} 12:00 PST`,
    amount: data.amount,
    company: data.company,
    category: data.category ?? "miscellaneous",
    institution: data.institution ?? null,
    transaction_type: data.transaction_type ?? "purchase",
    name: data.name ?? "Mira Lin Chen",
    category_audit: { source: "manual", reviewed_at: stamp },
    ignored: false,
    comment: null,
    deleted_at: null,
    context: null,
    statement_source: null,
  };
  appendManualTransaction(month, tx);
  return Promise.resolve({
    forwarded_to: tx.forwarded_to,
    date_file_name: tx.date_file_name,
    category: tx.category ?? "miscellaneous",
    status: "added",
  });
}

export function uploadEml(_file: File): Promise<{
  status: string;
  date_file_name?: string;
  company?: string;
  amount?: number;
  category?: string;
}> {
  throw new DemoModeError("EML upload is disabled in the demo.");
}

// ---------------------------------------------------------------------------
// Transactions
// ---------------------------------------------------------------------------

function monthSlug(prefix: string, month: string): string {
  return `${prefix}-${month}`;
}

export async function fetchTransactions(month: string): Promise<TransactionListResponse> {
  const res = await loadFixture<TransactionListResponse>(monthSlug("transactions", month));
  const manual = readManualTransactions(month);
  const merged = applyActiveOverlays([...manual, ...res.transactions]);
  return { ...res, count: merged.length, transactions: merged };
}

export async function fetchAttentionQueue(month: string): Promise<AttentionListResponse> {
  try {
    const res = await loadFixture<AttentionListResponse>(monthSlug("attention", month));
    const merged = applyActiveOverlays(res.transactions).filter((t) => !t.category_audit);
    return { ...res, count: merged.length, transactions: merged };
  } catch {
    return { month, count: 0, transactions: [] };
  }
}

export function fetchLatestTimestamp(_month?: string): Promise<LatestTimestampResponse> {
  return Promise.resolve({ month: null, latest: null });
}

export async function fetchAllTransactions(month: string): Promise<CombinedTransactionsResponse> {
  const res = await loadFixture<CombinedTransactionsResponse>(monthSlug("all", month));
  // The separate attention-{month}.json fixture is the source of truth — the
  // attention slice baked into all-{month}.json can lag. Prefer the standalone
  // fixture, fall back to the combined block.
  const standaloneAttention = await loadFixture<AttentionListResponse>(
    monthSlug("attention", month)
  ).catch(() => null);
  const attentionSource = standaloneAttention?.transactions ?? res.attention.transactions;
  // Manually added rows live in the sessionStorage overlay, not the fixture —
  // merge them here too or the Transactions page (combined query) never shows
  // what the Add dialog just created.
  const baseline = [...readManualTransactions(month), ...res.transactions.transactions];
  const activeTxns = applyActiveOverlays(baseline);
  const activeAttention = applyActiveOverlays(attentionSource).filter((t) => !t.category_audit);
  const trash = mergeTrashOverlay(month, res.trash.transactions, baseline);
  return {
    ...res,
    transactions: { ...res.transactions, count: activeTxns.length, transactions: activeTxns },
    attention: { ...res.attention, count: activeAttention.length, transactions: activeAttention },
    trash: { ...res.trash, count: trash.length, transactions: trash },
  };
}

/**
 * Merge trash: baseline trash fixture items stay unless restored via overlay
 * (and aren't tombstoned); active items deleted via overlay appear here.
 */
function mergeTrashOverlay(
  _month: string,
  baselineTrash: Transaction[],
  baselineActive: Transaction[]
): Transaction[] {
  const categoryMerged = [
    ...applyCategoryOverrides(baselineTrash),
    ...applyCategoryOverrides(baselineActive),
  ];
  const stateMerged = applyTxState(categoryMerged);
  const seen = new Set<string>();
  const out: Transaction[] = [];
  for (const t of stateMerged) {
    const k = `${t.forwarded_to}:${t.date_file_name}`;
    if (seen.has(k)) continue;
    seen.add(k);
    const ov = readOverlay(txStateKey(t.forwarded_to, t.date_file_name));
    if (ov?.tombstone) continue;
    if (t.deleted_at) out.push(t);
  }
  return out;
}

export async function fetchBulkTransactions(months: string[]): Promise<BulkTransactionsResponse> {
  const out: BulkTransactionsResponse = {};
  for (const m of months) {
    try {
      out[m] = await fetchAllTransactions(m);
    } catch {
      // Skip months without fixtures
    }
  }
  return out;
}

export function fetchCategories(): Promise<CategoriesResponse> {
  return loadFixture<CategoriesResponse>("categories");
}

export function updateCategory(
  forwardedTo: string,
  dateFileName: string,
  category: string
): Promise<CategoryUpdateResponse> {
  writeOverlay(categoryOverrideKey(forwardedTo, dateFileName), category);
  return Promise.resolve({
    tx_id: txIdFromComposite(forwardedTo, dateFileName),
    forwarded_to: forwardedTo,
    date_file_name: dateFileName,
    old_category: null,
    new_category: category,
  });
}

function patchTxState(
  forwardedTo: string,
  dateFileName: string,
  patch: TxStateOverlay
): TxStateOverlay {
  const key = txStateKey(forwardedTo, dateFileName);
  const existing = readOverlay(key) ?? {};
  const next = { ...existing, ...patch };
  writeOverlay(key, next);
  return next;
}

export function markReviewed(forwardedTo: string, dateFileName: string): Promise<ReviewResponse> {
  patchTxState(forwardedTo, dateFileName, { reviewed: true });
  return Promise.resolve({
    tx_id: txIdFromComposite(forwardedTo, dateFileName),
    forwarded_to: forwardedTo,
    date_file_name: dateFileName,
    source: "manual",
  });
}

export function setIgnored(
  forwardedTo: string,
  dateFileName: string,
  ignored: boolean
): Promise<IgnoreResponse> {
  patchTxState(forwardedTo, dateFileName, { ignored });
  return Promise.resolve({
    tx_id: txIdFromComposite(forwardedTo, dateFileName),
    forwarded_to: forwardedTo,
    date_file_name: dateFileName,
    ignored,
  });
}

export function setComment(
  forwardedTo: string,
  dateFileName: string,
  comment: string | null
): Promise<CommentResponse> {
  patchTxState(forwardedTo, dateFileName, { comment });
  return Promise.resolve({
    tx_id: txIdFromComposite(forwardedTo, dateFileName),
    forwarded_to: forwardedTo,
    date_file_name: dateFileName,
    comment,
  });
}

export function softDeleteTransaction(
  forwardedTo: string,
  dateFileName: string,
  deleted: boolean
): Promise<DeleteResponse> {
  const deleted_at = deleted ? new Date().toISOString() : null;
  patchTxState(forwardedTo, dateFileName, { deleted_at });
  return Promise.resolve({
    tx_id: txIdFromComposite(forwardedTo, dateFileName),
    forwarded_to: forwardedTo,
    date_file_name: dateFileName,
    deleted_at,
  });
}

export async function fetchTrash(month: string): Promise<TransactionListResponse> {
  const baselineTrash = await loadFixture<TransactionListResponse>(monthSlug("trash", month)).catch(
    () => ({ month, count: 0, transactions: [] }) as TransactionListResponse
  );
  const baselineActive = await loadFixture<TransactionListResponse>(
    monthSlug("transactions", month)
  ).catch(() => ({ month, count: 0, transactions: [] }) as TransactionListResponse);
  const trash = mergeTrashOverlay(month, baselineTrash.transactions, baselineActive.transactions);
  return { month, count: trash.length, transactions: trash };
}

export function permanentlyDeleteTransaction(
  forwardedTo: string,
  dateFileName: string
): Promise<PermanentDeleteResponse> {
  patchTxState(forwardedTo, dateFileName, { tombstone: true });
  return Promise.resolve({
    tx_id: txIdFromComposite(forwardedTo, dateFileName),
    forwarded_to: forwardedTo,
    date_file_name: dateFileName,
  });
}

export function updateTransactionFields(
  _forwardedTo: string,
  _dateFileName: string,
  _fields: { company?: string; amount?: number; transaction_type?: string }
): Promise<TransactionFieldsUpdateResponse> {
  throw new DemoModeError("updateTransactionFields is disabled in the demo.");
}

/** date_file_name leads with "YYYY.MM.DD_" — enough to find the row's month. */
function monthFromDateFileName(dateFileName: string): string | null {
  const m = /^(\d{4})\.(\d{2})\./.exec(dateFileName);
  return m ? `${m[1]}-${m[2]}` : null;
}

export async function fetchTransactionDetail(
  forwardedTo: string,
  dateFileName: string
): Promise<TransactionDetail> {
  const month = monthFromDateFileName(dateFileName);
  const matches = (t: Transaction) =>
    t.forwarded_to === forwardedTo && t.date_file_name === dateFileName;
  let row: Transaction | undefined;
  if (month) {
    row = readManualTransactions(month).find(matches);
    if (!row) {
      const fixture = await loadFixture<TransactionListResponse>(
        monthSlug("transactions", month)
      ).catch(() => null);
      row = fixture?.transactions.find(matches);
    }
  }
  if (!row) {
    throw new DemoFixtureMissingError(monthSlug("transactions", month ?? "unknown"));
  }
  // Overlay edits (comments in particular) feed the synthetic email content.
  const [overlaid] = applyTxState(applyCategoryOverrides([row]));
  return {
    tx_id: txIdFromComposite(forwardedTo, dateFileName),
    forwarded_to: forwardedTo,
    date_file_name: dateFileName,
    ...buildDemoEmail(overlaid ?? row),
  };
}

export async function fetchJournal(month: string): Promise<JournalResponse> {
  let res: JournalResponse;
  try {
    res = await loadFixture<JournalResponse>(monthSlug("journal", month));
  } catch {
    // Months outside the fixture range are real empty months, not errors —
    // the Journal page renders its "No transactions this month." state.
    return { month, days: [], month_total: 0, transaction_count: 0, budget_ceiling: null };
  }
  return {
    ...res,
    days: res.days.map((day) => ({
      ...day,
      transactions: applyActiveOverlays(day.transactions),
    })),
  };
}

export async function fetchJournalSummaries(month: string): Promise<JournalSummariesResponse> {
  try {
    return await loadFixture<JournalSummariesResponse>(monthSlug("journal-summaries", month));
  } catch {
    return { month, summaries: {} };
  }
}

export function fetchJournalSummaryStatus(): Promise<JournalSummaryStatus> {
  return Promise.resolve({
    status: "idle",
    month: null,
    completed: 0,
    total: 0,
    error: null,
  });
}

export function generateJournalSummaries(
  _month: string,
  _dates: string[],
  _force: boolean = false
): Promise<{ status: string; month: string; dates_queued: number }> {
  throw new DemoModeError("Summary generation is disabled in the demo.");
}

export function testOpenAiConnection(_apiKey: string): Promise<{ ok: boolean; error?: string }> {
  throw new DemoModeError("OpenAI testing is disabled in the demo.");
}

export function startChatgptLogin(): Promise<{ verification_url: string; user_code: string }> {
  throw new DemoModeError("ChatGPT connection is disabled in the demo.");
}

export function fetchChatgptLoginStatus(): Promise<{
  connected: boolean;
  pending: boolean;
  email: string | null;
  error: string | null;
  verification_url: string | null;
  user_code: string | null;
}> {
  return Promise.resolve({
    connected: false,
    pending: false,
    email: null,
    error: null,
    verification_url: null,
    user_code: null,
  });
}

export function disconnectChatgpt(): Promise<{ ok: boolean }> {
  throw new DemoModeError("ChatGPT disconnect is disabled in the demo.");
}

export async function fetchSummary(month: string): Promise<SummaryComparisonResponse> {
  return loadFixture<SummaryComparisonResponse>(monthSlug("summary", month));
}

export async function fetchTrend(_months?: number, _endMonth?: string): Promise<TrendResponse> {
  return loadFixture<TrendResponse>("summary-trend");
}

export async function fetchBudgetConfig(year: number): Promise<BudgetConfigResponse | null> {
  try {
    const cfg = await loadFixture<BudgetConfigResponse>(`budget-config-${year}`);
    return applyBudgetOverlay(cfg);
  } catch {
    return null;
  }
}

export async function updateBudgetConfig(
  year: number,
  data: BudgetConfigUpdateRequest
): Promise<BudgetConfigResponse> {
  writeOverlay(budgetOverrideKey(year), data);
  const base = await loadFixture<BudgetConfigResponse>(`budget-config-${year}`).catch(() => null);
  if (base) return applyBudgetOverlay(base);
  // Synthesize a minimal response
  const categories = Object.fromEntries(
    Object.entries(data.categories).map(([name, input]) => [
      name,
      {
        target: input.target,
        input_mode: input.input_mode,
        monthly_amount: input.input_mode === "monthly" ? input.target : input.target / 12,
        category_type: input.category_type,
      },
    ])
  );
  const allocated_total = Object.values(categories).reduce(
    (s, c) => s + (c.input_mode === "monthly" ? c.target * 12 : c.target),
    0
  );
  return {
    year,
    spending_ceiling: data.spending_ceiling,
    categories,
    groups: data.groups,
    targets_version: (data.targets_version ?? 0) + 1,
    groups_version: (data.groups_version ?? 0) + 1,
    allocated_total,
    unallocated: data.spending_ceiling - allocated_total,
  };
}

export async function fetchBudgetStatus(
  year: number,
  _compareYear?: number
): Promise<BudgetStatusResponse> {
  return loadFixture<BudgetStatusResponse>(`budget-status-${year}`);
}

export function fetchHistoricalAverages(_months?: number): Promise<HistoricalAveragesResponse> {
  return loadFixture<HistoricalAveragesResponse>("budget-historical").catch(() => ({
    months_analyzed: 0,
    period: {},
    categories: {},
  }));
}

// ---------------------------------------------------------------------------
// Category Groups
// ---------------------------------------------------------------------------

export function fetchGroups(year: number): Promise<GroupsResponse> {
  return loadFixture<GroupsResponse>(`groups-${year}`);
}

export function updateGroups(_year: number, _data: GroupsUpdateRequest): Promise<GroupsResponse> {
  throw new DemoModeError("Group updates are disabled in the demo.");
}

export function fetchSavedInsightsList(month: string): Promise<SavedInsightSummary[]> {
  return loadFixture<SavedInsightSummary[]>(`insights-saved-${month}`).catch(() => []);
}

export async function fetchSavedInsight(id: string, month: string): Promise<SavedInsight> {
  const list = await loadFixture<SavedInsight[]>(`insights-saved-full-${month}`).catch(() => null);
  if (list) {
    const found = list.find((s) => s.id === id);
    if (found) return found;
  }
  return loadFixture<SavedInsight>(`insight-${month}-${id}`);
}

// ---------------------------------------------------------------------------
// Insights context (deltas + anomalies) — computed on the fly from the same
// summary fixtures used elsewhere, to mirror the backend code path.
// ---------------------------------------------------------------------------

// Async fixture-loading wrapper around the pure `computeCategoryAnomalies`
// kernel (demoAnalytics.ts). I/O stays here; scoring lives in the kernel.
async function computeAnomalies(month: string): Promise<CategoryAnomaly[]> {
  const baselineMonths = Array.from({ length: 6 }, (_, i) => shiftMonth(month, -(6 - i)));
  const baselineSummaries = await Promise.all(
    baselineMonths.map((ym) =>
      loadFixture<SummaryComparisonResponse>(monthSlug("summary", ym))
        .then((s) => s.current?.by_category ?? {})
        .catch(() => ({}) as SummaryComparisonResponse["current"]["by_category"])
    )
  );
  const targetSummary = await loadFixture<SummaryComparisonResponse>(
    monthSlug("summary", month)
  ).catch(() => null);
  if (!targetSummary) return [];

  return computeCategoryAnomalies(baselineSummaries, targetSummary.current?.by_category ?? {});
}

// ---------------------------------------------------------------------------
// Merchant intelligence — computed on the fly from per-month summary fixtures.
// ---------------------------------------------------------------------------

function isRecognizableMerchant(name: string): boolean {
  const s = name.trim();
  if (!s) return false;
  if (s.toLowerCase() === "unknown") return false;
  if (s.includes("|")) return false;
  if (s.toLowerCase().includes("for the amount of")) return false;
  return true;
}

export function fetchCoverage(): Promise<CoverageResponse> {
  return loadFixture<CoverageResponse>("coverage");
}

export async function fetchMerchantIntelligence(
  month: string,
  months: number = 6
): Promise<MerchantIntelligenceResponse> {
  const windowKeys = Array.from({ length: months }, (_, i) => shiftMonth(month, -(months - 1 - i)));
  const summaries = await Promise.all(
    windowKeys.map((ym) =>
      loadFixture<SummaryComparisonResponse>(monthSlug("summary", ym)).catch(() => null)
    )
  );
  const targetSummary = summaries[summaries.length - 1];

  const perMerchantAmounts = new Map<string, number[]>();
  const perMerchantCounts = new Map<string, number[]>();
  const latestCategory = new Map<string, string>();

  summaries.forEach((s, idx) => {
    if (!s?.current?.by_company) return;
    for (const [company, info] of Object.entries(s.current.by_company)) {
      if (!isRecognizableMerchant(company)) continue;
      if (!perMerchantAmounts.has(company)) {
        perMerchantAmounts.set(company, Array(months).fill(0));
        perMerchantCounts.set(company, Array(months).fill(0));
      }
      const amounts = perMerchantAmounts.get(company);
      const counts = perMerchantCounts.get(company);
      if (amounts) amounts[idx] = info.amount ?? 0;
      if (counts) counts[idx] = info.count ?? 0;
      if (info.category) latestCategory.set(company, info.category);
    }
  });

  const merchants: MerchantRecord[] = [];
  for (const [company, amounts] of perMerchantAmounts) {
    const counts = perMerchantCounts.get(company) ?? [];
    const monthsActive = amounts.filter((a) => a > 0).length;
    const total = Math.round(amounts.reduce((s, v) => s + v, 0) * 100) / 100;
    const avgActive = monthsActive > 0 ? total / monthsActive : 0;
    let cv: number | null = null;
    if (monthsActive >= 2) {
      const active = amounts.filter((a) => a > 0);
      const mean = active.reduce((s, v) => s + v, 0) / active.length;
      const variance = active.reduce((s, v) => s + (v - mean) ** 2, 0) / (active.length - 1);
      const stdev = Math.sqrt(variance);
      cv = mean > 0 ? stdev / mean : null;
    }
    const freq = inferMerchantType(monthsActive, months, cv);
    let priceChange: MerchantRecord["price_change"] = null;
    if (freq === "fixed") {
      const positives = amounts.map((a, i) => ({ a, i })).filter((p) => p.a > 0);
      const prev = positives.at(-2);
      const curr = positives.at(-1);
      if (prev && curr) {
        const delta = curr.a - prev.a;
        if (Math.abs(delta) >= 1 && Math.abs(delta) / prev.a >= 0.05) {
          priceChange = {
            old_amount: Math.round(prev.a * 100) / 100,
            new_amount: Math.round(curr.a * 100) / 100,
            since_month: windowKeys[curr.i] ?? month,
          };
        }
      }
    }
    const last = amounts.at(-1) ?? 0;
    const prevToLast = amounts.at(-2) ?? 0;
    const earlier = amounts.slice(0, -2);
    const isNew = last > 0 && prevToLast > 0 && earlier.every((a) => a === 0);
    const isChurned =
      amounts.slice(-2).every((a) => a === 0) &&
      amounts.slice(0, -2).filter((a) => a > 0).length >= Math.max(2, months - 2 - 1);

    merchants.push({
      company,
      total,
      monthly_amounts: amounts.map((a) => Math.round(a * 100) / 100),
      monthly_counts: counts,
      months_active: monthsActive,
      avg_amount: Math.round(avgActive * 100) / 100,
      frequency_type: freq,
      category: latestCategory.get(company) ?? "miscellaneous",
      is_recurring: freq === "fixed" || freq === "variable",
      price_change: priceChange,
      is_new: isNew,
      is_churned: isChurned,
    });
  }
  merchants.sort((a, b) => b.total - a.total);

  const burn =
    Math.round(
      merchants.filter((m) => m.frequency_type === "fixed").reduce((s, m) => s + m.avg_amount, 0) *
        100
    ) / 100;
  const recurringCount = merchants.filter((m) => m.frequency_type === "fixed").length;
  const totalThisMonth = targetSummary?.current?.total_spending ?? 0;
  const priceChanges: MerchantPriceChangeRow[] = merchants.flatMap((m) =>
    m.price_change
      ? [
          {
            merchant: m.company,
            old_amount: m.price_change.old_amount,
            new_amount: m.price_change.new_amount,
            since_month: m.price_change.since_month,
          },
        ]
      : []
  );

  return {
    month,
    months_analyzed: months,
    period: { from: windowKeys[0] ?? month, to: windowKeys[months - 1] ?? month },
    merchants,
    summary: {
      recurring_burn_rate: burn,
      recurring_count: recurringCount,
      discretionary_this_month: Math.round((totalThisMonth - burn) * 100) / 100,
      new_merchants: merchants.filter((m) => m.is_new).map((m) => m.company),
      churned_merchants: merchants.filter((m) => m.is_churned).map((m) => m.company),
      price_changes: priceChanges,
    },
  };
}

export async function fetchInsightsContext(month: string): Promise<InsightsContext> {
  const summary = await loadFixture<SummaryComparisonResponse>(monthSlug("summary", month));
  const deltas = topCategoryDeltas(summary.current, summary.previous);
  const anomalies = await computeAnomalies(month);
  return {
    generated_at: new Date().toISOString(),
    month,
    current_month: summary.current as unknown as Record<string, unknown>,
    previous_month: summary.previous as unknown as Record<string, unknown> | null,
    delta: { amount: summary.delta_amount ?? 0, percent: summary.delta_percent ?? 0 },
    trend: [],
    budget: null,
    pace: null,
    historical_averages: {},
    category_deltas: deltas,
    anomalies,
    largest_transactions: [],
    suspected_ignored: [],
    commented_transactions: [],
  };
}

// ---------------------------------------------------------------------------
// Category Overrides
// ---------------------------------------------------------------------------

function mergeOverrideOverlay(baseline: OverrideListResponse): OverrideListResponse {
  const overlays = listByPrefix<OverrideOverlay>("override:");
  if (overlays.length === 0) return baseline;
  const map = new Map<string, OverrideOverlay>();
  for (const { key, value } of overlays) {
    map.set(key.slice("override:".length), value);
  }
  const merged = baseline.overrides
    .filter((o) => {
      const ov = map.get(o.company);
      return ov?.action !== "delete";
    })
    .map((o) => {
      const ov = map.get(o.company);
      if (ov && ov.action === "set") return { ...o, category: ov.category };
      return o;
    });
  const existing = new Set(merged.map((o) => o.company));
  for (const [company, ov] of map.entries()) {
    if (ov.action === "set" && !existing.has(company)) {
      merged.push({ company, category: ov.category });
    }
  }
  return { ...baseline, overrides: merged, count: merged.length };
}

export async function fetchOverrides(): Promise<OverrideListResponse> {
  const base = await loadFixture<OverrideListResponse>("overrides");
  return mergeOverrideOverlay(base);
}

export async function putOverride(
  company: string,
  category: string
): Promise<OverrideListResponse> {
  writeOverlay(overrideKey(company), { action: "set", category });
  return fetchOverrides();
}

export async function deleteOverride(company: string): Promise<void> {
  writeOverlay(overrideKey(company), { action: "delete" });
  return Promise.resolve();
}

export async function fetchOverrideSuggestions(
  _months?: number
): Promise<OverrideSuggestionsResponse> {
  const base = await loadFixture<OverrideSuggestionsResponse>("overrides-suggestions").catch(
    () => ({ suggestions: [], count: 0 }) as OverrideSuggestionsResponse
  );
  const dismissed = new Set(
    listByPrefix<true>("override-dismissed:").map(({ key }) =>
      key.slice("override-dismissed:".length)
    )
  );
  if (dismissed.size === 0) return base;
  const suggestions = base.suggestions.filter(
    (s) => !dismissed.has(`${s.company}:${s.suggested_category}`)
  );
  return { ...base, suggestions, count: suggestions.length };
}

export function dismissSuggestion(company: string, category: string): Promise<void> {
  writeOverlay(overrideDismissedKey(company, category), true);
  return Promise.resolve();
}

export async function fetchOverrideMatch(_company: string): Promise<OverrideMatchResponse> {
  return { category: null, matched_rule: null, confidence: null, tier: null, candidates: [] };
}

export function fetchOverrideDuplicates(): Promise<OverrideDuplicatesResponse> {
  return loadFixture<OverrideDuplicatesResponse>("overrides-duplicates").catch(() => ({
    groups: [],
    count: 0,
  }));
}

export function consolidateOverrides(_body: OverrideConsolidateRequest): Promise<void> {
  throw new DemoModeError("Consolidate is disabled in the demo.");
}

// ---------------------------------------------------------------------------
// Category Management
// ---------------------------------------------------------------------------

export function fetchManagedCategories(): Promise<CategoriesManagementResponse> {
  return loadFixture<CategoriesManagementResponse>("categories-managed");
}

export function addCategory(
  _name: string,
  _group: string | null
): Promise<CategoriesManagementResponse> {
  throw new DemoModeError("Add category is disabled in the demo.");
}

export function renameCategory(
  _oldName: string,
  _newName: string
): Promise<CategoryRenameResponse> {
  throw new DemoModeError("Rename category is disabled in the demo.");
}

export function deleteCategory(
  _name: string,
  _reassignTo?: string
): Promise<CategoryDeleteResponse> {
  throw new DemoModeError("Delete category is disabled in the demo.");
}

export async function fetchCategoryUsage(name: string): Promise<CategoryUsageResponse> {
  return loadFixture<CategoryUsageResponse>(`category-usage-${encodeURIComponent(name)}`).catch(
    () =>
      ({
        category: name,
        transaction_count: 0,
        override_count: 0,
      }) as unknown as CategoryUsageResponse
  );
}

export function updateCategoryGroup(
  _name: string,
  _group: string | null
): Promise<CategoryGroupUpdateResponse> {
  throw new DemoModeError("Group change is disabled in the demo.");
}

export async function fetchCategoryIcons(): Promise<CategoryIconsResponse> {
  return loadFixture<CategoryIconsResponse>("category-icons").catch(
    () => ({ icons: {}, version: 0 }) as CategoryIconsResponse
  );
}

export function setCategoryIcon(_name: string, _icon: string): Promise<CategoryIconsResponse> {
  throw new DemoModeError("Changing icons is disabled in the demo.");
}

export function clearCategoryIcon(_name: string): Promise<CategoryIconsResponse> {
  throw new DemoModeError("Changing icons is disabled in the demo.");
}

// ---------------------------------------------------------------------------
// Statement Import
// ---------------------------------------------------------------------------

export function uploadStatement(_file: File): Promise<StatementUploadResponse> {
  throw new DemoModeError("Statement upload is disabled in the demo.");
}

export function importStatementTransactions(_data: ImportRequest): Promise<ImportResponse> {
  throw new DemoModeError("Statement import is disabled in the demo.");
}

export function fetchStatements(): Promise<StatementListResponse> {
  return loadFixture<StatementListResponse>("statements").catch(() => {
    return { statements: [] } as unknown as StatementListResponse;
  });
}

export function fetchStatement(_id: string): Promise<StatementDetailResponse> {
  throw new DemoModeError("Statement detail is disabled in the demo.");
}

export function deleteStatement(_id: string): Promise<void> {
  throw new DemoModeError("Delete statement is disabled in the demo.");
}

export function updateTransactionAction(
  _statementId: string,
  _rowId: string,
  _data: TransactionActionUpdate
): Promise<{ ok: boolean; tx_index: number; row_id: string; action: string }> {
  throw new DemoModeError("Transaction action is disabled in the demo.");
}

export function getStatementDownloadUrl(_id: string): string {
  return "";
}

export function reparseStatement(_id: string): Promise<StatementDetailResponse> {
  throw new DemoModeError("Reparse is disabled in the demo.");
}

// ---------------------------------------------------------------------------
// Attachments (receipts & documents) — disabled in the demo
// ---------------------------------------------------------------------------
//
// Reads return empty shapes so the "Receipts to file" affordance stays hidden
// (count 0) and row clusters find no attachments; writes reject with
// DemoModeError. Parity with api.ts is compile-enforced by the vite alias.

const EMPTY_ATTACHMENTS: AttachmentListResponse = { count: 0, attachments: [] };

export function uploadAttachment(
  _file: File,
  _txId?: string,
  _kind?: string
): Promise<AttachmentResponse> {
  throw new DemoModeError("Attachments are disabled in the demo.");
}

export function fetchTransactionAttachments(_txId: string): Promise<AttachmentListResponse> {
  return Promise.resolve(EMPTY_ATTACHMENTS);
}

export function fetchUnlinkedAttachments(): Promise<AttachmentListResponse> {
  return Promise.resolve(EMPTY_ATTACHMENTS);
}

export function linkAttachment(_id: string, _txId: string | null): Promise<AttachmentResponse> {
  throw new DemoModeError("Attachments are disabled in the demo.");
}

export function deleteAttachment(_id: string): Promise<AttachmentDeleteResponse> {
  throw new DemoModeError("Attachments are disabled in the demo.");
}

export function getAttachmentFileUrl(_id: string): string {
  return "";
}

// Parsing is a write (calls the AI provider) — rejected in the demo. Reads that
// depend on a parse never fire because no attachment can be parsed here.
export function parseReceipt(_id: string): Promise<AttachmentResponse> {
  throw new DemoModeError("Attachments are disabled in the demo.");
}

// A read: return an empty, consistent candidates shape. Nothing to match against
// since the demo has no unfiled parsed receipts.
export function fetchReceiptCandidates(id: string): Promise<ReceiptCandidatesResponse> {
  return Promise.resolve({ attachment_id: id, auto_link_candidate: false, candidates: [] });
}

// ---------------------------------------------------------------------------
// Parse failures ("Needs review")
// ---------------------------------------------------------------------------

// The hand-authored fixture carries the email body on each row so the detail
// expand can render it. The list contract omits the body (PII + size), so we
// strip it in listParseFailures and only surface it through getParseFailure —
// mirroring the real API where GET /parse-failures returns summaries only.
type DemoParseFailureRow = ParseFailureSummary & { body: string };
interface DemoParseFailuresFixture {
  count: number;
  failures: DemoParseFailureRow[];
}

function loadParseFailures(): Promise<DemoParseFailuresFixture> {
  return loadFixture<DemoParseFailuresFixture>("parse-failures").catch(
    () => ({ count: 0, failures: [] }) as DemoParseFailuresFixture
  );
}

export async function listParseFailures(
  status?: ParseFailureStatus
): Promise<ParseFailureListResponse> {
  const { failures } = await loadParseFailures();
  const filtered = status ? failures.filter((f) => f.status === status) : failures;
  // Mirror the real API's newest-first ordering (received_at DESC). ISO strings
  // sort lexically in chronological order.
  const sorted = [...filtered].sort((a, b) => b.received_at.localeCompare(a.received_at));
  const summaries: ParseFailureSummary[] = sorted.map(({ body: _body, ...summary }) => summary);
  return { count: summaries.length, failures: summaries };
}

export async function getParseFailure(id: string): Promise<ParseFailureDetail> {
  const { failures } = await loadParseFailures();
  const row = failures.find((f) => f.id === id);
  if (!row) throw new DemoFixtureMissingError(`parse-failures:${id}`);
  return row;
}

export function retryParseFailure(_id: string): Promise<RetryResponse> {
  throw new DemoModeError("Retry is disabled in the demo.");
}

export function retryAllParseFailures(_filter: RetryAllRequest): Promise<RetryAllResponse> {
  throw new DemoModeError("Retry all is disabled in the demo.");
}

export function dismissParseFailure(_id: string): Promise<DismissResponse> {
  throw new DemoModeError("Set aside is disabled in the demo.");
}

// Parity twin — the demo has no backend to write to. The "Needs review" page
// gates the affordance with a calm toast before this is ever reached (same as
// retry/set aside); this guard is the backstop if a caller forgets to gate.
export function resolveParseFailure(
  _id: string,
  _body: ManualResolveRequest
): Promise<ManualResolveResponse> {
  throw new DemoModeError("Manual entry is disabled in the demo.");
}

// ---------------------------------------------------------------------------
// Insights Generation
// ---------------------------------------------------------------------------

export function generateInsights(_month: string): Promise<{ status: string; month: string }> {
  throw new DemoModeError("Insight generation is disabled in the demo.");
}

export function fetchInsightsStatus(): Promise<InsightsStatus> {
  return Promise.resolve({ status: "idle" });
}

// ---------------------------------------------------------------------------
// Merchant Aliases
// ---------------------------------------------------------------------------

export interface MerchantAliasEntry {
  raw_name: string;
  canonical_name: string;
}

export interface MerchantAliasListResponse {
  aliases: MerchantAliasEntry[];
  count: number;
  version: number;
}

export function fetchMerchantAliases(): Promise<MerchantAliasListResponse> {
  return loadFixture<MerchantAliasListResponse>("merchant-aliases");
}

export function putMerchantAlias(
  _rawName: string,
  _canonicalName: string
): Promise<{ ok: boolean }> {
  throw new DemoModeError("Alias updates are disabled in the demo.");
}

export function deleteMerchantAlias(_rawName: string): Promise<void> {
  throw new DemoModeError("Alias deletion is disabled in the demo.");
}

// ---------------------------------------------------------------------------
// Merchant Auto-Ignore Rules
// ---------------------------------------------------------------------------

export function fetchIgnoreRules(): Promise<IgnoreRuleListResponse> {
  return loadFixture<IgnoreRuleListResponse>("ignore-rules").catch(
    () => ({ rules: [], count: 0, version: 0 }) as IgnoreRuleListResponse
  );
}

export function addIgnoreRule(_pattern: string): Promise<IgnoreRuleListResponse> {
  throw new DemoModeError("Auto-ignore rules are disabled in the demo.");
}

export function deleteIgnoreRule(_pattern: string): Promise<void> {
  throw new DemoModeError("Auto-ignore rules are disabled in the demo.");
}

export function fetchIgnoreRuleSuggestions(
  _months?: number
): Promise<IgnoreRuleSuggestionsResponse> {
  return Promise.resolve({ suggestions: [], count: 0 });
}

export function applyIgnoreRules(_pattern?: string): Promise<IgnoreRuleApplyResponse> {
  throw new DemoModeError("Auto-ignore rules are disabled in the demo.");
}

export function dismissIgnoreRuleSuggestion(_merchant: string): Promise<void> {
  throw new DemoModeError("Auto-ignore rules are disabled in the demo.");
}

export function undismissIgnoreRuleSuggestion(_merchant: string): Promise<void> {
  throw new DemoModeError("Auto-ignore rules are disabled in the demo.");
}

export function fetchDismissedIgnoreRuleSuggestions(): Promise<DismissedIgnoreRuleSuggestionsResponse> {
  // The demo seeds no dismissals — suggestions themselves are always empty here.
  return Promise.resolve({ dismissed: [], count: 0 });
}

// ---------------------------------------------------------------------------
// Income Statement
// ---------------------------------------------------------------------------

export function fetchIncomeStatement(year: number): Promise<IncomeStatementResponse> {
  return loadFixture<IncomeStatementResponse>(`income-statement-${year}`);
}

// ---------------------------------------------------------------------------
// Tax pack (CRA claim lines)
// ---------------------------------------------------------------------------

// Read: load the generated tax-pack fixture. The pack is a backend snapshot,
// never computed client-side (the merchant-intelligence JS-port drift is the
// cautionary precedent). Only the demo year (2026) ships a fixture.
export function fetchTaxPack(year: number): Promise<TaxPackResponse> {
  return loadFixture<TaxPackResponse>(`tax-pack-${year}`);
}

// The export streams evidence files from disk and is demo-gated server-side.
export function downloadTaxPack(_year: number): Promise<void> {
  throw new DemoModeError("Tax pack export is disabled in the demo.");
}

// The seven CRA seed lines plus the "other" catch-all. Static (the real
// endpoint is read-only and rarely changes), so no fixture file is needed.
export function fetchTaxLines(): Promise<{ lines: TaxLineOption[] }> {
  return Promise.resolve({
    lines: [
      { key: "charitable", label: "Charitable donations" },
      { key: "medical", label: "Medical expenses" },
      { key: "childcare", label: "Child care expenses" },
      { key: "moving", label: "Moving expenses" },
      { key: "tuition", label: "Tuition and education" },
      { key: "dues", label: "Union and professional dues" },
      { key: "instalments", label: "Tax paid by instalments" },
      { key: "other", label: "Other claimable" },
    ],
  });
}

// Writes: overriding a transaction's tax classification is disabled in the demo.
export function setTaxOverride(
  _txId: string,
  _mode: "include" | "exclude",
  _lineKey?: string
): Promise<void> {
  throw new DemoModeError("Tax classification changes are disabled in the demo.");
}

export function clearTaxOverride(_txId: string): Promise<void> {
  throw new DemoModeError("Tax classification changes are disabled in the demo.");
}

// ---------------------------------------------------------------------------
// Transaction Search
// ---------------------------------------------------------------------------

function monthsInRange(from: string, to: string): string[] {
  // from/to are ISO date strings (YYYY-MM-DD). Return unique YYYY-MM months covered.
  const out: string[] = [];
  const start = new Date(from + "T00:00:00Z");
  const end = new Date(to + "T00:00:00Z");
  const cursor = new Date(Date.UTC(start.getUTCFullYear(), start.getUTCMonth(), 1));
  while (cursor <= end) {
    const y = cursor.getUTCFullYear();
    const m = String(cursor.getUTCMonth() + 1).padStart(2, "0");
    out.push(`${y}-${m}`);
    cursor.setUTCMonth(cursor.getUTCMonth() + 1);
  }
  return out;
}

function matchesSearch(t: Transaction, params: SearchParams): boolean {
  if (!t.date) return false;
  // params.from/params.to are "YYYY-MM" months, but t.date is "MM/DD/YYYY HH:MM TZ".
  // Derive the transaction's "YYYY-MM" month before comparing (formatDate(_, "iso")
  // parses the app's date format; "—" signals an unparseable date → exclude).
  const iso = formatDate(t.date, "iso");
  if (iso === "—") return false;
  const txnMonth = iso.slice(0, 7);
  if (txnMonth < params.from || txnMonth > params.to) return false;
  if (!params.include_ignored && t.ignored) return false;
  if (!params.include_deleted && t.deleted_at) return false;
  if (params.category && t.category !== params.category) return false;
  if (params.institution && t.institution !== params.institution) return false;
  if (params.type && t.transaction_type !== params.type) return false;
  if (params.company && !(t.company ?? "").toLowerCase().includes(params.company.toLowerCase()))
    return false;
  if (params.q) {
    const needle = params.q.toLowerCase();
    const hit = [t.company, t.comment, t.category].some((f) =>
      (f ?? "").toLowerCase().includes(needle)
    );
    if (!hit) return false;
  }
  if (params.min_amount != null && (t.amount ?? 0) < params.min_amount) return false;
  if (params.max_amount != null && (t.amount ?? 0) > params.max_amount) return false;
  return true;
}

export async function searchTransactions(params: SearchParams): Promise<SearchResponse> {
  const months = monthsInRange(params.from, params.to);
  const collected: Transaction[] = [];
  for (const m of months) {
    try {
      const res = await loadFixture<TransactionListResponse>(monthSlug("transactions", m));
      collected.push(...res.transactions);
    } catch {
      // skip missing fixtures
    }
  }
  const withOverrides = applyActiveOverlays(collected);
  const filtered = withOverrides.filter((t) => matchesSearch(t, params));
  const total_amount = filtered.reduce((s, t) => s + (t.amount ?? 0), 0);
  const by_category: Record<string, number> = {};
  for (const t of filtered) {
    const c = t.category ?? "Uncategorized";
    by_category[c] = (by_category[c] ?? 0) + (t.amount ?? 0);
  }
  const CAP = 1000;
  const capped = filtered.length > CAP;
  const summary: SearchSummary = {
    total_count: filtered.length,
    total_amount,
    avg_amount: filtered.length > 0 ? total_amount / filtered.length : 0,
    by_category,
    months_queried: months.length,
  };
  return {
    transactions: capped ? filtered.slice(0, CAP) : filtered,
    summary,
    capped,
    total_matching: filtered.length,
  };
}

export async function downloadExport(params: SearchParams): Promise<void> {
  const { transactions } = await searchTransactions(params);
  const headers = [
    "date",
    "company",
    "category",
    "amount",
    "transaction_type",
    "institution",
    "name",
    "forwarded_to",
    "comment",
  ];
  const escape = (val: unknown): string => {
    const s = val == null ? "" : String(val);
    return /[",\n]/.test(s) ? `"${s.replaceAll('"', '""')}"` : s;
  };
  const lines = [headers.join(",")];
  for (const t of transactions) {
    lines.push(
      [
        t.date,
        t.company,
        t.category,
        t.amount,
        t.transaction_type,
        t.institution,
        t.name,
        t.forwarded_to,
        t.comment,
      ]
        .map(escape)
        .join(",")
    );
  }
  const csv = lines.join("\n") + "\n";
  const blob = new Blob([csv], { type: "text/csv;charset=utf-8" });
  const url = URL.createObjectURL(blob);
  const a = document.createElement("a");
  a.href = url;
  a.download = `transactions_${params.from}_to_${params.to}.csv`;
  document.body.appendChild(a);
  a.click();
  document.body.removeChild(a);
  URL.revokeObjectURL(url);
}

// ---------------------------------------------------------------------------
// Data backup — disabled in demo (the static demo has no writable storage)
// ---------------------------------------------------------------------------

export function downloadBackup(): Promise<void> {
  throw new DemoModeError("Backup export is disabled in the demo.");
}

export function previewImport(_file: File): Promise<never> {
  throw new DemoModeError("Import is disabled in the demo.");
}

export function commitImport(
  _token: string,
  _strategy: string,
  _applyConfig?: boolean
): Promise<never> {
  throw new DemoModeError("Import is disabled in the demo.");
}

// ---------------------------------------------------------------------------
// Activity ledger (agent activity feed)
// ---------------------------------------------------------------------------

// A small, persona-compliant slice of the ledger held inline (L11): a
// `kitchen-agent` bearer token making a handful of edits, dated relative to the
// demo clock so relative timestamps stay sensible. No fixture file — the
// fixture checker scans demo-data/ and this keeps the demo write-free. The set
// covers a same-window burst, one already-reverted entry, and one
// envelope-only (`reversible: false`) entry so the page renders every state.
const DEMO_ACTIVITY_PRINCIPAL = {
  principal_kind: "token",
  principal_id: "kitchen1",
  principal_label: "kitchen-agent",
} as const;

function demoActivityTs(minutesBeforeNow: number): string {
  return new Date(new Date(DEMO_NOW_ISO).getTime() - minutesBeforeNow * 60_000).toISOString();
}

function buildDemoActivity(): ActivityListResponse {
  const entries: ActivityListResponse["entries"] = [
    {
      ...DEMO_ACTIVITY_PRINCIPAL,
      id: "demo-act-1",
      ts: demoActivityTs(2),
      operation_id: "patchTransaction",
      method: "PATCH",
      path: "/api/v1/transactions/demo-tx-groceries",
      resource_id: "demo-tx-groceries",
      summary: "Category set to Groceries",
      before: { Category: "Uncategorized" },
      after: { Category: "Groceries" },
      reversible: true,
      reverted_at: null,
      reverted_by: null,
    },
    {
      ...DEMO_ACTIVITY_PRINCIPAL,
      id: "demo-act-2",
      ts: demoActivityTs(6),
      operation_id: "putOverride",
      method: "PUT",
      path: "/api/v1/overrides/Uber%20Eats",
      resource_id: "Uber Eats",
      summary: "Override added: Uber Eats to Dining",
      before: {},
      after: { category: "Dining" },
      reversible: true,
      reverted_at: null,
      reverted_by: null,
    },
    {
      ...DEMO_ACTIVITY_PRINCIPAL,
      id: "demo-act-3",
      ts: demoActivityTs(9),
      operation_id: "setTransactionComment",
      method: "PUT",
      path: "/api/v1/transactions/demo-tx-transit/comment",
      resource_id: "demo-tx-transit",
      summary: "Comment updated",
      before: { Comment: "" },
      after: { Comment: "work travel" },
      reversible: true,
      reverted_at: null,
      reverted_by: null,
    },
    {
      ...DEMO_ACTIVITY_PRINCIPAL,
      id: "demo-act-4",
      ts: demoActivityTs(60 * 26),
      operation_id: "bulkUpdateTransactionCategory",
      method: "POST",
      path: "/api/v1/transactions/bulk-category",
      resource_id: null,
      summary: "Recategorized 4 transactions to Subscriptions",
      before: { rows: 4 },
      after: { category: "Subscriptions" },
      reversible: true,
      reverted_at: demoActivityTs(60 * 25),
      reverted_by: "demo-act-4-revert",
    },
    {
      ...DEMO_ACTIVITY_PRINCIPAL,
      id: "demo-act-5",
      ts: demoActivityTs(60 * 50),
      operation_id: "generateInsights",
      method: "POST",
      path: "/api/v1/insights/generate",
      resource_id: null,
      summary: null,
      before: null,
      after: null,
      reversible: false,
      reverted_at: null,
      reverted_by: null,
    },
  ];
  return { entries };
}

export function fetchActivity(_params: ActivityFilters = {}): Promise<ActivityListResponse> {
  return Promise.resolve(buildDemoActivity());
}

export function revertActivity(_id: string, _force?: boolean): Promise<RevertResponse> {
  throw new DemoModeError("Revert is disabled in the demo.");
}

export function fetchWhoami(): Promise<WhoamiResponse> {
  throw new DemoModeError("whoami is disabled in the demo.");
}
