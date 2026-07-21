import { afterEach, beforeEach, describe, expect, it, vi } from "vitest";
import { useParseReceipt } from "@/hooks/useParseReceipt";
import { mockFetchJSON } from "@/test/api-mock";
import { renderHookWithProviders } from "@/test/render";

const ATT_ID = "att_0123456789abcdef";
const PARSE_URL = `/api/v1/attachments/${ATT_ID}/parse`;

beforeEach(() => vi.clearAllMocks());
afterEach(() => vi.unstubAllGlobals());

describe("useParseReceipt", () => {
  it("invalidates attachment + candidate prefixes, not transaction-dependent ones", async () => {
    mockFetchJSON({ [PARSE_URL]: { id: ATT_ID, parse_status: "parsed" } });
    const { result, queryClient } = renderHookWithProviders(() => useParseReceipt());
    const spy = vi.spyOn(queryClient, "invalidateQueries");

    await result.current.mutateAsync(ATT_ID);

    const invalidatedKeys = spy.mock.calls.map((c) => c[0]?.queryKey);
    expect(invalidatedKeys).toContainEqual(["attachments"]);
    expect(invalidatedKeys).toContainEqual(["unlinkedAttachments"]);
    expect(invalidatedKeys).toContainEqual(["receiptCandidates"]);
    // Parsing enriches only the attachment row (L15) — monthly transaction
    // views must not be invalidated.
    expect(invalidatedKeys).not.toContainEqual(["transactions"]);
  });
});
