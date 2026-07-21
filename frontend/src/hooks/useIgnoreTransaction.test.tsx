import { waitFor } from "@testing-library/react";
import { toast } from "sonner";
import { afterEach, beforeEach, describe, expect, it, vi } from "vitest";
import { useIgnoreTransaction } from "@/hooks/useIgnoreTransaction";
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
