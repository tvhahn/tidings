import { fireEvent, render, screen } from "@testing-library/react";
import { act } from "react";
import { afterEach, beforeEach, describe, expect, it, vi } from "vitest";
import { StatementReview } from "@/components/StatementReview";
import type {
  AmbiguousItem,
  ImportAction,
  MatchedItem,
  NewItem,
  PreviouslyImportedItem,
  StatementUploadResponse,
  SuspectedDuplicateItem,
} from "@/types/api";

// --- Mocks ------------------------------------------------------------------
// Spy on the auto-save mutation so we can pin exactly what payload each save
// dispatches (and prove keys are row_id, not the positional index).
const { mutateSpy } = vi.hoisted(() => ({ mutateSpy: vi.fn() }));

vi.mock("@/hooks/useStatement", () => ({
  useUpdateTransactionAction: () => ({ mutate: mutateSpy }),
}));

// Stub CategoryPicker down to a plain button. The real picker is a Radix
// Popover + cmdk Command that does not open cleanly in jsdom; all we need for
// characterization is a control that fires `onSelect` with a category. Note
// the parent (StatementReview) lowercases the value it receives, so selecting
// "Dining" lands as "dining" — matching production behavior.
vi.mock("@/components/CategoryPicker", () => ({
  CategoryPicker: ({
    value,
    onSelect,
    disabled,
  }: {
    value: string | null;
    onSelect: (c: string) => void;
    disabled?: boolean;
  }) => (
    <button
      type="button"
      data-testid="category-picker"
      disabled={disabled}
      onClick={() => onSelect("Dining")}
    >
      {value ?? "Uncategorized"}
    </button>
  ),
}));

// --- Fixture builders -------------------------------------------------------
function rawTxn(over: Partial<StatementUploadResponse["transactions"][number]> = {}) {
  return {
    amount: 12.5,
    balance: null,
    date: "2026-03-15",
    description: "RAW DESC",
    type: "withdrawal" as const,
    ...over,
  };
}

function newItem(index: number, over: Partial<NewItem> = {}): NewItem {
  return {
    index,
    row_id: `row-${index}`,
    raw_description: `new-raw-${index}`,
    cleaned_description: `new-clean-${index}`,
    suggested_category: `new-cat-${index}`,
    statement_txn: rawTxn(),
    ...over,
  };
}

function matchedItem(index: number, over: Partial<MatchedItem> = {}): MatchedItem {
  return {
    index,
    row_id: `row-${index}`,
    raw_description: `matched-raw-${index}`,
    cleaned_description: `matched-clean-${index}`,
    suggested_category: `matched-cat-${index}`,
    company_differs: true,
    db_match: {
      amount: 12.5,
      category: "db-cat",
      company: "DB Co",
      date_file_name: `dfn-${index}`,
      forwarded_to: `fwd-${index}`,
    },
    statement_txn: rawTxn(),
    ...over,
  };
}

function ambiguousItem(index: number, over: Partial<AmbiguousItem> = {}): AmbiguousItem {
  return {
    index,
    row_id: `row-${index}`,
    raw_description: `amb-raw-${index}`,
    cleaned_description: `amb-clean-${index}`,
    suggested_category: `amb-cat-${index}`,
    enrichable: true,
    reason: "amount+date near-match",
    candidates: [
      {
        amount: 12.5,
        category: "cand-cat",
        company: "Cand Co",
        date_file_name: "shared-dfn",
        forwarded_to: "shared-fwd",
      },
    ],
    statement_txn: rawTxn(),
    ...over,
  };
}

function prevItem(
  index: number,
  over: Partial<PreviouslyImportedItem> = {}
): PreviouslyImportedItem {
  return {
    index,
    row_id: `row-${index}`,
    raw_description: `prev-raw-${index}`,
    cleaned_description: `prev-clean-${index}`,
    suggested_category: `prev-cat-${index}`,
    db_match: {
      amount: 12.5,
      category: "db-cat",
      company: "DB Co",
      date_file_name: `prev-dfn-${index}`,
      forwarded_to: `prev-fwd-${index}`,
    },
    statement_txn: rawTxn(),
    ...over,
  };
}

function dupItem(
  index: number,
  over: Partial<SuspectedDuplicateItem> = {}
): SuspectedDuplicateItem {
  return {
    index,
    row_id: `row-${index}`,
    raw_description: `dup-raw-${index}`,
    cleaned_description: `dup-clean-${index}`,
    suggested_category: `dup-cat-${index}`,
    reason: "same amount+date",
    db_match: {
      amount: 12.5,
      category: "db-cat",
      company: "DB Co",
      date_file_name: `dup-dfn-${index}`,
      forwarded_to: `dup-fwd-${index}`,
      transaction_type: "purchase",
    },
    statement_txn: rawTxn(),
    ...over,
  };
}

// Full fixture covering all five buckets. Index layout:
//   prev=0, matched=1, ambiguous=2 & 3 (share one candidate), dup=4, new=5 & 6.
function fullFixture(): StatementUploadResponse {
  return {
    statement_id: "stmt-1",
    metadata: {
      institution: "RBC",
      account_type: "chequing",
      period_start: "2026-03-01",
      period_end: "2026-03-31",
      transaction_count: 7,
      parsed_with_ai: false,
    },
    summary: {
      ambiguous_count: 2,
      duplicate_count: 0,
      enriched_count: 0,
      imported_count: 0,
      matched_count: 1,
      new_count: 2,
      previously_imported_count: 1,
      skipped_count: 0,
      suspected_duplicate_count: 1,
      total_parsed: 7,
      updated_count: 0,
    },
    previously_imported: [prevItem(0)],
    matched: [matchedItem(1)],
    ambiguous: [ambiguousItem(2), ambiguousItem(3)],
    suspected_duplicates: [dupItem(4)],
    new: [newItem(5), newItem(6)],
    transactions: [],
  };
}

// Fixture with only "new" rows — isolates the save-dispatch tests from the
// ambiguous section, whose pickers/checkboxes otherwise render first in the DOM.
function newOnlyFixture(count: number): StatementUploadResponse {
  const items = Array.from({ length: count }, (_, i) => newItem(5 + i));
  return {
    ...fullFixture(),
    previously_imported: [],
    matched: [],
    ambiguous: [],
    suspected_duplicates: [],
    new: items,
    summary: {
      ...fullFixture().summary,
      ambiguous_count: 0,
      matched_count: 0,
      previously_imported_count: 0,
      suspected_duplicate_count: 0,
      new_count: count,
    },
  };
}

function renderReview(data: StatementUploadResponse, onImport = vi.fn()) {
  render(
    <StatementReview
      data={data}
      onImport={onImport}
      isImporting={false}
      statementId={data.statement_id}
    />
  );
  return { onImport };
}

beforeEach(() => {
  mutateSpy.mockClear();
});

afterEach(() => {
  vi.useRealTimers();
});

describe("StatementReview — handleSubmit action assembly", () => {
  it("assembles the default payload across all five buckets", () => {
    const { onImport } = renderReview(fullFixture());

    // Submit label counts import(2 new) + enrich(3: 2 ambiguous states + matched);
    // note enrichCount reflects row STATE, not the claiming outcome (row 3 loses
    // its candidate at assembly time yet still shows as enrich here).
    fireEvent.click(screen.getByRole("button", { name: "Import 2 / Enrich 3" }));

    expect(onImport).toHaveBeenCalledTimes(1);
    const actions = onImport.mock.calls[0]![0] as ImportAction[];

    expect(actions).toEqual([
      // New — both default to import, seeded company=raw, category=suggested.
      { index: 5, action: "import", category: "new-cat-5", company: "new-raw-5" },
      { index: 6, action: "import", category: "new-cat-6", company: "new-raw-6" },
      // Ambiguous — first row claims the shared candidate, second is starved → skip.
      {
        index: 2,
        action: "enrich",
        company: "amb-raw-2",
        category: "amb-cat-2",
        forwarded_to: "shared-fwd",
        date_file_name: "shared-dfn",
      },
      { index: 3, action: "skip" },
      // Matched — company_differs seeds enrich, carries db_match coords.
      {
        index: 1,
        action: "enrich",
        company: "matched-raw-1",
        category: "matched-cat-1",
        forwarded_to: "fwd-1",
        date_file_name: "dfn-1",
      },
      // Suspected duplicate — defaults to skip.
      { index: 4, action: "skip" },
    ]);
    // Previously-imported defaults to skip and is intentionally omitted entirely.
    expect(actions.some((a) => a.index === 0)).toBe(false);
  });

  it("emits update/import entries when prev-imported and suspected-dup are toggled on", () => {
    const { onImport } = renderReview(fullFixture());

    // Expand the collapsed "Previously Imported" section, then toggle to update.
    fireEvent.click(screen.getByText(/Previously Imported \(1\)/));
    fireEvent.click(screen.getByRole("checkbox", { name: /Select \(update\)/i }));

    // Toggle the suspected-duplicate row to import.
    fireEvent.click(screen.getByRole("checkbox", { name: /Select \(import\)/i }));

    fireEvent.click(screen.getByRole("button", { name: /Update 1/ }));

    const actions = onImport.mock.calls[0]![0] as ImportAction[];

    // Previously-imported → update, with db_match coords.
    expect(actions).toContainEqual({
      index: 0,
      action: "update",
      company: "prev-raw-0",
      category: "prev-cat-0",
      forwarded_to: "prev-fwd-0",
      date_file_name: "prev-dfn-0",
    });
    // Suspected-duplicate → import (company=raw, category=suggested).
    expect(actions).toContainEqual({
      index: 4,
      action: "import",
      category: "dup-cat-4",
      company: "dup-raw-4",
    });
  });
});

describe("StatementReview — usedAmbiguousKeys candidate claiming", () => {
  it("gives the shared candidate to the first ambiguous row only; the second skips", () => {
    // Two ambiguous rows, both enrich, both list only the same single candidate.
    const data = fullFixture();
    const { onImport } = renderReview(data);

    fireEvent.click(screen.getByRole("button", { name: "Import 2 / Enrich 3" }));

    const actions = onImport.mock.calls[0]![0] as ImportAction[];
    const amb = actions.filter((a) => a.index === 2 || a.index === 3);
    expect(amb).toEqual([
      {
        index: 2,
        action: "enrich",
        company: "amb-raw-2",
        category: "amb-cat-2",
        forwarded_to: "shared-fwd",
        date_file_name: "shared-dfn",
      },
      { index: 3, action: "skip" },
    ]);
  });
});

describe("StatementReview — immediate saves (action & category)", () => {
  it("saves immediately with the row_id when an action toggles", () => {
    renderReview(newOnlyFixture(1));

    // The single "new" row (row-5) defaults to import; flip it to skip.
    fireEvent.click(screen.getByRole("checkbox", { name: /Deselect \(will skip\)/i }));

    expect(mutateSpy).toHaveBeenCalledTimes(1);
    expect(mutateSpy).toHaveBeenCalledWith({
      rowId: "row-5", // row_id from the map, NOT the positional index (5)
      data: { action: "skip", company: "new-raw-5", category: "new-cat-5" },
    });
  });

  it("saves immediately with the row_id when a category is picked", () => {
    renderReview(newOnlyFixture(1));

    // The only category picker belongs to the new row (row-5).
    fireEvent.click(screen.getByTestId("category-picker"));

    expect(mutateSpy).toHaveBeenCalledTimes(1);
    expect(mutateSpy).toHaveBeenCalledWith({
      rowId: "row-5",
      data: { action: "import", company: "new-raw-5", category: "dining" },
    });
  });
});

describe("StatementReview — debounced company save", () => {
  it("collapses rapid company edits into one save after 300ms with the final value", () => {
    vi.useFakeTimers();
    renderReview(newOnlyFixture(1));

    // The only company Input belongs to the new row (row-5).
    const input = screen.getByRole("textbox");

    fireEvent.change(input, { target: { value: "Aa" } });
    fireEvent.change(input, { target: { value: "Acm" } });
    fireEvent.change(input, { target: { value: "Acme" } });

    // Nothing dispatched until the debounce window elapses.
    expect(mutateSpy).not.toHaveBeenCalled();

    act(() => {
      vi.advanceTimersByTime(300);
    });

    expect(mutateSpy).toHaveBeenCalledTimes(1);
    expect(mutateSpy).toHaveBeenCalledWith({
      rowId: "row-5",
      data: { action: "import", company: "Acme", category: "new-cat-5" },
    });
  });
});

describe("StatementReview — bulkSetAction", () => {
  it("dispatches one save per affected row on Skip All", () => {
    renderReview(newOnlyFixture(2));

    // Both new rows default to import; Skip All flips both → two saves.
    fireEvent.click(screen.getByRole("button", { name: /^Skip All$/ }));

    expect(mutateSpy).toHaveBeenCalledTimes(2);
    const savedRowIds = mutateSpy.mock.calls.map((c) => c[0].rowId).sort();
    expect(savedRowIds).toEqual(["row-5", "row-6"]);
    for (const call of mutateSpy.mock.calls) {
      expect(call[0].data.action).toBe("skip");
    }
  });
});
