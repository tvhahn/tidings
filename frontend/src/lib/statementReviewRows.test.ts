import { describe, expect, it } from "vitest";
import {
  assembleImportActions,
  bulkSetSectionAction,
  classifyUpdate,
  countAction,
  initRowStates,
  mergeRow,
  someActionNot,
  summarizeStates,
  type RowState,
  type RowStates,
} from "@/lib/statementReviewRows";
import { makeStatementUploadResponse } from "@/test/factories";
import type {
  AmbiguousItem,
  MatchedItem,
  NewItem,
  PreviouslyImportedItem,
  StatementUploadResponse,
  SuspectedDuplicateItem,
} from "@/types/api";

const rawTxn = {
  amount: 12.5,
  balance: null,
  date: "2026-03-15",
  description: "RAW",
  type: "withdrawal" as const,
};

function newItem(index: number): NewItem {
  return {
    index,
    row_id: `row-${index}`,
    raw_description: `new-raw-${index}`,
    cleaned_description: `new-clean-${index}`,
    suggested_category: `new-cat-${index}`,
    statement_txn: rawTxn,
  };
}
function matchedItem(index: number, company_differs: boolean): MatchedItem {
  return {
    index,
    row_id: `row-${index}`,
    raw_description: `matched-raw-${index}`,
    cleaned_description: `matched-clean-${index}`,
    suggested_category: `matched-cat-${index}`,
    company_differs,
    db_match: {
      amount: 12.5,
      category: "db",
      company: "DB",
      date_file_name: `dfn-${index}`,
      forwarded_to: `fwd-${index}`,
    },
    statement_txn: rawTxn,
  };
}
function ambiguousItem(index: number, candidateKey: string): AmbiguousItem {
  const [forwarded_to, date_file_name] = candidateKey.split("|");
  return {
    index,
    row_id: `row-${index}`,
    raw_description: `amb-raw-${index}`,
    cleaned_description: `amb-clean-${index}`,
    suggested_category: `amb-cat-${index}`,
    enrichable: true,
    reason: "near-match",
    candidates: [
      {
        amount: 12.5,
        category: "c",
        company: "C",
        forwarded_to: forwarded_to!,
        date_file_name: date_file_name!,
      },
    ],
    statement_txn: rawTxn,
  };
}
function prevItem(index: number): PreviouslyImportedItem {
  return {
    index,
    row_id: `row-${index}`,
    raw_description: `prev-raw-${index}`,
    cleaned_description: `prev-clean-${index}`,
    suggested_category: `prev-cat-${index}`,
    db_match: {
      amount: 12.5,
      category: "db",
      company: "DB",
      date_file_name: `prev-dfn-${index}`,
      forwarded_to: `prev-fwd-${index}`,
    },
    statement_txn: rawTxn,
  };
}
function dupItem(index: number): SuspectedDuplicateItem {
  return {
    index,
    row_id: `row-${index}`,
    raw_description: `dup-raw-${index}`,
    cleaned_description: `dup-clean-${index}`,
    suggested_category: `dup-cat-${index}`,
    reason: "dup",
    db_match: {
      amount: 12.5,
      category: "db",
      company: "DB",
      date_file_name: `dup-dfn-${index}`,
      forwarded_to: `dup-fwd-${index}`,
      transaction_type: "purchase",
    },
    statement_txn: rawTxn,
  };
}

function fixture(): StatementUploadResponse {
  return makeStatementUploadResponse({
    previously_imported: [prevItem(0)],
    matched: [matchedItem(1, true)],
    ambiguous: [
      ambiguousItem(2, "shared-fwd|shared-dfn"),
      ambiguousItem(3, "shared-fwd|shared-dfn"),
    ],
    suspected_duplicates: [dupItem(4)],
    new: [newItem(5), newItem(6)],
  });
}

describe("initRowStates", () => {
  it("seeds each bucket with the correct default action and section", () => {
    const s = initRowStates(fixture());
    expect(s[5]).toEqual({
      section: "new",
      action: "import",
      company: "new-raw-5",
      category: "new-cat-5",
    });
    expect(s[2]).toEqual({
      section: "ambiguous",
      action: "enrich",
      company: "amb-raw-2",
      category: "amb-cat-2",
    });
    expect(s[4]).toEqual({
      section: "suspected_duplicates",
      action: "skip",
      company: "dup-raw-4",
      category: "dup-cat-4",
    });
    expect(s[0]).toEqual({
      section: "previously_imported",
      action: "skip",
      company: "prev-raw-0",
      category: "prev-cat-0",
    });
  });

  it("seeds matched as enrich only when company_differs", () => {
    const differs = initRowStates(makeStatementUploadResponse({ matched: [matchedItem(1, true)] }));
    const same = initRowStates(makeStatementUploadResponse({ matched: [matchedItem(1, false)] }));
    expect(differs[1]?.action).toBe("enrich");
    expect(same[1]?.action).toBe("skip");
  });
});

describe("classifyUpdate", () => {
  it("prioritizes action → immediate, company → debounced, category → immediate", () => {
    expect(classifyUpdate({ action: "skip" })).toBe("immediate");
    expect(classifyUpdate({ company: "Acme" })).toBe("debounced");
    expect(classifyUpdate({ category: "dining" })).toBe("immediate");
    expect(classifyUpdate({})).toBe("none");
  });

  it("action wins when multiple fields change together", () => {
    expect(classifyUpdate({ action: "skip", company: "x" })).toBe("immediate");
    expect(classifyUpdate({ company: "x", category: "y" })).toBe("debounced");
  });
});

describe("mergeRow", () => {
  it("merges updates while preserving the section discriminant", () => {
    const row: RowState = { section: "new", action: "import", company: "a", category: "b" };
    expect(mergeRow(row, { company: "c" })).toEqual({
      section: "new",
      action: "import",
      company: "c",
      category: "b",
    });
    expect(mergeRow(row, { action: "skip" })).toEqual({
      section: "new",
      action: "skip",
      company: "a",
      category: "b",
    });
  });
});

describe("count / query helpers", () => {
  it("countAction and someActionNot scope to a single section", () => {
    const s = initRowStates(fixture());
    expect(countAction(s, "new", "import")).toBe(2);
    expect(countAction(s, "ambiguous", "enrich")).toBe(2);
    expect(countAction(s, "suspected_duplicates", "import")).toBe(0);
    expect(someActionNot(s, "new", "import")).toBe(false);
    expect(someActionNot(s, "new", "skip")).toBe(true);
  });

  it("summarizeStates aggregates import/enrich/update across the right sections", () => {
    expect(summarizeStates(initRowStates(fixture()))).toEqual({
      importCount: 2,
      enrichCount: 3,
      updateCount: 0,
    });
  });
});

describe("bulkSetSectionAction", () => {
  it("flips only the target section and reports changed indices", () => {
    const s = initRowStates(fixture());
    const { next, changed } = bulkSetSectionAction(s, "new", "skip");
    expect(changed.sort()).toEqual([5, 6]);
    expect(next[5]?.action).toBe("skip");
    expect(next[6]?.action).toBe("skip");
    // Other sections untouched.
    expect(next[2]?.action).toBe("enrich");
    expect(next[4]?.action).toBe("skip");
  });

  it("reports no changes when every row is already the target action", () => {
    const s = initRowStates(fixture());
    const { changed } = bulkSetSectionAction(s, "new", "import");
    expect(changed).toEqual([]);
  });
});

describe("assembleImportActions", () => {
  it("reproduces the full default payload across all five buckets", () => {
    const data = fixture();
    const actions = assembleImportActions(data, initRowStates(data));
    expect(actions).toEqual([
      { index: 5, action: "import", category: "new-cat-5", company: "new-raw-5" },
      { index: 6, action: "import", category: "new-cat-6", company: "new-raw-6" },
      {
        index: 2,
        action: "enrich",
        company: "amb-raw-2",
        category: "amb-cat-2",
        forwarded_to: "shared-fwd",
        date_file_name: "shared-dfn",
      },
      { index: 3, action: "skip" },
      {
        index: 1,
        action: "enrich",
        company: "matched-raw-1",
        category: "matched-cat-1",
        forwarded_to: "fwd-1",
        date_file_name: "dfn-1",
      },
      { index: 4, action: "skip" },
    ]);
  });

  it("claims a shared ambiguous candidate for the first row only", () => {
    const data = fixture();
    const actions = assembleImportActions(data, initRowStates(data));
    expect(actions.filter((a) => a.index === 2 || a.index === 3)).toEqual([
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

  it("gives distinct candidates to distinct rows", () => {
    const data = makeStatementUploadResponse({
      ambiguous: [ambiguousItem(2, "a|1"), ambiguousItem(3, "b|2")],
    });
    const actions = assembleImportActions(data, initRowStates(data));
    expect(actions).toEqual([
      {
        index: 2,
        action: "enrich",
        company: "amb-raw-2",
        category: "amb-cat-2",
        forwarded_to: "a",
        date_file_name: "1",
      },
      {
        index: 3,
        action: "enrich",
        company: "amb-raw-3",
        category: "amb-cat-3",
        forwarded_to: "b",
        date_file_name: "2",
      },
    ]);
  });

  it("emits update/import entries when prev-imported and suspected-dup are toggled on", () => {
    const data = fixture();
    const states: RowStates = {
      ...initRowStates(data),
      0: {
        section: "previously_imported",
        action: "update",
        company: "prev-raw-0",
        category: "prev-cat-0",
      },
      4: {
        section: "suspected_duplicates",
        action: "import",
        company: "dup-raw-4",
        category: "dup-cat-4",
      },
    };
    const actions = assembleImportActions(data, states);
    expect(actions).toContainEqual({
      index: 0,
      action: "update",
      company: "prev-raw-0",
      category: "prev-cat-0",
      forwarded_to: "prev-fwd-0",
      date_file_name: "prev-dfn-0",
    });
    expect(actions).toContainEqual({
      index: 4,
      action: "import",
      category: "dup-cat-4",
      company: "dup-raw-4",
    });
  });

  it("omits matched rows left on skip", () => {
    const data = makeStatementUploadResponse({ matched: [matchedItem(1, false)] });
    const actions = assembleImportActions(data, initRowStates(data));
    expect(actions).toEqual([]);
  });
});
