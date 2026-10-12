import { waitFor } from "@testing-library/react";
import { toast } from "sonner";
import { afterEach, beforeEach, describe, expect, it, vi } from "vitest";
import { useMarkReviewed } from "@/hooks/useMarkReviewed";
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
const REVIEW_URL = `/api/v1/transactions/${txIdFromComposite(FWD, DFN)}/review`;

type TxnList = { transactions: ReturnType<typeof makeTxn>[]; count: number };

beforeEach(() => vi.clearAllMocks());
afterEach(() => vi.unstubAllGlobals());

describe("useMarkReviewed", () => {
  it("optimistically drops the row from attention and stamps a manual review", async () => {
    const pending = pendingResponse();
    mockFetchJSON({ [REVIEW_URL]: pending.responder });
    const { result, queryClient } = renderHookWithProviders(() => useMarkReviewed());
    const txn = makeTxn({
      forwarded_to: FWD,
      date_file_name: DFN,
      category: "miscellaneous",
      category_audit: null,
    });
    queryClient.setQueryData(["attention", "2026-02"], { transactions: [txn], count: 1 });
    queryClient.setQueryData(
      ["transactions-combined", "2026-02"],
      makeCombined({ transactions: [txn], attention: [txn] })
    );

    result.current.mutate({ forwardedTo: FWD, dateFileName: DFN });

    await waitFor(() => {
      const combined = queryClient.getQueryData(["transactions-combined", "2026-02"]) as Combined;
      expect(combined.attention.count).toBe(0);
    });
    const combined = queryClient.getQueryData(["transactions-combined", "2026-02"]) as Combined;
    expect(combined.attention.transactions).toEqual([]);
    expect(combined.transactions.count).toBe(1);
    expect(combined.transactions.transactions[0]?.category_audit?.source).toBe("manual");
    const attention = queryClient.getQueryData(["attention", "2026-02"]) as TxnList;
    expect(attention.transactions).toEqual([]);

    pending.release();
    await waitFor(() => expect(toast).toHaveBeenCalledWith("Category confirmed"));
  });

  it("restores the exact combined and attention snapshots and toasts on failure", async () => {
    mockFetchError();
    const { result, queryClient } = renderHookWithProviders(() => useMarkReviewed());
    const txn = makeTxn({ forwarded_to: FWD, date_file_name: DFN, category: "miscellaneous" });
    const attentionSnapshot = { transactions: [txn], count: 1 };
    const combinedSnapshot = makeCombined({ transactions: [txn], attention: [txn] });
    queryClient.setQueryData(["attention", "2026-02"], attentionSnapshot);
    queryClient.setQueryData(["transactions-combined", "2026-02"], combinedSnapshot);

    await expect(
      result.current.mutateAsync({ forwardedTo: FWD, dateFileName: DFN })
    ).rejects.toBeTruthy();

    expect(queryClient.getQueryData(["transactions-combined", "2026-02"])).toEqual(
      combinedSnapshot
    );
    expect(queryClient.getQueryData(["attention", "2026-02"])).toEqual(attentionSnapshot);
    await waitFor(() => expect(toast.error).toHaveBeenCalledWith("Failed to confirm category"));
  });
});
