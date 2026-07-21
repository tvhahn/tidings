import { afterEach, beforeEach, describe, expect, it, vi } from "vitest";
import { useLinkAttachment } from "@/hooks/useLinkAttachment";
import { mockFetchJSON } from "@/test/api-mock";
import { renderHookWithProviders } from "@/test/render";

const ATT_ID = "att_0123456789abcdef";
const LINK_URL = `/api/v1/attachments/${ATT_ID}/link`;

beforeEach(() => vi.clearAllMocks());
afterEach(() => vi.unstubAllGlobals());

describe("useLinkAttachment", () => {
  it("invalidates both attachment prefixes and not transaction-dependent ones", async () => {
    mockFetchJSON({ [LINK_URL]: { id: ATT_ID, tx_id: "tx1" } });
    const { result, queryClient } = renderHookWithProviders(() => useLinkAttachment());
    const spy = vi.spyOn(queryClient, "invalidateQueries");

    await result.current.mutateAsync({ id: ATT_ID, txId: "tx1" });

    const invalidatedKeys = spy.mock.calls.map((c) => c[0]?.queryKey);
    expect(invalidatedKeys).toContainEqual(["attachments"]);
    expect(invalidatedKeys).toContainEqual(["unlinkedAttachments"]);
    // A link resolves a receipt's candidate set — refetch it so undo/relink
    // reflects the row's new state.
    expect(invalidatedKeys).toContainEqual(["receiptCandidates"]);
    // Linking a receipt flips its row's tax-pack evidence to "receipt" (L15),
    // so the tax pack must refresh.
    expect(invalidatedKeys).toContainEqual(["tax-pack"]);
    // Linking a file changes no transaction data (L15) — the monthly
    // transaction views must not be invalidated.
    expect(invalidatedKeys).not.toContainEqual(["transactions"]);
  });

  it("passes tx_id: null to unlink", async () => {
    const fetchMock = mockFetchJSON({ [LINK_URL]: { id: ATT_ID, tx_id: null } });
    const { result } = renderHookWithProviders(() => useLinkAttachment());

    await result.current.mutateAsync({ id: ATT_ID, txId: null });

    const init = fetchMock.mock.calls.at(-1)?.[1] as RequestInit;
    expect(JSON.parse(init.body as string)).toEqual({ tx_id: null });
  });
});
