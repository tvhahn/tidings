import { waitFor } from "@testing-library/react";
import { toast } from "sonner";
import { afterEach, beforeEach, describe, expect, it, vi } from "vitest";
import { useSoftDelete } from "@/hooks/useSoftDelete";
import { txIdFromComposite } from "@/lib/api";
import { mockFetchError, mockFetchJSON } from "@/test/api-mock";
import { makeTxn } from "@/test/factories";
import { renderHookWithProviders } from "@/test/render";

// Capture sonner toast calls without rendering the portal-based Toaster.
vi.mock("sonner", () => {
  const mockToast = Object.assign(vi.fn(), { success: vi.fn(), error: vi.fn() });
  return { toast: mockToast };
});

const FWD = "user";
const DFN = "d1";
const DELETE_URL = `/api/v1/transactions/${txIdFromComposite(FWD, DFN)}/delete`;

type TxnList = { transactions: ReturnType<typeof makeTxn>[]; count: number };
type SearchList = { transactions: ReturnType<typeof makeTxn>[]; total_matching: number };

beforeEach(() => vi.clearAllMocks());
afterEach(() => vi.unstubAllGlobals());

describe("useSoftDelete", () => {
  it("optimistically removes the row from the transactions cache", async () => {
    mockFetchJSON({ [DELETE_URL]: {} });
    const { result, queryClient } = renderHookWithProviders(() => useSoftDelete());
    const txn = makeTxn({ forwarded_to: FWD, date_file_name: DFN });
    queryClient.setQueryData(["transactions", "2026-02"], { transactions: [txn], count: 1 });

    await result.current.mutateAsync({ forwardedTo: FWD, dateFileName: DFN });

    const cached = queryClient.getQueryData(["transactions", "2026-02"]) as TxnList;
    expect(cached.transactions).toHaveLength(0);
    expect(cached.count).toBe(0);
  });

  it("also drops the row from the transaction-search cache", async () => {
    mockFetchJSON({ [DELETE_URL]: {} });
    const { result, queryClient } = renderHookWithProviders(() => useSoftDelete());
    const target = makeTxn({ forwarded_to: FWD, date_file_name: DFN });
    const other = makeTxn({ forwarded_to: "other", date_file_name: "d2" });
    queryClient.setQueryData(["transaction-search", { q: "x" }], {
      transactions: [target, other],
      total_matching: 5,
    });

    await result.current.mutateAsync({ forwardedTo: FWD, dateFileName: DFN });

    const search = queryClient.getQueryData(["transaction-search", { q: "x" }]) as SearchList;
    expect(search.transactions).toHaveLength(1);
    expect(search.transactions[0]?.forwarded_to).toBe("other");
    // total_matching decremented by exactly the number of removed rows (1).
    expect(search.total_matching).toBe(4);
  });

  it("rolls the cache back and toasts on failure", async () => {
    mockFetchError();
    const { result, queryClient } = renderHookWithProviders(() => useSoftDelete());
    const txn = makeTxn({ forwarded_to: FWD, date_file_name: DFN });
    queryClient.setQueryData(["transactions", "2026-02"], { transactions: [txn], count: 1 });

    await expect(
      result.current.mutateAsync({ forwardedTo: FWD, dateFileName: DFN })
    ).rejects.toBeTruthy();

    const cached = queryClient.getQueryData(["transactions", "2026-02"]) as TxnList;
    expect(cached.transactions).toHaveLength(1); // snapshot restored
    await waitFor(() => expect(toast.error).toHaveBeenCalledWith("Failed to delete transaction"));
  });

  it("restores the exact transactions AND search snapshots on failure", async () => {
    mockFetchError();
    const { result, queryClient } = renderHookWithProviders(() => useSoftDelete());
    const txn = makeTxn({ forwarded_to: FWD, date_file_name: DFN });
    const txnSnapshot = { transactions: [txn], count: 1 };
    const searchSnapshot = { transactions: [txn], total_matching: 3 };
    queryClient.setQueryData(["transactions", "2026-02"], txnSnapshot);
    queryClient.setQueryData(["transaction-search", { q: "y" }], searchSnapshot);

    await expect(
      result.current.mutateAsync({ forwardedTo: FWD, dateFileName: DFN })
    ).rejects.toBeTruthy();

    // Both caches deep-equal their pre-mutation snapshots — not just "a row is back".
    expect(queryClient.getQueryData(["transactions", "2026-02"])).toEqual(txnSnapshot);
    expect(queryClient.getQueryData(["transaction-search", { q: "y" }])).toEqual(searchSnapshot);
  });

  it("offers an Undo action that invalidates on success", async () => {
    mockFetchJSON({ [DELETE_URL]: {} });
    const { result, queryClient } = renderHookWithProviders(() => useSoftDelete());
    const invalidate = vi.spyOn(queryClient, "invalidateQueries");
    queryClient.setQueryData(["transactions", "2026-02"], {
      transactions: [makeTxn({ forwarded_to: FWD, date_file_name: DFN })],
      count: 1,
    });

    await result.current.mutateAsync({ forwardedTo: FWD, dateFileName: DFN });

    await waitFor(() =>
      expect(toast).toHaveBeenCalledWith("Transaction deleted", expect.any(Object))
    );
    const call = (toast as unknown as { mock: { calls: unknown[][] } }).mock.calls.find(
      (c) => c[0] === "Transaction deleted"
    );
    const action = (call?.[1] as { action: { onClick: () => void } }).action;
    invalidate.mockClear();
    await action.onClick();
    await waitFor(() => expect(invalidate).toHaveBeenCalled());
  });
});
