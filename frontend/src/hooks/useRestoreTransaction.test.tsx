import { waitFor } from "@testing-library/react";
import { toast } from "sonner";
import { afterEach, beforeEach, describe, expect, it, vi } from "vitest";
import { useRestoreTransaction } from "@/hooks/useRestoreTransaction";
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
// Restore reuses the soft-delete endpoint with `deleted: false`.
const DELETE_URL = `/api/v1/transactions/${txIdFromComposite(FWD, DFN)}/delete`;
const DELETED_AT = "2026-02-25T12:00:00+00:00";

type TxnList = { transactions: ReturnType<typeof makeTxn>[]; count: number };

beforeEach(() => vi.clearAllMocks());
afterEach(() => vi.unstubAllGlobals());

describe("useRestoreTransaction", () => {
  it("optimistically moves the row from trash back into the combined transactions", async () => {
    const pending = pendingResponse();
    mockFetchJSON({ [DELETE_URL]: pending.responder });
    const { result, queryClient } = renderHookWithProviders(() => useRestoreTransaction());
    const trashed = makeTxn({ forwarded_to: FWD, date_file_name: DFN, deleted_at: DELETED_AT });
    queryClient.setQueryData(["trash", "2026-02"], { transactions: [trashed], count: 1 });
    queryClient.setQueryData(
      ["transactions-combined", "2026-02"],
      makeCombined({ trash: [trashed] })
    );

    result.current.mutate({ forwardedTo: FWD, dateFileName: DFN });

    await waitFor(() => {
      const combined = queryClient.getQueryData(["transactions-combined", "2026-02"]) as Combined;
      expect(combined.trash.count).toBe(0);
    });
    const combined = queryClient.getQueryData(["transactions-combined", "2026-02"]) as Combined;
    expect(combined.trash.transactions).toEqual([]);
    expect(combined.transactions.count).toBe(1);
    expect(combined.transactions.transactions[0]?.deleted_at).toBeNull();
    const trash = queryClient.getQueryData(["trash", "2026-02"]) as TxnList;
    expect(trash.transactions).toEqual([]);

    pending.release();
    await waitFor(() => expect(toast).toHaveBeenCalledWith("Transaction restored"));
  });

  it("restores the exact combined and trash snapshots and toasts on failure", async () => {
    mockFetchError();
    const { result, queryClient } = renderHookWithProviders(() => useRestoreTransaction());
    const trashed = makeTxn({ forwarded_to: FWD, date_file_name: DFN, deleted_at: DELETED_AT });
    const trashSnapshot = { transactions: [trashed], count: 1 };
    const combinedSnapshot = makeCombined({ trash: [trashed] });
    queryClient.setQueryData(["trash", "2026-02"], trashSnapshot);
    queryClient.setQueryData(["transactions-combined", "2026-02"], combinedSnapshot);

    await expect(
      result.current.mutateAsync({ forwardedTo: FWD, dateFileName: DFN })
    ).rejects.toBeTruthy();

    expect(queryClient.getQueryData(["transactions-combined", "2026-02"])).toEqual(
      combinedSnapshot
    );
    expect(queryClient.getQueryData(["trash", "2026-02"])).toEqual(trashSnapshot);
    await waitFor(() => expect(toast.error).toHaveBeenCalledWith("Failed to restore transaction"));
  });
});
