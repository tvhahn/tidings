import { waitFor } from "@testing-library/react";
import { toast } from "sonner";
import { beforeEach, describe, expect, it, vi } from "vitest";
import { useDismissParseFailure } from "@/hooks/useDismissParseFailure";
import { useRetryParseFailure } from "@/hooks/useRetryParseFailure";
import { mockFetchJSON } from "@/test/api-mock";
import { renderHookWithProviders } from "@/test/render";

// Capture sonner toast calls without rendering the portal-based Toaster.
// vitest hoists vi.mock above the imports, so the mock is registered first.
vi.mock("sonner", () => {
  const mockToast = Object.assign(vi.fn(), { success: vi.fn(), error: vi.fn() });
  return { toast: mockToast };
});

const RETRY_URL = "/api/v1/parse-failures/pf1/retry";
const DISMISS_URL = "/api/v1/parse-failures/pf1";

beforeEach(() => {
  vi.clearAllMocks();
});

describe("useRetryParseFailure — the three outcomes", () => {
  it("created → success toast", async () => {
    mockFetchJSON({ [RETRY_URL]: { failure_id: "pf1", status: "created", date_file_name: "d" } });
    const { result } = renderHookWithProviders(() => useRetryParseFailure());
    await result.current.mutateAsync("pf1");
    await waitFor(() =>
      expect(toast.success).toHaveBeenCalledWith("Recorded — added to your transactions")
    );
    expect(toast.error).not.toHaveBeenCalled();
  });

  it("duplicate → already-recorded toast", async () => {
    mockFetchJSON({ [RETRY_URL]: { failure_id: "pf1", status: "duplicate" } });
    const { result } = renderHookWithProviders(() => useRetryParseFailure());
    await result.current.mutateAsync("pf1");
    await waitFor(() => expect(toast).toHaveBeenCalledWith("Already recorded"));
    expect(toast.error).not.toHaveBeenCalled();
  });

  it("still_failing → calm retry-later toast, never an error toast", async () => {
    mockFetchJSON({ [RETRY_URL]: { failure_id: "pf1", status: "still_failing" } });
    const { result } = renderHookWithProviders(() => useRetryParseFailure());
    await result.current.mutateAsync("pf1");
    await waitFor(() =>
      expect(toast).toHaveBeenCalledWith(
        "Still can't read this one — try again after a parser update"
      )
    );
    expect(toast.success).not.toHaveBeenCalled();
    expect(toast.error).not.toHaveBeenCalled();
  });
});

describe("useDismissParseFailure", () => {
  it("set aside → confirmation toast with no fake Undo action", async () => {
    mockFetchJSON({ [DISMISS_URL]: { failure_id: "pf1", status: "dismissed" } });
    const { result } = renderHookWithProviders(() => useDismissParseFailure());
    await result.current.mutateAsync("pf1");
    await waitFor(() => expect(toast).toHaveBeenCalledWith("Email set aside"));
    // A second arg would carry a toast action; there is no un-dismiss endpoint,
    // so there must be no Undo affordance.
    const mockToast = toast as unknown as { mock: { calls: unknown[][] } };
    const call = mockToast.mock.calls.find((c) => c[0] === "Email set aside");
    expect(call?.[1]).toBeUndefined();
  });
});
