import { waitFor } from "@testing-library/react";
import { toast } from "sonner";
import { afterEach, beforeEach, describe, expect, it, vi } from "vitest";
import { useResolveParseFailure } from "@/hooks/useResolveParseFailure";
import { mockFetchJSON } from "@/test/api-mock";
import { renderHookWithProviders } from "@/test/render";
import type { ManualResolveRequest } from "@/types/api";

// Capture sonner toast calls without rendering the portal-based Toaster.
vi.mock("sonner", () => {
  const mockToast = Object.assign(vi.fn(), { success: vi.fn(), error: vi.fn() });
  return { toast: mockToast };
});

const RESOLVE_URL = "/api/v1/parse-failures/pf1/resolve";
const BODY: ManualResolveRequest = {
  date: "2026-06-21",
  amount: 12.5,
  company: "Corner Market",
  category: "groceries",
  transaction_type: "purchase",
};

beforeEach(() => {
  vi.clearAllMocks();
});

afterEach(() => {
  vi.unstubAllGlobals();
});

describe("useResolveParseFailure — the manual-entry outcomes", () => {
  it("created → success toast reused verbatim from retry", async () => {
    mockFetchJSON({ [RESOLVE_URL]: { failure_id: "pf1", status: "created", date_file_name: "d" } });
    const { result } = renderHookWithProviders(() => useResolveParseFailure());
    await result.current.mutateAsync({ id: "pf1", body: BODY });
    await waitFor(() =>
      expect(toast.success).toHaveBeenCalledWith("Recorded — added to your transactions")
    );
    expect(toast.error).not.toHaveBeenCalled();
  });

  it("created → refreshes the queue and the transaction-dependent views", async () => {
    // The factory's onSettled owns the refresh contract: the resolved row must
    // leave "Needs review" (parse-failures prefix) AND the new transaction must
    // appear on Journal/Transactions/attention (invalidateTransactionDependents).
    // A regression dropping either invalidation would otherwise pass every
    // toast-only assertion, so spy on the shared client directly.
    mockFetchJSON({ [RESOLVE_URL]: { failure_id: "pf1", status: "created", date_file_name: "d" } });
    const { result, queryClient } = renderHookWithProviders(() => useResolveParseFailure());
    const invalidate = vi.spyOn(queryClient, "invalidateQueries");
    await result.current.mutateAsync({ id: "pf1", body: BODY });
    await waitFor(() => {
      expect(invalidate).toHaveBeenCalledWith({ queryKey: ["parse-failures"] });
      expect(invalidate).toHaveBeenCalledWith(
        expect.objectContaining({ queryKey: ["transactions"] })
      );
      expect(invalidate).toHaveBeenCalledWith(expect.objectContaining({ queryKey: ["journal"] }));
    });
  });

  it("duplicate → already-recorded toast", async () => {
    mockFetchJSON({ [RESOLVE_URL]: { failure_id: "pf1", status: "duplicate" } });
    const { result } = renderHookWithProviders(() => useResolveParseFailure());
    await result.current.mutateAsync({ id: "pf1", body: BODY });
    await waitFor(() => expect(toast).toHaveBeenCalledWith("Already recorded"));
    expect(toast.success).not.toHaveBeenCalled();
    expect(toast.error).not.toHaveBeenCalled();
  });

  it("422 → calm, specific error toast pointing at the likely culprits", async () => {
    // mockFetchJSON only ever returns 200, so stub a 422 directly with the
    // backend's unified {error, code} body that fetchJSON turns into ApiError.
    vi.stubGlobal(
      "fetch",
      vi.fn(
        async () =>
          new Response(
            JSON.stringify({
              error: "Could not store transaction — check the values",
              code: "HTTP_422",
            }),
            { status: 422, headers: { "Content-Type": "application/json" } }
          )
      )
    );
    const { result } = renderHookWithProviders(() => useResolveParseFailure());
    await expect(result.current.mutateAsync({ id: "pf1", body: BODY })).rejects.toThrow();
    await waitFor(() =>
      expect(toast.error).toHaveBeenCalledWith(
        "Couldn't save those details — check the amount and company"
      )
    );
    expect(toast.success).not.toHaveBeenCalled();
  });
});
