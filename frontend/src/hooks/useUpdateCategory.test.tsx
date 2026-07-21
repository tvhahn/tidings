import { toast } from "sonner";
import { afterEach, beforeEach, describe, expect, it, vi } from "vitest";
import { useUpdateCategory } from "@/hooks/useUpdateCategory";
import { txIdFromComposite } from "@/lib/api";
import { mockFetchError, mockFetchJSON } from "@/test/api-mock";
import { makeTxn } from "@/test/factories";
import { renderHookWithProviders } from "@/test/render";

vi.mock("sonner", () => {
  const mockToast = Object.assign(vi.fn(), { success: vi.fn(), error: vi.fn() });
  return { toast: mockToast };
});

const FWD = "user";
const DFN = "d1";
// updateCategory PATCHes the bare transaction path (no action suffix).
const CATEGORY_URL = `/api/v1/transactions/${txIdFromComposite(FWD, DFN)}`;

type Bucket = { transactions: ReturnType<typeof makeTxn>[]; count: number };
type Combined = { transactions: Bucket; attention: Bucket; trash: Bucket };
type SearchList = { transactions: ReturnType<typeof makeTxn>[]; total_matching: number };
type JournalList = { days: { transactions: ReturnType<typeof makeTxn>[] }[] };

function seedCombined(txn: ReturnType<typeof makeTxn>): Combined {
  return {
    transactions: { transactions: [txn], count: 1 },
    attention: { transactions: [], count: 0 },
    trash: { transactions: [], count: 0 },
  };
}

function seedJournal(txn: ReturnType<typeof makeTxn>): JournalList {
  return { days: [{ transactions: [txn] }] };
}

beforeEach(() => vi.clearAllMocks());
afterEach(() => vi.unstubAllGlobals());

describe("useUpdateCategory", () => {
  it("optimistically lowercases the category across the flat and combined caches", async () => {
    mockFetchJSON({ [CATEGORY_URL]: {} });
    const { result, queryClient } = renderHookWithProviders(() => useUpdateCategory());
    const txn = makeTxn({ forwarded_to: FWD, date_file_name: DFN, category: "groceries" });
    queryClient.setQueryData(["transactions", "2026-02"], { transactions: [txn], count: 1 });
    queryClient.setQueryData(["transactions-combined", "2026-02"], seedCombined(txn));

    await result.current.mutateAsync({
      forwardedTo: FWD,
      dateFileName: DFN,
      category: "Dining",
      oldCategory: "groceries",
    });

    const flat = queryClient.getQueryData(["transactions", "2026-02"]) as Bucket;
    expect(flat.transactions[0]?.category).toBe("dining");
    const combined = queryClient.getQueryData(["transactions-combined", "2026-02"]) as Combined;
    expect(combined.transactions.transactions[0]?.category).toBe("dining");
  });

  it("also lowercases the category across the search and journal caches", async () => {
    mockFetchJSON({ [CATEGORY_URL]: {} });
    const { result, queryClient } = renderHookWithProviders(() => useUpdateCategory());
    const txn = makeTxn({ forwarded_to: FWD, date_file_name: DFN, category: "groceries" });
    queryClient.setQueryData(["transaction-search", { q: "x" }], {
      transactions: [txn],
      total_matching: 1,
    });
    queryClient.setQueryData(["journal", "2026-02"], seedJournal(txn));

    await result.current.mutateAsync({
      forwardedTo: FWD,
      dateFileName: DFN,
      category: "Dining",
      oldCategory: "groceries",
    });

    const search = queryClient.getQueryData(["transaction-search", { q: "x" }]) as SearchList;
    expect(search.transactions[0]?.category).toBe("dining");
    const journal = queryClient.getQueryData(["journal", "2026-02"]) as JournalList;
    expect(journal.days[0]?.transactions[0]?.category).toBe("dining");
  });

  it("rolls every snapshotted cache back on failure", async () => {
    mockFetchError();
    const { result, queryClient } = renderHookWithProviders(() => useUpdateCategory());
    const txn = makeTxn({ forwarded_to: FWD, date_file_name: DFN, category: "groceries" });
    queryClient.setQueryData(["transactions", "2026-02"], { transactions: [txn], count: 1 });
    queryClient.setQueryData(["transactions-combined", "2026-02"], seedCombined(txn));

    await expect(
      result.current.mutateAsync({
        forwardedTo: FWD,
        dateFileName: DFN,
        category: "Dining",
        oldCategory: "groceries",
      })
    ).rejects.toBeTruthy();

    const flat = queryClient.getQueryData(["transactions", "2026-02"]) as Bucket;
    expect(flat.transactions[0]?.category).toBe("groceries"); // restored
    const combined = queryClient.getQueryData(["transactions-combined", "2026-02"]) as Combined;
    expect(combined.transactions.transactions[0]?.category).toBe("groceries");
    // This hook intentionally has no error toast (the pill snapping back is the signal).
    expect(toast.error).not.toHaveBeenCalled();
  });

  it("restores the exact search and journal snapshots on failure", async () => {
    mockFetchError();
    const { result, queryClient } = renderHookWithProviders(() => useUpdateCategory());
    const txn = makeTxn({ forwarded_to: FWD, date_file_name: DFN, category: "groceries" });
    const searchSnapshot = { transactions: [txn], total_matching: 1 };
    const journalSnapshot = seedJournal(txn);
    queryClient.setQueryData(["transaction-search", { q: "y" }], searchSnapshot);
    queryClient.setQueryData(["journal", "2026-02"], journalSnapshot);

    await expect(
      result.current.mutateAsync({
        forwardedTo: FWD,
        dateFileName: DFN,
        category: "Dining",
        oldCategory: "groceries",
      })
    ).rejects.toBeTruthy();

    // Deep-equal the pre-mutation snapshots — the search + journal rollback loops.
    expect(queryClient.getQueryData(["transaction-search", { q: "y" }])).toEqual(searchSnapshot);
    expect(queryClient.getQueryData(["journal", "2026-02"])).toEqual(journalSnapshot);
  });
});
