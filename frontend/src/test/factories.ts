import { txIdFromComposite } from "@/lib/api";
import type {
  BudgetCategoryConfig,
  BudgetConfigResponse,
  BudgetGroupConfig,
  BudgetStatusResponse,
  CategoryIconsResponse,
  GroupsResponse,
  MonthSummary,
  OverrideEntry,
  OverrideListResponse,
  StatementUploadResponse,
  SummaryComparisonResponse,
  Transaction,
} from "@/types/api";

export function makeTxn(overrides: Partial<Transaction> = {}): Transaction {
  const fwd = overrides.forwarded_to ?? "test@example.com";
  const dfn = overrides.date_file_name ?? "2026.02.01_12.00_test.eml";
  return {
    tx_id: txIdFromComposite(fwd, dfn),
    forwarded_to: fwd,
    date_file_name: dfn,
    date: "02/01/2026 12:00 PST",
    amount: 10,
    company: "TestCo",
    category: "groceries",
    institution: "RBC",
    transaction_type: "purchase",
    name: "Test",
    category_audit: null,
    ignored: false,
    comment: null,
    deleted_at: null,
    ...overrides,
  };
}

export function makeMonthSummary(overrides: Partial<MonthSummary> = {}): MonthSummary {
  return {
    by_category: {},
    by_company: {},
    deposit_count: 0,
    deposit_total: 0,
    deposits_by_company: {},
    spending_count: 0,
    top_categories: [],
    total_spending: 0,
    year_month: "2026-04",
    ...overrides,
  };
}

export function makeSummary(
  overrides: Partial<SummaryComparisonResponse> = {}
): SummaryComparisonResponse {
  return {
    current: makeMonthSummary(),
    previous: makeMonthSummary({ year_month: "2026-03" }),
    delta_amount: 0,
    delta_percent: 0,
    ...overrides,
  };
}

export function makeBudgetCategoryConfig(
  overrides: Partial<BudgetCategoryConfig> = {}
): BudgetCategoryConfig {
  return {
    category_type: "variable",
    input_mode: "monthly",
    monthly_amount: 200,
    target: 200,
    ...overrides,
  };
}

export function makeBudgetGroupConfig(
  overrides: Partial<BudgetGroupConfig> = {}
): BudgetGroupConfig {
  return {
    name: "Essentials",
    categories: ["groceries", "rent"],
    ...overrides,
  };
}

export function makeBudgetConfig(
  overrides: Partial<BudgetConfigResponse> = {}
): BudgetConfigResponse {
  return {
    year: 2026,
    spending_ceiling: 5000,
    allocated_total: 2600,
    unallocated: 2400,
    targets_version: 1,
    groups_version: 1,
    categories: {
      groceries: makeBudgetCategoryConfig({ monthly_amount: 600, target: 600 }),
      rent: makeBudgetCategoryConfig({
        category_type: "fixed",
        monthly_amount: 2000,
        target: 2000,
      }),
    },
    groups: [makeBudgetGroupConfig()],
    ...overrides,
  };
}

export function makeBudgetStatus(
  overrides: Partial<BudgetStatusResponse> = {}
): BudgetStatusResponse {
  return {
    year: 2026,
    as_of: "2026-04-28",
    elapsed_year_fraction: 0.32,
    monthly_totals: [400, 380, 410, 0, 0, 0, 0, 0, 0, 0, 0, 0],
    compare_year: null,
    prior_year_total: null,
    overall: {
      expected_pace: 1600,
      headline: "On track",
      spending_ceiling: 5000,
      status: "on_track",
      variance: 0,
      ytd_spent: 1190,
    },
    groups: [],
    unbudgeted: [],
    ...overrides,
  };
}

export function makeCategoryGroups(overrides: Partial<GroupsResponse> = {}): GroupsResponse {
  return {
    year: 2026,
    version: 1,
    groups: [makeBudgetGroupConfig()],
    ...overrides,
  };
}

export function makeCategoryIcons(
  overrides: Partial<CategoryIconsResponse> = {}
): CategoryIconsResponse {
  return {
    version: 1,
    icons: { groceries: "ShoppingCart", rent: "Home" },
    ...overrides,
  };
}

export function makeOverride(overrides: Partial<OverrideEntry> = {}): OverrideEntry {
  return {
    company: "TEST COMPANY",
    category: "groceries",
    ...overrides,
  };
}

export function makeOverrideList(
  overrides: Partial<OverrideListResponse> = {}
): OverrideListResponse {
  const list = overrides.overrides ?? [makeOverride()];
  return {
    count: list.length,
    overrides: list,
    version: 1,
    ...overrides,
  };
}

export function makeStatementUploadResponse(
  overrides: Partial<StatementUploadResponse> = {}
): StatementUploadResponse {
  return {
    statement_id: "stmt_test_001",
    metadata: {
      institution: "RBC",
      account_type: "chequing",
      period_start: "2026-03-01",
      period_end: "2026-03-31",
      transaction_count: 0,
      parsed_with_ai: false,
    },
    summary: {
      ambiguous_count: 0,
      duplicate_count: 0,
      enriched_count: 0,
      imported_count: 0,
      matched_count: 0,
      new_count: 0,
      previously_imported_count: 0,
      skipped_count: 0,
      suspected_duplicate_count: 0,
      total_parsed: 0,
      updated_count: 0,
    },
    ambiguous: [],
    matched: [],
    new: [],
    previously_imported: [],
    suspected_duplicates: [],
    transactions: [],
    ...overrides,
  };
}
