/**
 * Flat re-export barrel over `api.generated.ts`. Generated types live as
 * deeply-nested `components["schemas"]["X"]` paths; this file aliases each one
 * the rest of the codebase uses to a short, importable name.
 *
 * Update this file when adding new endpoints or response models. The barrel
 * itself is hand-maintained — `api.generated.ts` is the codegen output.
 */
import type { components, paths } from "./api.generated";

type Schemas = components["schemas"];

// ---------------------------------------------------------------------------
// Budget
// ---------------------------------------------------------------------------
export type BudgetCategoryConfig = Schemas["BudgetCategoryConfig"];
export type BudgetCategoryConfigInput = Schemas["BudgetCategoryConfigInput"];
export type BudgetGroupConfig = Schemas["BudgetGroupConfig"];
export type BudgetConfigResponse = Schemas["BudgetConfigResponse"];
export type BudgetConfigUpdateRequest = Schemas["BudgetConfigUpdateRequest"];
export type BudgetStatusResponse = Schemas["BudgetStatusResponse"];
export type CategoryPaceDetail = Schemas["CategoryPaceDetail"];
export type GroupPace = Schemas["GroupPace"];
export type GroupsResponse = Schemas["GroupsResponse"];
export type GroupsUpdateRequest = Schemas["GroupsUpdateRequest"];
export type HistoricalAveragesResponse = Schemas["HistoricalAveragesResponse"];
export type HistoricalCategoryAverage = Schemas["HistoricalCategoryAverage"];
export type PaceStatus = Schemas["PaceStatus"];
export type UnbudgetedCategory = Schemas["UnbudgetedCategory"];

// ---------------------------------------------------------------------------
// Categories (management)
// ---------------------------------------------------------------------------
export type CategoriesManagementResponse = Schemas["CategoriesManagementResponse"];
export type CategoryDeleteResponse = Schemas["CategoryDeleteResponse"];
export type CategoryGroupUpdateResponse = Schemas["CategoryGroupUpdateResponse"];
export type CategoryIconsResponse = Schemas["CategoryIconsResponse"];
export type CategoryRenameResponse = Schemas["CategoryRenameResponse"];
export type CategoryUsageResponse = Schemas["CategoryUsageResponse"];
export type CategoryWithGroup = Schemas["CategoryWithGroup"];
export type SetCategoryIconRequest = Schemas["SetCategoryIconRequest"];

// ---------------------------------------------------------------------------
// App config
// ---------------------------------------------------------------------------
export type AppConfig = Schemas["AppConfigResponse"];
export type AppConfigUpdate = Schemas["AppConfigUpdateRequest"];
export type TestS3BackupResponse = Schemas["TestS3BackupResponse"];
export type S3BackupStatus = Schemas["S3BackupStatusResponse"];
/**
 * AI provider literal union — the full set a task can route to (daily
 * summaries, monthly insights, document parsing). Mirrors the backend enum on
 * `daily_summary_provider` / `insights_provider` / `document_parsing_provider`.
 */
export type AiProvider = "claude_cli" | "openai" | "codex" | "gemini_cli" | "disabled";
/**
 * Categorization (and email rescue) routes only to the OpenAI-family providers,
 * so its provider column is a narrower union than {@link AiProvider}. Mirrors
 * the backend enum on `categorization_provider`.
 */
export type CategorizationProvider = "openai" | "codex" | "disabled";
/**
 * Reasoning-effort union shared by every `*_reasoning_effort` key. The Pydantic
 * field widens to `string | null` in the generated schema; this keeps the
 * curated effort lists narrow at the call site.
 */
export type ReasoningEffort = "none" | "minimal" | "low" | "medium" | "high" | "xhigh" | "max";

// ---------------------------------------------------------------------------
// Health probe
// ---------------------------------------------------------------------------
export type HealthStatus = Schemas["HealthResponse"];
export type HealthStatusValue = Schemas["HealthResponse"]["status"];

// ---------------------------------------------------------------------------
// Coverage (ingestion health)
// ---------------------------------------------------------------------------
export type CoverageResponse = Schemas["CoverageResponse"];
export type CoverageInstitution = Schemas["CoverageInstitution"];
/** Per-institution cadence status vocabulary emitted by the coverage service. */
export type CoverageStatus = Schemas["CoverageInstitution"]["status"];
export type CaptureSummary = Schemas["CaptureSummary"];
export type CaptureBucket = Schemas["CaptureBucket"];
export type CaptureBucketInstitution = Schemas["CaptureBucketInstitution"];
export type CaptureBucketType = Schemas["CaptureBucketType"];

// ---------------------------------------------------------------------------
// Income statement
// ---------------------------------------------------------------------------
export type ExpenseCategoryRow = Schemas["ExpenseCategoryRow"];
export type ExpenseSectionResponse = Schemas["ExpenseSectionResponse"];
export type IncomeCompanyRow = Schemas["IncomeCompanyRow"];
export type IncomeSectionResponse = Schemas["IncomeSectionResponse"];
export type IncomeStatementResponse = Schemas["IncomeStatementResponse"];
export type ProjectionResponse = Schemas["ProjectionResponse"];

// ---------------------------------------------------------------------------
// Merchants
// ---------------------------------------------------------------------------
export type MerchantIntelligenceResponse = Schemas["MerchantIntelligenceResponse"];
export type MerchantRecord = Schemas["MerchantRecord"];
export type MerchantPriceChange = Schemas["MerchantPriceChange"];
export type MerchantPriceChangeRow = Schemas["MerchantPriceChangeRow"];
export type MerchantIntelligenceSummary = Schemas["MerchantIntelligenceSummary"];

// ---------------------------------------------------------------------------
// Insights
// ---------------------------------------------------------------------------
export type InsightsStatus = Schemas["InsightsStatusResponse"];
export type InsightsContext = Schemas["InsightsContextResponse"];
export type CategoryDelta = Schemas["CategoryDelta"];
export type CategoryAnomaly = Schemas["CategoryAnomaly"];
export type SavedInsightSummary = Schemas["SavedInsightItem"];
export type SavedInsightList = Schemas["SavedInsightListResponse"];
export type SavedInsight = Schemas["SavedInsightDetail"];

// ---------------------------------------------------------------------------
// Journal / day summaries
// ---------------------------------------------------------------------------
export type JournalDay = Schemas["JournalDay"];
export type JournalResponse = Schemas["JournalResponse"];
export type JournalSummariesResponse = Schemas["DaySummariesResponse"];
export type JournalSummaryStatus = Schemas["DaySummaryStatusResponse"];

// ---------------------------------------------------------------------------
// Overrides
// ---------------------------------------------------------------------------
export type OverrideEntry = Schemas["OverrideEntry"];
export type OverrideListResponse = Schemas["OverrideListResponse"];
export type OverrideSuggestion = Schemas["OverrideSuggestion"];
export type OverrideSuggestionsResponse = Schemas["OverrideSuggestionsResponse"];
export type OverrideMatchCandidate = Schemas["OverrideMatchCandidate"];
export type OverrideMatchResponse = Schemas["OverrideMatchResponse"];
export type OverrideMatchTier = Schemas["OverrideMatchCandidate"]["tier"];
export type OverrideDuplicateMember = Schemas["OverrideDuplicateMember"];
export type OverrideDuplicateGroup = Schemas["OverrideDuplicateGroup"];
export type OverrideDuplicatesResponse = Schemas["OverrideDuplicatesResponse"];
export type OverrideConsolidateRequest = Schemas["OverrideConsolidateRequest"];

// ---------------------------------------------------------------------------
// Auto-ignore rules
// ---------------------------------------------------------------------------
export type IgnoreRuleEntry = Schemas["IgnoreRuleEntry"];
export type IgnoreRuleListResponse = Schemas["IgnoreRuleListResponse"];
export type IgnoreRuleSuggestion = Schemas["IgnoreRuleSuggestion"];
export type IgnoreRuleSuggestionsResponse = Schemas["IgnoreRuleSuggestionsResponse"];
export type IgnoreRuleApplyResult = Schemas["IgnoreRuleApplyResult"];
export type IgnoreRuleApplyResponse = Schemas["IgnoreRuleApplyResponse"];
export type DismissedIgnoreRuleSuggestion = Schemas["DismissedIgnoreRuleSuggestion"];
export type DismissedIgnoreRuleSuggestionsResponse =
  Schemas["DismissedIgnoreRuleSuggestionsResponse"];

// ---------------------------------------------------------------------------
// Statements
// ---------------------------------------------------------------------------
export type StatementTransaction = Schemas["StatementTransaction"];
export type StatementMetadata = Schemas["StatementMetadata"];
export type MatchedItem = Schemas["MatchedItem"];
export type AmbiguousItem = Schemas["AmbiguousItem"];
export type NewItem = Schemas["NewItem"];
export type SuspectedDuplicateItem = Schemas["SuspectedDuplicateItem"];
export type PreviouslyImportedItem = Schemas["PreviouslyImportedItem"];
export type StatementUploadResponse = Schemas["StatementUploadResponse"];
export type ImportAction = Schemas["ImportAction"];
export type ImportRequest = Schemas["ImportRequest"];
export type ImportResponse = Schemas["ImportResponse"];
export type StatementSummaryItem = Schemas["StatementSummaryItem"];
export type StatementListResponse = Schemas["StatementListResponse"];
export type StatementTransactionItem = Schemas["StatementTransactionItem"];
export type StatementDetailResponse = Schemas["StatementDetailResponse"];
export type TransactionActionUpdate = Schemas["TransactionActionUpdate"];

// ---------------------------------------------------------------------------
// Attachments (receipts & documents)
// ---------------------------------------------------------------------------
export type AttachmentResponse = Schemas["AttachmentResponse"];
export type AttachmentListResponse = Schemas["AttachmentListResponse"];
export type AttachmentDeleteResponse = Schemas["AttachmentDeleteResponse"];
export type LinkAttachmentRequest = Schemas["LinkAttachmentRequest"];
export type ReceiptCandidate = Schemas["ReceiptCandidate"];
export type ReceiptCandidatesResponse = Schemas["ReceiptCandidatesResponse"];

// ---------------------------------------------------------------------------
// Tax pack (CRA claim lines)
// ---------------------------------------------------------------------------
export type TaxPackResponse = Schemas["TaxPackResponse"];
export type TaxLineResponse = Schemas["TaxLineResponse"];
export type TaxPackTransaction = Schemas["TaxPackTransaction"];
export type TaxEvidenceCounts = Schemas["TaxEvidenceCounts"];

// ---------------------------------------------------------------------------
// Transactions / summary / search
// ---------------------------------------------------------------------------
export type TransactionContext = Schemas["TransactionContext"];
export type Transaction = Schemas["TransactionResponse"];
export type TransactionDetail = Schemas["TransactionDetailResponse"];
export type TransactionListResponse = Schemas["TransactionListResponse"];
export type AttentionListResponse = Schemas["AttentionListResponse"];
export type CombinedTransactionsResponse = Schemas["CombinedTransactionsResponse"];
export type LatestTimestampResponse = Schemas["LatestTimestampResponse"];
/**
 * Bulk endpoint returns a `Dict[str, CombinedTransactionsResponse]` — keyed
 * by month — which OpenAPI represents via `additionalProperties`. No named
 * component is generated, so the shape is reconstructed here.
 */
export type BulkTransactionsResponse = Record<string, CombinedTransactionsResponse>;
export type CategoryUpdateRequest = Schemas["CategoryUpdateRequest"];
export type CategoryUpdateResponse = Schemas["CategoryUpdateResponse"];
export type ReviewResponse = Schemas["ReviewResponse"];
export type IgnoreResponse = Schemas["IgnoreResponse"];
export type CommentResponse = Schemas["CommentResponse"];
export type DeleteResponse = Schemas["DeleteResponse"];
export type PermanentDeleteResponse = Schemas["PermanentDeleteResponse"];
export type TransactionFieldsUpdateResponse = Schemas["TransactionFieldsUpdateResponse"];
export type CategoriesResponse = Schemas["CategoriesResponse"];
export type CategorySummary = Schemas["CategorySummary"];
export type CompanySummary = Schemas["CompanySummary"];
export type DepositSourceSummary = Schemas["DepositSourceSummary"];
export type TopCategory = Schemas["TopCategory"];
export type MonthSummary = Schemas["MonthSummary"];
export type SummaryComparisonResponse = Schemas["SummaryComparisonResponse"];
export type TrendMonthEntry = Schemas["TrendMonthEntry"];
export type TrendResponse = Schemas["TrendResponse"];
export type SearchSummary = Schemas["SearchSummary"];
export type SearchResponse = Schemas["SearchResponse"];
/**
 * Query-parameter bag for `GET /api/v1/transactions/search`. Derived from
 * the operation's typed `parameters.query` so any backend change to the
 * query schema flows through automatically.
 */
export type SearchParams = paths["/api/v1/transactions/search"]["get"]["parameters"]["query"];

// ---------------------------------------------------------------------------
// Parse failures ("Needs review")
// ---------------------------------------------------------------------------
export type ParseFailureSummary = Schemas["ParseFailureSummary"];
export type ParseFailureDetail = Schemas["ParseFailureDetail"];
export type ParseFailureListResponse = Schemas["ParseFailureListResponse"];
export type RetryResponse = Schemas["RetryResponse"];
export type RetryAllRequest = Schemas["RetryAllRequest"];
export type RetryAllResponse = Schemas["RetryAllResponse"];
export type DismissResponse = Schemas["DismissResponse"];
export type ManualResolveRequest = Schemas["ManualResolveRequest"];
export type ManualResolveResponse = Schemas["ManualResolveResponse"];
/** Canonical transaction-type union — mirrors the backend's `TransactionType`. */
export type TransactionType = NonNullable<Schemas["ManualResolveRequest"]["transaction_type"]>;
/**
 * Store-side status vocabulary (`VALID_STATUSES` in
 * `src/finance/parse_failure_store_local.py`). The Pydantic field is typed as
 * `str`, so the generated schema widens to `string`; this local union keeps the
 * status filter narrowing the UI relies on.
 */
export type ParseFailureStatus = "quarantined" | "recovered" | "retried" | "dismissed";

// ---------------------------------------------------------------------------
// Activity ledger (agent activity feed)
// ---------------------------------------------------------------------------
export type ActivityEntry = Schemas["ActivityEntry"];
export type ActivityListResponse = Schemas["ActivityListResponse"];
export type RevertResponse = Schemas["RevertResponse"];
export type WhoamiResponse = Schemas["WhoamiResponse"];

// ---------------------------------------------------------------------------
// Data backup (import/export)
// ---------------------------------------------------------------------------
export type ImportPreviewCounts = Schemas["ImportPreviewCounts"];
export type ImportPreviewSample = Schemas["ImportPreviewSample"];
export type ImportPreviewResponse = Schemas["ImportPreviewResponse"];
export type ImportCommitRequest = Schemas["ImportCommitRequest"];
export type ImportResult = Schemas["ImportResult"];
export type ConfigPreview = Schemas["ConfigPreview"];
export type ImportStrategy = "skip" | "overwrite" | "keep_both";
