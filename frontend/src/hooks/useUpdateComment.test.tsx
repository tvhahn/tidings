import { waitFor } from "@testing-library/react";
import { toast } from "sonner";
import { afterEach, beforeEach, describe, expect, it, vi } from "vitest";
import { useUpdateComment } from "@/hooks/useUpdateComment";
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
const COMMENT_URL = `/api/v1/transactions/${txIdFromComposite(FWD, DFN)}/comment`;

type TxnList = { transactions: ReturnType<typeof makeTxn>[]; count: number };
type Journal = { days: { date: string; transactions: ReturnType<typeof makeTxn>[] }[] };

beforeEach(() => vi.clearAllMocks());
afterEach(() => vi.unstubAllGlobals());

describe("useUpdateComment", () => {
  it("optimistically writes the comment into the transactions and journal caches", async () => {
    mockFetchJSON({ [COMMENT_URL]: {} });
    const { result, queryClient } = renderHookWithProviders(() => useUpdateComment());
    queryClient.setQueryData(["transactions", "2026-02"], {
      transactions: [makeTxn({ forwarded_to: FWD, date_file_name: DFN, comment: null })],
      count: 1,
    });
    queryClient.setQueryData(["journal", "2026-02"], {
      days: [
        { date: "2026-02-01", transactions: [makeTxn({ forwarded_to: FWD, date_file_name: DFN })] },
      ],
    });

    await result.current.mutateAsync({ forwardedTo: FWD, dateFileName: DFN, comment: "hi there" });

    const txns = queryClient.getQueryData(["transactions", "2026-02"]) as TxnList;
    expect(txns.transactions[0]?.comment).toBe("hi there");
    const journal = queryClient.getQueryData(["journal", "2026-02"]) as Journal;
    expect(journal.days[0]?.transactions[0]?.comment).toBe("hi there");
  });

  it("rolls back and toasts on failure", async () => {
    mockFetchError();
    const { result, queryClient } = renderHookWithProviders(() => useUpdateComment());
    queryClient.setQueryData(["transactions", "2026-02"], {
      transactions: [makeTxn({ forwarded_to: FWD, date_file_name: DFN, comment: null })],
      count: 1,
    });

    await expect(
      result.current.mutateAsync({ forwardedTo: FWD, dateFileName: DFN, comment: "hi" })
    ).rejects.toBeTruthy();

    const txns = queryClient.getQueryData(["transactions", "2026-02"]) as TxnList;
    expect(txns.transactions[0]?.comment).toBeNull(); // restored
    await waitFor(() => expect(toast.error).toHaveBeenCalledWith("Failed to save note"));
  });

  it("toasts 'Note cleared' when the comment is emptied", async () => {
    mockFetchJSON({ [COMMENT_URL]: {} });
    const { result, queryClient } = renderHookWithProviders(() => useUpdateComment());
    queryClient.setQueryData(["transactions", "2026-02"], {
      transactions: [makeTxn({ forwarded_to: FWD, date_file_name: DFN, comment: "old" })],
      count: 1,
    });

    await result.current.mutateAsync({ forwardedTo: FWD, dateFileName: DFN, comment: null });

    await waitFor(() => expect(toast).toHaveBeenCalledWith("Note cleared"));
  });
});
