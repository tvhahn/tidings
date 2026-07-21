import { waitFor } from "@testing-library/react";
import { afterEach, beforeEach, describe, expect, it, vi } from "vitest";
import {
  useAddIgnoreRule,
  useApplyIgnoreRules,
  useDismissIgnoreRuleSuggestion,
  useIgnoreRuleDismissedSuggestions,
  useIgnoreRules,
  useUndismissIgnoreRuleSuggestion,
} from "@/hooks/useIgnoreRules";
import { mockFetchJSON } from "@/test/api-mock";
import { renderHookWithProviders } from "@/test/render";

const RULES_URL = "/api/v1/ignore-rules";
const APPLY_URL = "/api/v1/ignore-rules/apply";
const DISMISS_URL = "/api/v1/ignore-rules/suggestions/dismissed";

beforeEach(() => vi.clearAllMocks());
afterEach(() => vi.unstubAllGlobals());

describe("useIgnoreRules", () => {
  it("fetches the rule list", async () => {
    mockFetchJSON({
      [RULES_URL]: { rules: [{ pattern: "MAPLETRADE INC." }], count: 1, version: 2 },
    });
    const { result } = renderHookWithProviders(() => useIgnoreRules());
    await waitFor(() => expect(result.current.isSuccess).toBe(true));
    expect(result.current.data?.count).toBe(1);
    expect(result.current.data?.rules[0]?.pattern).toBe("MAPLETRADE INC.");
  });
});

describe("useAddIgnoreRule", () => {
  it("posts the pattern and invalidates the rule + suggestion queries", async () => {
    mockFetchJSON({
      [RULES_URL]: (init?: RequestInit) => {
        expect(init?.method).toBe("POST");
        return { rules: [{ pattern: "MAPLETRADE INC." }], count: 1, version: 1 };
      },
    });
    const { result, queryClient } = renderHookWithProviders(() => useAddIgnoreRule());
    const spy = vi.spyOn(queryClient, "invalidateQueries");

    await result.current.mutateAsync("MAPLETRADE INC.");

    expect(spy).toHaveBeenCalledWith({ queryKey: ["ignoreRules"] });
    expect(spy).toHaveBeenCalledWith({ queryKey: ["ignoreRuleSuggestions"] });
  });
});

describe("useApplyIgnoreRules", () => {
  it("returns backfill counts and invalidates transaction-dependent views", async () => {
    mockFetchJSON({
      [APPLY_URL]: {
        results: [{ pattern: "MAPLETRADE INC.", matched: 12, updated: 12 }],
        total_matched: 12,
        total_updated: 12,
      },
    });
    const { result, queryClient } = renderHookWithProviders(() => useApplyIgnoreRules());
    const spy = vi.spyOn(queryClient, "invalidateQueries");

    const res = await result.current.mutateAsync("MAPLETRADE INC.");
    expect(res.total_updated).toBe(12);
    // invalidateTransactionDependents fans out over the transaction prefixes.
    expect(spy).toHaveBeenCalledWith(expect.objectContaining({ queryKey: ["transactions"] }));
    expect(spy).toHaveBeenCalledWith(expect.objectContaining({ queryKey: ["summary"] }));
  });
});

describe("useDismissIgnoreRuleSuggestion", () => {
  it("posts the merchant and invalidates the suggestion + dismissed queries", async () => {
    const fetchMock = mockFetchJSON({
      [DISMISS_URL]: (init?: RequestInit) => {
        expect(init?.method).toBe("POST");
        expect(JSON.parse(String(init?.body))).toEqual({ merchant: "MiscPayment CARDCO" });
        return {};
      },
    });
    const { result, queryClient } = renderHookWithProviders(() => useDismissIgnoreRuleSuggestion());
    const spy = vi.spyOn(queryClient, "invalidateQueries");

    await result.current.mutateAsync("MiscPayment CARDCO");

    expect(fetchMock).toHaveBeenCalled();
    expect(spy).toHaveBeenCalledWith({ queryKey: ["ignoreRuleSuggestions"] });
    expect(spy).toHaveBeenCalledWith({ queryKey: ["ignoreRuleDismissed"] });
  });
});

describe("useIgnoreRuleDismissedSuggestions", () => {
  it("fetches the dismissed suggestion list", async () => {
    mockFetchJSON({
      [DISMISS_URL]: {
        dismissed: [{ merchant: "MiscPayment CARDCO", dismissed_at: "2026-07-16T00:00:00+00:00" }],
        count: 1,
      },
    });
    const { result } = renderHookWithProviders(() => useIgnoreRuleDismissedSuggestions());
    await waitFor(() => expect(result.current.isSuccess).toBe(true));
    expect(result.current.data?.count).toBe(1);
    expect(result.current.data?.dismissed[0]?.merchant).toBe("MiscPayment CARDCO");
  });
});

describe("useUndismissIgnoreRuleSuggestion", () => {
  it("deletes the dismissal and invalidates the suggestion + dismissed queries", async () => {
    const fetchMock = mockFetchJSON({
      [`${DISMISS_URL}/MiscPayment%20CARDCO`]: (init?: RequestInit) => {
        expect(init?.method).toBe("DELETE");
        return {};
      },
    });
    const { result, queryClient } = renderHookWithProviders(() =>
      useUndismissIgnoreRuleSuggestion()
    );
    const spy = vi.spyOn(queryClient, "invalidateQueries");

    await result.current.mutateAsync("MiscPayment CARDCO");

    expect(fetchMock).toHaveBeenCalled();
    expect(spy).toHaveBeenCalledWith({ queryKey: ["ignoreRuleSuggestions"] });
    expect(spy).toHaveBeenCalledWith({ queryKey: ["ignoreRuleDismissed"] });
  });
});
