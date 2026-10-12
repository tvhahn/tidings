import { waitFor } from "@testing-library/react";
import { toast } from "sonner";
import { afterEach, beforeEach, describe, expect, it, vi } from "vitest";
import { useIgnoreTransaction } from "@/hooks/useIgnoreTransaction";
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
const IGNORE_URL = `/api/v1/transactions/${txIdFromComposite(FWD, DFN)}/ignore`;

type TxnList = { transactions: ReturnType<typeof makeTxn>[]; count: number };

beforeEach(() => vi.clearAllMocks());
afterEach(() => vi.unstubAllGlobals());

describe("useIgnoreTransaction", () => {
  it("optimistically flips the ignored flag in the cache", async () => {
    mockFetchJSON({ [IGNORE_URL]: {} });
    const { result, queryClient } = renderHookWithProviders(() => useIgnoreTransaction());
    queryClient.setQueryData(["transactions", "2026-02"], {
      transactions: [makeTxn({ forwarded_to: FWD, date_file_name: DFN, ignored: false })],
      count: 1,
    });

    await result.current.mutateAsync({ forwardedTo: FWD, dateFileName: DFN, ignored: true });

    const cached = queryClient.getQueryData(["transactions", "2026-02"]) as TxnList;
    expect(cached.transactions[0]?.ignored).toBe(true);
  });

  it("rolls back and toasts on failure", async () => {
    mockFetchError();
    const { result, queryClient } = renderHookWithProviders(() => useIgnoreTransaction());
    queryClient.setQueryData(["transactions", "2026-02"], {
      transactions: [makeTxn({ forwarded_to: FWD, date_file_name: DFN, ignored: false })],
      count: 1,
    });

    await expect(
      result.current.mutateAsync({ forwardedTo: FWD, dateFileName: DFN, ignored: true })
    ).rejects.toBeTruthy();

    const cached = queryClient.getQueryData(["transactions", "2026-02"]) as TxnList;
    expect(cached.transactions[0]?.ignored).toBe(false); // restored
    await waitFor(() => expect(toast.error).toHaveBeenCalledWith("Failed to update transaction"));
  });

  it("optimistically flips the flag in the combined cache and drops the row from attention", async () => {
    const pending = pendingResponse();
    mockFetchJSON({ [IGNORE_URL]: pending.responder });
    const { result, queryClient } = renderHookWithProviders(() => useIgnoreTransaction());
    const txn = makeTxn({ forwarded_to: FWD, date_file_name: DFN, ignored: false });
    queryClient.setQueryData(
      ["transactions-combined", "2026-02"],
      makeCombined({ transactions: [txn], attention: [txn] })
    );

    result.current.mutate({ forwardedTo: FWD, dateFileName: DFN, ignored: true });

    // Before the server answers, the visible row is already ignored.
    await waitFor(() => {
      const combined = queryClient.getQueryData(["transactions-combined", "2026-02"]) as Combined;
      expect(combined.transactions.transactions[0]?.ignored).toBe(true);
    });
    const combined = queryClient.getQueryData(["transactions-combined", "2026-02"]) as Combined;
    expect(combined.transactions.count).toBe(1); // ignored rows stay in the list
    expect(combined.attention.transactions).toEqual([]);
    expect(combined.attention.count).toBe(0);

    pending.release();
    await waitFor(() => expect(result.current.isSuccess).toBe(true));
  });

  it("un-ignoring clears the flag without touching attention", async () => {
    mockFetchJSON({ [IGNORE_URL]: {} });
    const { result, queryClient } = renderHookWithProviders(() => useIgnoreTransaction());
    const txn = makeTxn({ forwarded_to: FWD, date_file_name: DFN, ignored: true });
    queryClient.setQueryData(
      ["transactions-combined", "2026-02"],
      makeCombined({ transactions: [txn] })
    );

    await result.current.mutateAsync({ forwardedTo: FWD, dateFileName: DFN, ignored: false });

    const combined = queryClient.getQueryData(["transactions-combined", "2026-02"]) as Combined;
    expect(combined.transactions.transactions[0]?.ignored).toBe(false);
    expect(combined.attention.count).toBe(0);
  });

  it("restores the exact combined snapshot on failure", async () => {
    mockFetchError();
    const { result, queryClient } = renderHookWithProviders(() => useIgnoreTransaction());
    const txn = makeTxn({ forwarded_to: FWD, date_file_name: DFN, ignored: false });
    const snapshot = makeCombined({ transactions: [txn], attention: [txn] });
    queryClient.setQueryData(["transactions-combined", "2026-02"], snapshot);

    await expect(
      result.current.mutateAsync({ forwardedTo: FWD, dateFileName: DFN, ignored: true })
    ).rejects.toBeTruthy();

    expect(queryClient.getQueryData(["transactions-combined", "2026-02"])).toEqual(snapshot);
  });

  it("labels the success toast by direction", async () => {
    mockFetchJSON({ [IGNORE_URL]: {} });
    const { result, queryClient } = renderHookWithProviders(() => useIgnoreTransaction());
    queryClient.setQueryData(["transactions", "2026-02"], {
      transactions: [makeTxn({ forwarded_to: FWD, date_file_name: DFN })],
      count: 1,
    });

    await result.current.mutateAsync({ forwardedTo: FWD, dateFileName: DFN, ignored: true });

    await waitFor(() =>
      expect(toast).toHaveBeenCalledWith("Transaction ignored", expect.any(Object))
    );
  });
});
