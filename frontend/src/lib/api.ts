import { ApiError } from "@/lib/apiError";
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
  InsightsContext,
  MerchantIntelligenceResponse,
  IgnoreResponse,
  ImportPreviewResponse,
  ImportRequest,
  DismissedIgnoreRuleSuggestionsResponse,
  IgnoreRuleApplyResponse,
  IgnoreRuleListResponse,
  IgnoreRuleSuggestionsResponse,
  ImportResponse,
  ImportResult,
  ImportStrategy,
  IncomeStatementResponse,
  InsightsStatus,
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
  PermanentDeleteResponse,
  ReceiptCandidatesResponse,
  ReviewResponse,
  RetryAllRequest,
  RetryAllResponse,
  RetryResponse,
  RevertResponse,
  SavedInsight,
  SavedInsightList,
  SavedInsightSummary,
  S3BackupStatus,
  SearchParams,
  SearchResponse,
  StatementDetailResponse,
  StatementListResponse,
  StatementUploadResponse,
  SummaryComparisonResponse,
  TaxPackResponse,
  TestS3BackupResponse,
  TransactionActionUpdate,
  TransactionDetail,
  TransactionFieldsUpdateResponse,
  TransactionListResponse,
  TransactionType,
  TrendResponse,
  WhoamiResponse,
} from "@/types/api";

// ---------------------------------------------------------------------------
// Contents (line numbers approximate; sections demarcated by `// ---` below)
//   App Config ............................. L119
//   Health / liveness probe ................ L135
//   Auth (Phase 4 cookie session) .......... L143
//   Manual Transaction Entry ............... L188
//   Transactions ........................... L239
//   Category Groups ........................ L453
//   Category Overrides ..................... L503
//   Category Management .................... L570
//   Category Icon Overrides ................ L630
//   Statement Import ....................... L652
//   Insights Generation .................... L716
//   Merchant Aliases ....................... L739
//   Income Statement ....................... L773
//   Transaction Search ..................... L781
//   Data backup (Settings tab) ............. L818
// ---------------------------------------------------------------------------

const BASE = "/api/v1";

// URL-safe surrogate id; mirrors `src/finance/tx_id.py`. Composite keys
// no longer appear in path URLs (Tier 2 stable-tx-id migration). The
// legacy `/transactions/{forwarded_to}/{date_file_name}` shape still
// works via 308 redirect, but we build the canonical URL directly so
// callers don't pay the redirect hop.
export function txIdFromComposite(forwardedTo: string, dateFileName: string): string {
  const raw = `${forwardedTo}|${dateFileName}`;
  const bytes = new TextEncoder().encode(raw);
  let bin = "";
  for (const b of bytes) bin += String.fromCharCode(b);
  return btoa(bin).replace(/\+/g, "-").replace(/\//g, "_").replace(/=+$/, "");
}

function txnPath(forwardedTo: string, dateFileName: string): string {
  return `${BASE}/transactions/${txIdFromComposite(forwardedTo, dateFileName)}`;
}

// Phase 4: cookie session lives on the same origin as the SPA; every fetch
// must opt in to credentials so the cookie travels. A bare 401 anywhere
// dispatches `tidings:auth-required` so the AuthBoundary can re-render the
// LoginGate on demand mid-session.
export const AUTH_REQUIRED_EVENT = "tidings:auth-required";

// Dispatched after a successful set-password / login so the AuthBoundary
// re-probes /health and dismisses the SetupBanner without a hard reload.
export const AUTH_STATE_CHANGED_EVENT = "tidings:auth-state-changed";

// Every api.ts request funnels through these four helpers so the whole client
// shares one error contract: on any non-2xx they throw the structured
// `ApiError` carrying the backend's `{error, code, details}` envelope (and a
// populated `.status`), and a bare 401 signals the AuthBoundary. `fetchJSON`
// covers JSON request/response; `postFormData` covers multipart uploads;
// `downloadFile` covers binary/blob downloads. Raw `fetch` should not appear
// below — reach for one of these instead.

interface FetchJSONOptions {
  /** Return null instead of throwing when the server answers 404 (for
   *  endpoints where "not found" is a valid empty state, not a failure). */
  allow404?: boolean;
  /** Skip the AUTH_REQUIRED dispatch on 401. Set it for endpoints where a 401
   *  is an expected in-band result the caller handles itself (e.g. a wrong
   *  current-password on change-password), so it must not eject the session. */
  skipAuthEvent?: boolean;
}

// Parses the backend's unified `{error, code, details}` body (src/api/errors.py)
// and throws the structured ApiError. Falls back to status prose when the body
// isn't that shape (proxies, hard 502s). Shared by every request helper below.
async function throwApiError(res: Response): Promise<never> {
  let message = `API error: ${res.status} ${res.statusText}`;
  let code = `HTTP_${res.status}`;
  let details: unknown = null;
  try {
    const body: unknown = await res.json();
    if (body !== null && typeof body === "object") {
      const b = body as { error?: unknown; code?: unknown; details?: unknown };
      if (typeof b.error === "string" && b.error) message = b.error;
      if (typeof b.code === "string" && b.code) code = b.code;
      details = b.details ?? null;
    }
  } catch {
    // non-JSON error body — keep the fallback message
  }
  throw new ApiError(res.status, code, message, details);
}

// A bare 401 dispatches `tidings:auth-required` so the AuthBoundary can
// re-render the LoginGate mid-session. `/auth/login` is exempt (a failed login
// is an in-band result, not a dropped session); `skipAuthEvent` exempts other
// endpoints that handle their own 401.
function maybeSignalAuthRequired(res: Response, url: string, opts?: FetchJSONOptions): void {
  if (res.status === 401 && !opts?.skipAuthEvent && !url.endsWith("/auth/login")) {
    window.dispatchEvent(new CustomEvent(AUTH_REQUIRED_EVENT));
  }
}

// Reads the success body, tolerating an empty payload (204 No Content, or a
// zero-length 200 from a void-returning write) instead of throwing on
// JSON.parse.
async function parseJsonBody<T>(res: Response): Promise<T> {
  if (res.status === 204) return undefined as T;
  const text = await res.text();
  return (text ? JSON.parse(text) : undefined) as T;
}

async function fetchJSON<T>(url: string, init?: RequestInit, opts?: FetchJSONOptions): Promise<T> {
  const res = await fetch(url, { credentials: "same-origin", ...init });
  maybeSignalAuthRequired(res, url, opts);
  if (opts?.allow404 && res.status === 404) return null as T;
  if (!res.ok) await throwApiError(res);
  return parseJsonBody<T>(res);
}

// Multipart uploads: the request body is FormData (not JSON), but the response
// and error envelope are identical to fetchJSON's, so uploads share the same
// ApiError contract. Kept separate because fetchJSON must never stringify a File.
async function postFormData<T>(url: string, formData: FormData): Promise<T> {
  const res = await fetch(url, { method: "POST", credentials: "same-origin", body: formData });
  maybeSignalAuthRequired(res, url);
  if (!res.ok) await throwApiError(res);
  return parseJsonBody<T>(res);
}

// Blob downloads: the success body is a binary stream we hand to the browser as
// a file, so it can't go through fetchJSON (which parses JSON). Errors still
// surface as ApiError via the shared envelope parser.
async function downloadFile(url: string, filename: string, init?: RequestInit): Promise<void> {
  const res = await fetch(url, { credentials: "same-origin", ...init });
  maybeSignalAuthRequired(res, url);
  if (!res.ok) await throwApiError(res);
  const blob = await res.blob();
  const objectUrl = URL.createObjectURL(blob);
  const a = document.createElement("a");
  a.href = objectUrl;
  a.download = filename;
  document.body.appendChild(a);
  a.click();
  document.body.removeChild(a);
  URL.revokeObjectURL(objectUrl);
}

// ---------------------------------------------------------------------------
// App Config
// ---------------------------------------------------------------------------

export function fetchConfig(): Promise<AppConfig> {
  return fetchJSON(`${BASE}/config`);
}

export function updateConfig(data: AppConfigUpdate): Promise<AppConfig> {
  return fetchJSON(`${BASE}/config`, {
    method: "PUT",
    headers: { "Content-Type": "application/json" },
    body: JSON.stringify(data),
  });
}

// Stateless verify for the S3 backup target: checks the bucket is reachable and
// writable with the current credentials and persists nothing. The caller saves
// the verified bucket/prefix separately via updateConfig on `ok`.
export function testS3Backup(bucket: string, prefix: string | null): Promise<TestS3BackupResponse> {
  return fetchJSON(`${BASE}/config/test-s3-backup`, {
    method: "POST",
    headers: { "Content-Type": "application/json" },
    body: JSON.stringify({ bucket, prefix }),
  });
}

export function fetchS3BackupStatus(): Promise<S3BackupStatus> {
  return fetchJSON(`${BASE}/data/s3-backup-status`);
}

// ---------------------------------------------------------------------------
// Health / liveness probe
// ---------------------------------------------------------------------------

export function fetchHealth(): Promise<HealthStatus> {
  return fetchJSON(`${BASE}/health`);
}

// ---------------------------------------------------------------------------
// Auth (Phase 4 cookie session)
// ---------------------------------------------------------------------------

export type AuthOk = { status: string };

export function setAppPassword(args: {
  password: string;
  current_password?: string;
}): Promise<AuthOk> {
  // A wrong current-password returns 401 as an in-band result the change-password
  // form surfaces itself — `skipAuthEvent` keeps it from ejecting the session.
  return fetchJSON(
    `${BASE}/auth/set-password`,
    {
      method: "POST",
      headers: { "Content-Type": "application/json" },
      body: JSON.stringify(args),
    },
    { skipAuthEvent: true }
  );
}

export function loginWithPassword(password: string): Promise<AuthOk> {
  // fetchJSON exempts `/auth/login` from the auth-required dispatch: a failed
  // login is an in-band result, not a dropped session. The backend envelope's
  // `error` ("invalid password") flows through as ApiError.message.
  return fetchJSON(`${BASE}/auth/login`, {
    method: "POST",
    headers: { "Content-Type": "application/json" },
    body: JSON.stringify({ password }),
  });
}

export function logout(): Promise<AuthOk> {
  return fetchJSON(`${BASE}/auth/logout`, { method: "POST" });
}

export function signOutAllDevices(): Promise<AuthOk> {
  return fetchJSON(`${BASE}/auth/sign-out-all`, { method: "POST" });
}

// ---------------------------------------------------------------------------
// Manual Transaction Entry
// ---------------------------------------------------------------------------

export interface ManualTransactionRequest {
  date: string;
  amount: number;
  company: string;
  category?: string | undefined;
  transaction_type?: TransactionType | undefined;
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
  return fetchJSON(`${BASE}/transactions`, {
    method: "POST",
    headers: { "Content-Type": "application/json" },
    body: JSON.stringify(data),
  });
}

export async function uploadEml(file: File): Promise<{
  status: string;
  date_file_name?: string;
  company?: string;
  amount?: number;
  category?: string;
}> {
  const formData = new FormData();
  formData.append("file", file);
  return postFormData(`${BASE}/transactions/upload-eml`, formData);
}

// ---------------------------------------------------------------------------
// Transactions
// ---------------------------------------------------------------------------

export function fetchTransactions(month: string): Promise<TransactionListResponse> {
  return fetchJSON(`${BASE}/transactions?month=${encodeURIComponent(month)}`);
}

export function fetchAttentionQueue(month: string): Promise<AttentionListResponse> {
  return fetchJSON(`${BASE}/transactions/attention?month=${encodeURIComponent(month)}`);
}

export function fetchLatestTimestamp(month?: string): Promise<LatestTimestampResponse> {
  const qs = month ? `?month=${encodeURIComponent(month)}` : "";
  return fetchJSON(`${BASE}/transactions/latest${qs}`);
}

export function fetchAllTransactions(month: string): Promise<CombinedTransactionsResponse> {
  return fetchJSON(`${BASE}/transactions/all?month=${encodeURIComponent(month)}`);
}

export function fetchBulkTransactions(months: string[]): Promise<BulkTransactionsResponse> {
  return fetchJSON(`${BASE}/transactions/bulk?months=${encodeURIComponent(months.join(","))}`);
}

export function fetchCategories(): Promise<CategoriesResponse> {
  return fetchJSON(`${BASE}/categories`);
}

export function updateCategory(
  forwardedTo: string,
  dateFileName: string,
  category: string
): Promise<CategoryUpdateResponse> {
  return fetchJSON(txnPath(forwardedTo, dateFileName), {
    method: "PATCH",
    headers: { "Content-Type": "application/json" },
    body: JSON.stringify({ category }),
  });
}

export function markReviewed(forwardedTo: string, dateFileName: string): Promise<ReviewResponse> {
  return fetchJSON(txnPath(forwardedTo, dateFileName) + "/review", { method: "POST" });
}

export function setIgnored(
  forwardedTo: string,
  dateFileName: string,
  ignored: boolean
): Promise<IgnoreResponse> {
  return fetchJSON(txnPath(forwardedTo, dateFileName) + "/ignore", {
    method: "POST",
    headers: { "Content-Type": "application/json" },
    body: JSON.stringify({ ignored }),
  });
}

export function setComment(
  forwardedTo: string,
  dateFileName: string,
  comment: string | null
): Promise<CommentResponse> {
  return fetchJSON(txnPath(forwardedTo, dateFileName) + "/comment", {
    method: "PUT",
    headers: { "Content-Type": "application/json" },
    body: JSON.stringify({ comment }),
  });
}

export function softDeleteTransaction(
  forwardedTo: string,
  dateFileName: string,
  deleted: boolean
): Promise<DeleteResponse> {
  return fetchJSON(txnPath(forwardedTo, dateFileName) + "/delete", {
    method: "POST",
    headers: { "Content-Type": "application/json" },
    body: JSON.stringify({ deleted }),
  });
}

export function fetchTrash(month: string): Promise<TransactionListResponse> {
  return fetchJSON(`${BASE}/transactions/trash?month=${encodeURIComponent(month)}`);
}

export function permanentlyDeleteTransaction(
  forwardedTo: string,
  dateFileName: string
): Promise<PermanentDeleteResponse> {
  return fetchJSON(txnPath(forwardedTo, dateFileName), { method: "DELETE" });
}

export function updateTransactionFields(
  forwardedTo: string,
  dateFileName: string,
  fields: { company?: string; amount?: number; transaction_type?: string }
): Promise<TransactionFieldsUpdateResponse> {
  return fetchJSON(txnPath(forwardedTo, dateFileName) + "/fields", {
    method: "PUT",
    headers: { "Content-Type": "application/json" },
    body: JSON.stringify(fields),
  });
}

export function fetchTransactionDetail(
  forwardedTo: string,
  dateFileName: string
): Promise<TransactionDetail> {
  return fetchJSON(txnPath(forwardedTo, dateFileName) + "/detail");
}

export function fetchJournal(month: string): Promise<JournalResponse> {
  return fetchJSON(`${BASE}/journal?month=${encodeURIComponent(month)}`);
}

export function fetchJournalSummaries(month: string): Promise<JournalSummariesResponse> {
  return fetchJSON(`${BASE}/journal/summaries?month=${encodeURIComponent(month)}`);
}

export function fetchJournalSummaryStatus(): Promise<JournalSummaryStatus> {
  return fetchJSON(`${BASE}/journal/summaries/status`);
}

export function generateJournalSummaries(
  month: string,
  dates: string[],
  force: boolean = false
): Promise<{ status: string; month: string; dates_queued: number }> {
  // A 409 ("already running") surfaces as ApiError with `.status === 409`, which
  // the caller (JournalPage) branches on for its own toast copy.
  return fetchJSON(`${BASE}/journal/summaries/generate`, {
    method: "POST",
    headers: { "Content-Type": "application/json" },
    body: JSON.stringify({ month, dates, force }),
  });
}

export function testOpenAiConnection(apiKey: string): Promise<{ ok: boolean; error?: string }> {
  return fetchJSON(`${BASE}/config/test-openai`, {
    method: "POST",
    headers: { "Content-Type": "application/json" },
    body: JSON.stringify({ api_key: apiKey }),
  });
}

export interface ChatgptLoginStatus {
  connected: boolean;
  pending: boolean;
  email: string | null;
  error: string | null;
  verification_url: string | null;
  user_code: string | null;
}

export function startChatgptLogin(): Promise<{ verification_url: string; user_code: string }> {
  return fetchJSON(`${BASE}/auth/chatgpt/start`, { method: "POST" });
}

export function fetchChatgptLoginStatus(): Promise<ChatgptLoginStatus> {
  return fetchJSON(`${BASE}/auth/chatgpt/status`);
}

export function disconnectChatgpt(): Promise<{ ok: boolean }> {
  return fetchJSON(`${BASE}/auth/chatgpt/disconnect`, { method: "POST" });
}

export function fetchSummary(month: string): Promise<SummaryComparisonResponse> {
  return fetchJSON(`${BASE}/summary?month=${encodeURIComponent(month)}`);
}

export function fetchTrend(months?: number, endMonth?: string): Promise<TrendResponse> {
  const params = new URLSearchParams();
  if (months) params.set("months", String(months));
  if (endMonth) params.set("end_month", endMonth);
  const qs = params.toString();
  return fetchJSON(`${BASE}/summary/trend${qs ? `?${qs}` : ""}`);
}

export function fetchBudgetConfig(year: number): Promise<BudgetConfigResponse | null> {
  // A 404 means "no budget configured for this year yet" — a valid empty state,
  // not an error — so `allow404` returns null instead of throwing.
  return fetchJSON(`${BASE}/budget/config?year=${year}`, undefined, { allow404: true });
}

export function updateBudgetConfig(
  year: number,
  data: BudgetConfigUpdateRequest
): Promise<BudgetConfigResponse> {
  // A 409 (multi-tab write conflict) surfaces as ApiError with `.status === 409`,
  // which BudgetEditPage branches on for its conflict UX.
  return fetchJSON(`${BASE}/budget/config?year=${year}`, {
    method: "PUT",
    headers: { "Content-Type": "application/json" },
    body: JSON.stringify(data),
  });
}

export function fetchBudgetStatus(
  year: number,
  compareYear?: number
): Promise<BudgetStatusResponse> {
  const params = new URLSearchParams({ year: String(year) });
  if (compareYear) params.set("compare_year", String(compareYear));
  return fetchJSON(`${BASE}/budget/status?${params}`);
}

export function fetchHistoricalAverages(months?: number): Promise<HistoricalAveragesResponse> {
  const params = months ? `?months=${months}` : "";
  return fetchJSON(`${BASE}/budget/historical-averages${params}`);
}

// ---------------------------------------------------------------------------
// Category Groups
// ---------------------------------------------------------------------------

export function fetchGroups(year: number): Promise<GroupsResponse> {
  return fetchJSON(`${BASE}/groups?year=${year}`);
}

export function updateGroups(year: number, data: GroupsUpdateRequest): Promise<GroupsResponse> {
  // A 409 (groups edited elsewhere) surfaces as ApiError with `.status === 409`,
  // which GroupEditorDialog branches on for its conflict toast.
  return fetchJSON(`${BASE}/groups?year=${year}`, {
    method: "PUT",
    headers: { "Content-Type": "application/json" },
    body: JSON.stringify(data),
  });
}

export async function fetchSavedInsightsList(month: string): Promise<SavedInsightSummary[]> {
  const res = await fetchJSON<SavedInsightList>(
    `${BASE}/insights/saved?month=${encodeURIComponent(month)}`
  );
  return res.items;
}

export function fetchInsightsContext(month: string): Promise<InsightsContext> {
  return fetchJSON(`${BASE}/insights/context?month=${encodeURIComponent(month)}`);
}

export function fetchMerchantIntelligence(
  month: string,
  months: number = 6
): Promise<MerchantIntelligenceResponse> {
  return fetchJSON(
    `${BASE}/merchants/intelligence?month=${encodeURIComponent(month)}&months=${months}`
  );
}

export function fetchCoverage(): Promise<CoverageResponse> {
  return fetchJSON(`${BASE}/coverage`);
}

export function fetchSavedInsight(id: string, month: string): Promise<SavedInsight> {
  return fetchJSON(
    `${BASE}/insights/saved/${encodeURIComponent(id)}?month=${encodeURIComponent(month)}`
  );
}

// ---------------------------------------------------------------------------
// Category Overrides
// ---------------------------------------------------------------------------

export function fetchOverrides(): Promise<OverrideListResponse> {
  return fetchJSON(`${BASE}/overrides`);
}

export function putOverride(company: string, category: string): Promise<OverrideListResponse> {
  return fetchJSON(`${BASE}/overrides/${encodeURIComponent(company)}`, {
    method: "PUT",
    headers: { "Content-Type": "application/json" },
    body: JSON.stringify({ category }),
  });
}

export function deleteOverride(company: string): Promise<void> {
  return fetchJSON(`${BASE}/overrides/${encodeURIComponent(company)}`, { method: "DELETE" });
}

export function fetchOverrideSuggestions(months?: number): Promise<OverrideSuggestionsResponse> {
  const params = months ? `?months=${months}` : "";
  return fetchJSON(`${BASE}/overrides/suggestions${params}`);
}

export function dismissSuggestion(company: string, category: string): Promise<void> {
  return fetchJSON(`${BASE}/overrides/suggestions/dismissed`, {
    method: "POST",
    headers: { "Content-Type": "application/json" },
    body: JSON.stringify({ company, category }),
  });
}

export function fetchOverrideMatch(
  company: string,
  options?: { includeHistory?: boolean; minScore?: number }
): Promise<OverrideMatchResponse> {
  const params = new URLSearchParams({ company });
  if (options?.includeHistory) params.set("include_history", "true");
  if (options?.minScore !== undefined) params.set("min_score", String(options.minScore));
  return fetchJSON(`${BASE}/overrides/match?${params.toString()}`);
}

export function fetchOverrideDuplicates(): Promise<OverrideDuplicatesResponse> {
  return fetchJSON(`${BASE}/overrides/duplicates`);
}

export function consolidateOverrides(body: OverrideConsolidateRequest): Promise<void> {
  return fetchJSON(`${BASE}/overrides/consolidate`, {
    method: "POST",
    headers: { "Content-Type": "application/json" },
    body: JSON.stringify(body),
  });
}

// ---------------------------------------------------------------------------
// Merchant Auto-Ignore Rules
// ---------------------------------------------------------------------------

export function fetchIgnoreRules(): Promise<IgnoreRuleListResponse> {
  return fetchJSON(`${BASE}/ignore-rules`);
}

export function addIgnoreRule(pattern: string): Promise<IgnoreRuleListResponse> {
  return fetchJSON(`${BASE}/ignore-rules`, {
    method: "POST",
    headers: { "Content-Type": "application/json" },
    body: JSON.stringify({ pattern }),
  });
}

export function deleteIgnoreRule(pattern: string): Promise<void> {
  return fetchJSON(`${BASE}/ignore-rules/${encodeURIComponent(pattern)}`, { method: "DELETE" });
}

export function fetchIgnoreRuleSuggestions(
  months?: number
): Promise<IgnoreRuleSuggestionsResponse> {
  const params = months ? `?months=${months}` : "";
  return fetchJSON(`${BASE}/ignore-rules/suggestions${params}`);
}

export function applyIgnoreRules(pattern?: string): Promise<IgnoreRuleApplyResponse> {
  return fetchJSON(`${BASE}/ignore-rules/apply`, {
    method: "POST",
    headers: { "Content-Type": "application/json" },
    body: JSON.stringify({ pattern: pattern ?? null }),
  });
}

export function dismissIgnoreRuleSuggestion(merchant: string): Promise<void> {
  return fetchJSON(`${BASE}/ignore-rules/suggestions/dismissed`, {
    method: "POST",
    headers: { "Content-Type": "application/json" },
    body: JSON.stringify({ merchant }),
  });
}

export function undismissIgnoreRuleSuggestion(merchant: string): Promise<void> {
  return fetchJSON(`${BASE}/ignore-rules/suggestions/dismissed/${encodeURIComponent(merchant)}`, {
    method: "DELETE",
  });
}

export function fetchDismissedIgnoreRuleSuggestions(): Promise<DismissedIgnoreRuleSuggestionsResponse> {
  return fetchJSON(`${BASE}/ignore-rules/suggestions/dismissed`);
}

// ---------------------------------------------------------------------------
// Category Management
// ---------------------------------------------------------------------------

export function fetchManagedCategories(): Promise<CategoriesManagementResponse> {
  return fetchJSON(`${BASE}/categories/managed`);
}

export function addCategory(
  name: string,
  group: string | null
): Promise<CategoriesManagementResponse> {
  return fetchJSON(`${BASE}/categories`, {
    method: "POST",
    headers: { "Content-Type": "application/json" },
    body: JSON.stringify({ name, group }),
  });
}

export function renameCategory(oldName: string, newName: string): Promise<CategoryRenameResponse> {
  return fetchJSON(`${BASE}/categories/${encodeURIComponent(oldName)}`, {
    method: "PUT",
    headers: { "Content-Type": "application/json" },
    body: JSON.stringify({ new_name: newName }),
  });
}

export function deleteCategory(name: string, reassignTo?: string): Promise<CategoryDeleteResponse> {
  const params = reassignTo ? `?reassign_to=${encodeURIComponent(reassignTo)}` : "";
  // Callers branch on `.status` (e.g. 409 when the category is still in use);
  // ApiError carries both that and the envelope's `error` message.
  return fetchJSON(`${BASE}/categories/${encodeURIComponent(name)}${params}`, { method: "DELETE" });
}

export function fetchCategoryUsage(name: string): Promise<CategoryUsageResponse> {
  return fetchJSON(`${BASE}/categories/${encodeURIComponent(name)}/usage`);
}

export function updateCategoryGroup(
  name: string,
  group: string | null
): Promise<CategoryGroupUpdateResponse> {
  return fetchJSON(`${BASE}/categories/${encodeURIComponent(name)}/group`, {
    method: "PUT",
    headers: { "Content-Type": "application/json" },
    body: JSON.stringify({ group }),
  });
}

// ---------------------------------------------------------------------------
// Category Icon Overrides
// ---------------------------------------------------------------------------

export function fetchCategoryIcons(): Promise<CategoryIconsResponse> {
  return fetchJSON(`${BASE}/categories/icons`);
}

export function setCategoryIcon(name: string, icon: string): Promise<CategoryIconsResponse> {
  return fetchJSON(`${BASE}/categories/icons?name=${encodeURIComponent(name)}`, {
    method: "PUT",
    headers: { "Content-Type": "application/json" },
    body: JSON.stringify({ icon }),
  });
}

export function clearCategoryIcon(name: string): Promise<CategoryIconsResponse> {
  return fetchJSON(`${BASE}/categories/icons?name=${encodeURIComponent(name)}`, {
    method: "DELETE",
  });
}

// ---------------------------------------------------------------------------
// Statement Import
// ---------------------------------------------------------------------------

export async function uploadStatement(file: File): Promise<StatementUploadResponse> {
  const formData = new FormData();
  formData.append("file", file);
  return postFormData(`${BASE}/statements/upload`, formData);
}

export function importStatementTransactions(data: ImportRequest): Promise<ImportResponse> {
  return fetchJSON(`${BASE}/statements/import`, {
    method: "POST",
    headers: { "Content-Type": "application/json" },
    body: JSON.stringify(data),
  });
}

export function fetchStatements(): Promise<StatementListResponse> {
  return fetchJSON(`${BASE}/statements`);
}

export function fetchStatement(id: string): Promise<StatementDetailResponse> {
  return fetchJSON(`${BASE}/statements/${encodeURIComponent(id)}`);
}

export function deleteStatement(id: string): Promise<void> {
  return fetchJSON(`${BASE}/statements/${encodeURIComponent(id)}`, { method: "DELETE" });
}

export function updateTransactionAction(
  statementId: string,
  rowId: string,
  data: TransactionActionUpdate
): Promise<{ ok: boolean; tx_index: number; row_id: string; action: string }> {
  return fetchJSON(
    `${BASE}/statements/${encodeURIComponent(statementId)}/transactions/${encodeURIComponent(rowId)}`,
    {
      method: "PATCH",
      headers: { "Content-Type": "application/json" },
      body: JSON.stringify(data),
    }
  );
}

export function getStatementDownloadUrl(id: string): string {
  return `${BASE}/statements/${encodeURIComponent(id)}/download`;
}

export function reparseStatement(id: string): Promise<StatementDetailResponse> {
  return fetchJSON(`${BASE}/statements/${encodeURIComponent(id)}/reparse`, { method: "POST" });
}

// ---------------------------------------------------------------------------
// Attachments (receipts & documents)
// ---------------------------------------------------------------------------

// Multipart upload mirrors uploadStatement: FormData with the raw file, plus
// optional form fields. When `txId` is present the server links the row to that
// transaction immediately. `credentials` is included so the auth cookie travels
// (the endpoint is protected the same as every other write).
export async function uploadAttachment(
  file: File,
  txId?: string,
  kind?: string
): Promise<AttachmentResponse> {
  const formData = new FormData();
  formData.append("file", file);
  if (txId) formData.append("tx_id", txId);
  if (kind) formData.append("kind", kind);
  return postFormData(`${BASE}/attachments`, formData);
}

export function fetchTransactionAttachments(txId: string): Promise<AttachmentListResponse> {
  return fetchJSON(`${BASE}/transactions/${encodeURIComponent(txId)}/attachments`);
}

export function fetchUnlinkedAttachments(): Promise<AttachmentListResponse> {
  return fetchJSON(`${BASE}/attachments?unlinked=true`);
}

// `txId: null` unlinks (moves the attachment back to "Receipts to file").
export function linkAttachment(id: string, txId: string | null): Promise<AttachmentResponse> {
  return fetchJSON(`${BASE}/attachments/${encodeURIComponent(id)}/link`, {
    method: "POST",
    headers: { "Content-Type": "application/json" },
    body: JSON.stringify({ tx_id: txId }),
  });
}

export function deleteAttachment(id: string): Promise<AttachmentDeleteResponse> {
  return fetchJSON(`${BASE}/attachments/${encodeURIComponent(id)}`, { method: "DELETE" });
}

// The file is served inline (image preview or PDF open-in-tab); callers point an
// <img> src or an anchor href at this URL rather than fetching bytes in JS.
export function getAttachmentFileUrl(id: string): string {
  return `${BASE}/attachments/${encodeURIComponent(id)}/file`;
}

// Parse a receipt through the configured AI provider (consent-gated server-side;
// 422 when `ai_receipt_parsing_enabled` is off). Returns the enriched row with
// `parse_status`/`parse_json`.
export function parseReceipt(id: string): Promise<AttachmentResponse> {
  return fetchJSON(`${BASE}/attachments/${encodeURIComponent(id)}/parse`, { method: "POST" });
}

// Ranked transactions a parsed receipt might explain. 409 when the attachment
// hasn't been parsed yet. Read-only: when exactly one tier-1 candidate exists
// and the attachment was unlinked, the server sets `auto_link_candidate: true`
// to signal the client should link the first candidate (via the link mutation);
// the GET itself performs no write.
export function fetchReceiptCandidates(id: string): Promise<ReceiptCandidatesResponse> {
  return fetchJSON(`${BASE}/attachments/${encodeURIComponent(id)}/candidates`);
}

// ---------------------------------------------------------------------------
// Parse failures ("Needs review")
// ---------------------------------------------------------------------------

export function listParseFailures(status?: ParseFailureStatus): Promise<ParseFailureListResponse> {
  const qs = status ? `?status=${encodeURIComponent(status)}` : "";
  return fetchJSON(`${BASE}/parse-failures${qs}`);
}

// Detail carries the raw email body (PII) — only call this when a row is
// expanded on demand, never for the list.
export function getParseFailure(id: string): Promise<ParseFailureDetail> {
  return fetchJSON(`${BASE}/parse-failures/${encodeURIComponent(id)}`);
}

export function retryParseFailure(id: string): Promise<RetryResponse> {
  return fetchJSON(`${BASE}/parse-failures/${encodeURIComponent(id)}/retry`, { method: "POST" });
}

// Bulk retry a whole institution's (or sender domain's) quarantined backlog
// through the deterministic parsers (never AI). At least one filter field is
// required; the server caps the sweep at 1,000 rows.
export function retryAllParseFailures(filter: RetryAllRequest): Promise<RetryAllResponse> {
  return fetchJSON(`${BASE}/parse-failures/retry-all`, {
    method: "POST",
    headers: { "Content-Type": "application/json" },
    body: JSON.stringify(filter),
  });
}

// Records a hand-entered transaction for a quarantined email and marks the row
// resolved. Unlike retry (which only re-runs the deterministic parsers), this
// carries the values the user typed by hand for the long tail no parser reads.
export function resolveParseFailure(
  id: string,
  body: ManualResolveRequest
): Promise<ManualResolveResponse> {
  return fetchJSON(`${BASE}/parse-failures/${encodeURIComponent(id)}/resolve`, {
    method: "POST",
    headers: { "Content-Type": "application/json" },
    body: JSON.stringify(body),
  });
}

export function dismissParseFailure(id: string): Promise<DismissResponse> {
  return fetchJSON(`${BASE}/parse-failures/${encodeURIComponent(id)}`, { method: "DELETE" });
}

// ---------------------------------------------------------------------------
// Insights Generation
// ---------------------------------------------------------------------------

export function generateInsights(month: string): Promise<{ status: string; month: string }> {
  // A 409 ("already running") surfaces as ApiError with `.status === 409`, which
  // InsightsPage branches on for its own "already in progress" copy.
  return fetchJSON(`${BASE}/insights/generate?month=${encodeURIComponent(month)}`, {
    method: "POST",
  });
}

export function fetchInsightsStatus(): Promise<InsightsStatus> {
  return fetchJSON(`${BASE}/insights/status`);
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
  return fetchJSON(`${BASE}/merchant-aliases`);
}

export function putMerchantAlias(rawName: string, canonicalName: string): Promise<{ ok: boolean }> {
  return fetchJSON(`${BASE}/merchant-aliases/${encodeURIComponent(rawName)}`, {
    method: "PUT",
    headers: { "Content-Type": "application/json" },
    body: JSON.stringify({ canonical_name: canonicalName }),
  });
}

export function deleteMerchantAlias(rawName: string): Promise<void> {
  return fetchJSON(`${BASE}/merchant-aliases/${encodeURIComponent(rawName)}`, { method: "DELETE" });
}

// ---------------------------------------------------------------------------
// Income Statement
// ---------------------------------------------------------------------------

export function fetchIncomeStatement(year: number): Promise<IncomeStatementResponse> {
  return fetchJSON(`${BASE}/income-statement?year=${year}`);
}

// ---------------------------------------------------------------------------
// Tax pack (CRA claim lines)
// ---------------------------------------------------------------------------

export function fetchTaxPack(year: number): Promise<TaxPackResponse> {
  return fetchJSON(`${BASE}/tax-pack?year=${year}`);
}

// Streams an in-memory zip (summary + per-line CSVs + evidence files). Uses the
// downloadBackup blob pattern; demo mode rejects the export server-side.
export function downloadTaxPack(year: number): Promise<void> {
  return downloadFile(`${BASE}/tax-pack/export?year=${year}`, `tax-pack-${year}.zip`);
}

// ---------------------------------------------------------------------------
// Tax-item overrides (per-transaction include/exclude on a CRA claim line)
// ---------------------------------------------------------------------------

// A selectable CRA claim line. Hand-written (not codegen) — the endpoint
// returns the seven seed lines plus a synthetic "other" catch-all.
export type TaxLineOption = { key: string; label: string };

export function fetchTaxLines(): Promise<{ lines: TaxLineOption[] }> {
  return fetchJSON(`${BASE}/tax-pack/lines`);
}

// Force a transaction onto (or off) a claim line. `mode: "include"` requires
// `lineKey`; `mode: "exclude"` suppresses it. Returns 204 (no body), which
// fetchJSON now tolerates.
export function setTaxOverride(
  txId: string,
  mode: "include" | "exclude",
  lineKey?: string
): Promise<void> {
  return fetchJSON(`${BASE}/tax-pack/items`, {
    method: "POST",
    headers: { "Content-Type": "application/json" },
    body: JSON.stringify({ tx_id: txId, mode, line_key: lineKey }),
  });
}

// Remove a prior override, reverting the row to its auto-classified state.
// Returns 204 (no body).
export function clearTaxOverride(txId: string): Promise<void> {
  return fetchJSON(`${BASE}/tax-pack/items/${encodeURIComponent(txId)}`, { method: "DELETE" });
}

// ---------------------------------------------------------------------------
// Transaction Search
// ---------------------------------------------------------------------------

function buildSearchParams(params: SearchParams): URLSearchParams {
  const qs = new URLSearchParams();
  qs.set("from", params.from);
  qs.set("to", params.to);
  if (params.q) qs.set("q", params.q);
  if (params.category) qs.set("category", params.category);
  if (params.institution) qs.set("institution", params.institution);
  if (params.company) qs.set("company", params.company);
  if (params.type) qs.set("type", params.type);
  if (params.min_amount != null) qs.set("min_amount", String(params.min_amount));
  if (params.max_amount != null) qs.set("max_amount", String(params.max_amount));
  if (params.include_ignored) qs.set("include_ignored", "true");
  if (params.include_deleted) qs.set("include_deleted", "true");
  return qs;
}

export function searchTransactions(params: SearchParams): Promise<SearchResponse> {
  return fetchJSON(`${BASE}/transactions/search?${buildSearchParams(params)}`);
}

export function downloadExport(params: SearchParams): Promise<void> {
  return downloadFile(
    `${BASE}/transactions/export?${buildSearchParams(params)}`,
    `transactions_${params.from}_to_${params.to}.csv`
  );
}

// ---------------------------------------------------------------------------
// Data backup — full import/export (Settings tab)
// ---------------------------------------------------------------------------

export function downloadBackup(): Promise<void> {
  const today = new Date().toISOString().slice(0, 10);
  return downloadFile(`${BASE}/data/export`, `finance-backup-${today}.zip`, { method: "POST" });
}

export function previewImport(file: File): Promise<ImportPreviewResponse> {
  const formData = new FormData();
  formData.append("file", file);
  return postFormData(`${BASE}/data/import/preview`, formData);
}

export function commitImport(
  token: string,
  strategy: ImportStrategy,
  applyConfig = true
): Promise<ImportResult> {
  return fetchJSON(`${BASE}/data/import/commit`, {
    method: "POST",
    headers: { "Content-Type": "application/json" },
    body: JSON.stringify({ token, strategy, apply_config: applyConfig }),
  });
}

// ---------------------------------------------------------------------------
// Activity ledger (agent activity feed)
// ---------------------------------------------------------------------------

export interface ActivityFilters {
  limit?: number;
  since?: string;
  principal?: string;
  operation?: string;
}

// The ledger of recorded writes, newest first. No pagination (L12) — `limit`
// (default 100, max 500 server-side) and `since` bound the window instead.
export function fetchActivity(params: ActivityFilters = {}): Promise<ActivityListResponse> {
  const qs = new URLSearchParams();
  if (params.limit != null) qs.set("limit", String(params.limit));
  if (params.since) qs.set("since", params.since);
  if (params.principal) qs.set("principal", params.principal);
  if (params.operation) qs.set("operation", params.operation);
  const q = qs.toString();
  return fetchJSON(`${BASE}/activity${q ? `?${q}` : ""}`);
}

// Undo a single recorded write. A 409 (`stale_revert` when the resource moved
// on, or already-reverted / not-reversible) surfaces as ApiError with
// `.status === 409`; `force` overrides the stale-revert guard.
export function revertActivity(id: string, force = false): Promise<RevertResponse> {
  const qs = force ? "?force=true" : "";
  return fetchJSON(`${BASE}/activity/${encodeURIComponent(id)}/revert${qs}`, { method: "POST" });
}

// The resolved identity of the current caller (token label / scope for bearer
// callers; nulls for cookie sessions and the dev bypass).
export function fetchWhoami(): Promise<WhoamiResponse> {
  return fetchJSON(`${BASE}/whoami`);
}
