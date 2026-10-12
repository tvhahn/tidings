import { waitFor } from "@testing-library/react";
import { toast } from "sonner";
import { afterEach, beforeEach, describe, expect, it, vi } from "vitest";
import { useUpdateTransactionFields } from "@/hooks/useUpdateTransactionFields";
import { txIdFromComposite } from "@/lib/api";
import { mockFetchError, mockFetchJSON, pendingResponse } from "@/test/api-mock";
import { makeCombined, makeTxn } from "@/test/factories";
import { renderHookWithProviders } from "@/test/render";
import type { CombinedTransactionsResponse as Combined } from "@/types/api";

vi.mock("sonner", () => {
  const mockToast = Object.assign(vi.fn(), { success: vi.fn(), error: vi.fn() });
  return { toast: mockToast };
});

const FWD = "user";
const DFN = "d1";
const FIELDS_URL = `/api/v1/transactions/${txIdFromComposite(FWD, DFN)}/fields`;

// The onSuccess handler reads data.category and data.old_values, so the mock
// response must carry the real TransactionFieldsUpdateResponse shape.
const OK_RESPONSE = {
  category: null,
  old_values: { company: null, amount: null, transaction_type: null },
};

type TxnList = { transactions: ReturnType<typeof makeTxn>[]; count: number };
type SearchList = { transactions: ReturnType<typeof makeTxn>[]; total_matching: number };

beforeEach(() => vi.clearAllMocks());
afterEach(() => vi.unstubAllGlobals());

describe("useUpdateTransactionFields", () => {
  it("optimistically applies the changed fields to the cache", async () => {
    mockFetchJSON({ [FIELDS_URL]: OK_RESPONSE });
    const { result, queryClient } = renderHookWithProviders(() => useUpdateTransactionFields());
    queryClient.setQueryData(["transactions", "2026-02"], {
      transactions: [
        makeTxn({ forwarded_to: FWD, date_file_name: DFN, company: "Old Co", amount: 10 }),
      ],
      count: 1,
    });

    await result.current.mutateAsync({
      forwardedTo: FWD,
      dateFileName: DFN,
      fields: { company: "New Co", amount: 99 },
    });

    const cached = queryClient.getQueryData(["transactions", "2026-02"]) as TxnList;
    expect(cached.transactions[0]?.company).toBe("New Co");
    expect(cached.transactions[0]?.amount).toBe(99);
  });

  it("also applies the changed fields to the transaction-search cache", async () => {
    mockFetchJSON({ [FIELDS_URL]: OK_RESPONSE });
    const { result, queryClient } = renderHookWithProviders(() => useUpdateTransactionFields());
    queryClient.setQueryData(["transaction-search", { q: "x" }], {
      transactions: [makeTxn({ forwarded_to: FWD, date_file_name: DFN, company: "Old Co" })],
      total_matching: 1,
    });

    await result.current.mutateAsync({
      forwardedTo: FWD,
      dateFileName: DFN,
      fields: { company: "New Co" },
    });

    const search = queryClient.getQueryData(["transaction-search", { q: "x" }]) as SearchList;
    expect(search.transactions[0]?.company).toBe("New Co");
  });

  it("applies a server-side auto-category to both caches on success", async () => {
    // When an override auto-recategorizes the transaction, the server echoes a
    // `category`; onSuccess must fan that value into the flat + search caches.
    mockFetchJSON({
      [FIELDS_URL]: {
        category: "dining",
        old_values: { company: null, amount: null, transaction_type: null },
      },
    });
    const { result, queryClient } = renderHookWithProviders(() => useUpdateTransactionFields());
    queryClient.setQueryData(["transactions", "2026-02"], {
      transactions: [
        makeTxn({
          forwarded_to: FWD,
          date_file_name: DFN,
          company: "Old Co",
          category: "groceries",
        }),
      ],
      count: 1,
    });
    queryClient.setQueryData(["transaction-search", { q: "x" }], {
      transactions: [
        makeTxn({
          forwarded_to: FWD,
          date_file_name: DFN,
          company: "Old Co",
          category: "groceries",
        }),
      ],
      total_matching: 1,
    });

    await result.current.mutateAsync({
      forwardedTo: FWD,
      dateFileName: DFN,
      fields: { company: "New Co" },
    });

    const flat = queryClient.getQueryData(["transactions", "2026-02"]) as TxnList;
    expect(flat.transactions[0]?.category).toBe("dining");
    const search = queryClient.getQueryData(["transaction-search", { q: "x" }]) as SearchList;
    expect(search.transactions[0]?.category).toBe("dining");
  });

  it("optimistically applies the fields in the combined cache and the server category on success", async () => {
    const pending = pendingResponse({ ...OK_RESPONSE, category: "dining" });
    mockFetchJSON({ [FIELDS_URL]: pending.responder });
    const { result, queryClient } = renderHookWithProviders(() => useUpdateTransactionFields());
    const txn = makeTxn({ forwarded_to: FWD, date_file_name: DFN, company: "Old Co", amount: 10 });
    queryClient.setQueryData(
      ["transactions-combined", "2026-02"],
      makeCombined({ transactions: [txn] })
    );

    result.current.mutate({
      forwardedTo: FWD,
      dateFileName: DFN,
      fields: { company: "New Co", amount: 99 },
    });

    await waitFor(() => {
      const combined = queryClient.getQueryData(["transactions-combined", "2026-02"]) as Combined;
      expect(combined.transactions.transactions[0]?.company).toBe("New Co");
    });
    let combined = queryClient.getQueryData(["transactions-combined", "2026-02"]) as Combined;
    expect(combined.transactions.transactions[0]?.amount).toBe(99);
    expect(combined.transactions.transactions[0]?.category).toBe("groceries");

    pending.release();
    await waitFor(() => expect(result.current.isSuccess).toBe(true));
    combined = queryClient.getQueryData(["transactions-combined", "2026-02"]) as Combined;
    expect(combined.transactions.transactions[0]?.category).toBe("dining");
  });

  it("restores the exact combined snapshot on failure", async () => {
    mockFetchError();
    const { result, queryClient } = renderHookWithProviders(() => useUpdateTransactionFields());
    const txn = makeTxn({ forwarded_to: FWD, date_file_name: DFN, company: "Old Co", amount: 10 });
    const snapshot = makeCombined({ transactions: [txn] });
    queryClient.setQueryData(["transactions-combined", "2026-02"], snapshot);

    await expect(
      result.current.mutateAsync({
        forwardedTo: FWD,
        dateFileName: DFN,
        fields: { company: "New Co" },
      })
    ).rejects.toBeTruthy();

    expect(queryClient.getQueryData(["transactions-combined", "2026-02"])).toEqual(snapshot);
  });

  it("rolls back and toasts on failure", async () => {
    mockFetchError();
    const { result, queryClient } = renderHookWithProviders(() => useUpdateTransactionFields());
    queryClient.setQueryData(["transactions", "2026-02"], {
      transactions: [
        makeTxn({ forwarded_to: FWD, date_file_name: DFN, company: "Old Co", amount: 10 }),
      ],
      count: 1,
    });

    await expect(
      result.current.mutateAsync({
        forwardedTo: FWD,
        dateFileName: DFN,
        fields: { company: "New Co", amount: 99 },
      })
    ).rejects.toBeTruthy();

    const cached = queryClient.getQueryData(["transactions", "2026-02"]) as TxnList;
    expect(cached.transactions[0]?.company).toBe("Old Co"); // restored
    expect(cached.transactions[0]?.amount).toBe(10);
    await waitFor(() => expect(toast.error).toHaveBeenCalledWith("Failed to update transaction"));
  });

  it("restores the exact transactions AND search snapshots on failure", async () => {
    mockFetchError();
    const { result, queryClient } = renderHookWithProviders(() => useUpdateTransactionFields());
    const txn = makeTxn({ forwarded_to: FWD, date_file_name: DFN, company: "Old Co", amount: 10 });
    const txnSnapshot = { transactions: [txn], count: 1 };
    const searchSnapshot = { transactions: [txn], total_matching: 2 };
    queryClient.setQueryData(["transactions", "2026-02"], txnSnapshot);
    queryClient.setQueryData(["transaction-search", { q: "y" }], searchSnapshot);

    await expect(
      result.current.mutateAsync({
        forwardedTo: FWD,
        dateFileName: DFN,
        fields: { company: "New Co", amount: 99 },
      })
    ).rejects.toBeTruthy();

    // Both caches deep-equal their pre-mutation snapshots — including the
    // search rollback loop.
    expect(queryClient.getQueryData(["transactions", "2026-02"])).toEqual(txnSnapshot);
    expect(queryClient.getQueryData(["transaction-search", { q: "y" }])).toEqual(searchSnapshot);
  });

  it("offers an Undo affordance on success", async () => {
    mockFetchJSON({ [FIELDS_URL]: OK_RESPONSE });
    const { result, queryClient } = renderHookWithProviders(() => useUpdateTransactionFields());
    queryClient.setQueryData(["transactions", "2026-02"], {
      transactions: [makeTxn({ forwarded_to: FWD, date_file_name: DFN })],
      count: 1,
    });

    await result.current.mutateAsync({
      forwardedTo: FWD,
      dateFileName: DFN,
      fields: { company: "New Co" },
    });

    await waitFor(() =>
      expect(toast).toHaveBeenCalledWith("Transaction updated", expect.any(Object))
    );
  });

  it("Undo replays the previous field values and re-invalidates", async () => {
    // old_values carries a non-null company, so the Undo onClick rebuilds the
    // { company } patch and PATCHes /fields again, then invalidates dependents.
    mockFetchJSON({
      [FIELDS_URL]: {
        category: null,
        old_values: { company: "Old Co", amount: null, transaction_type: null },
      },
    });
    const { result, queryClient } = renderHookWithProviders(() => useUpdateTransactionFields());
    const invalidate = vi.spyOn(queryClient, "invalidateQueries");
    queryClient.setQueryData(["transactions", "2026-02"], {
      transactions: [makeTxn({ forwarded_to: FWD, date_file_name: DFN })],
      count: 1,
    });

    await result.current.mutateAsync({
      forwardedTo: FWD,
      dateFileName: DFN,
      fields: { company: "New Co" },
    });

    await waitFor(() =>
      expect(toast).toHaveBeenCalledWith("Transaction updated", expect.any(Object))
    );
    const call = (toast as unknown as { mock: { calls: unknown[][] } }).mock.calls.find(
      (c) => c[0] === "Transaction updated"
    );
    const action = (call?.[1] as { action: { onClick: () => void } }).action;
    invalidate.mockClear();
    action.onClick();
    await waitFor(() => expect(invalidate).toHaveBeenCalled());
  });

  it("Undo is a no-op when the server reports no prior values", async () => {
    // Every old_values field is null → oldFields stays empty → the guard skips
    // the replay PATCH entirely (no second fetch, no invalidate).
    const fetchMock = mockFetchJSON({ [FIELDS_URL]: OK_RESPONSE });
    const { result, queryClient } = renderHookWithProviders(() => useUpdateTransactionFields());
    const invalidate = vi.spyOn(queryClient, "invalidateQueries");
    queryClient.setQueryData(["transactions", "2026-02"], {
      transactions: [makeTxn({ forwarded_to: FWD, date_file_name: DFN })],
      count: 1,
    });

    await result.current.mutateAsync({
      forwardedTo: FWD,
      dateFileName: DFN,
      fields: { company: "New Co" },
    });

    await waitFor(() =>
      expect(toast).toHaveBeenCalledWith("Transaction updated", expect.any(Object))
    );
    const call = (toast as unknown as { mock: { calls: unknown[][] } }).mock.calls.find(
      (c) => c[0] === "Transaction updated"
    );
    const action = (call?.[1] as { action: { onClick: () => void } }).action;
    const fetchCallsBefore = fetchMock.mock.calls.length;
    invalidate.mockClear();
    action.onClick();
    // Guard short-circuits: no replay PATCH, no invalidate.
    expect(fetchMock.mock.calls.length).toBe(fetchCallsBefore);
    expect(invalidate).not.toHaveBeenCalled();
  });
});
