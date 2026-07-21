import { afterEach, describe, expect, it, vi } from "vitest";
import {
  AUTH_REQUIRED_EVENT,
  clearTaxOverride,
  deleteCategory,
  fetchBudgetConfig,
  fetchTransactions,
  loginWithPassword,
  setAppPassword,
  updateBudgetConfig,
} from "@/lib/api";
import { ApiError } from "@/lib/apiError";

// Covers the shared request-helper contract in api.ts: every site now funnels
// through fetchJSON/postFormData/downloadFile, so these tests pin the behaviors
// consumers depend on — the `.status`/409 branch, the 404 empty-state, the
// 204/empty-body writes, and the 401 auth-event policy.

function makeRes(status: number, body?: unknown): Response {
  const text = body === undefined ? "" : JSON.stringify(body);
  return {
    ok: status >= 200 && status < 300,
    status,
    statusText: "",
    json: async () => (text ? JSON.parse(text) : {}),
    text: async () => text,
  } as unknown as Response;
}

function mockFetch(res: Response) {
  return vi.spyOn(globalThis, "fetch").mockResolvedValue(res);
}

afterEach(() => vi.restoreAllMocks());

describe("api request helpers", () => {
  it("returns null on 404 for allow404 endpoints (empty state, not error)", async () => {
    mockFetch(makeRes(404, { error: "not found" }));
    await expect(fetchBudgetConfig(2026)).resolves.toBeNull();
  });

  it("resolves a void write on a 204 with no body", async () => {
    mockFetch(makeRes(204));
    await expect(clearTaxOverride("tx-1")).resolves.toBeUndefined();
  });

  it("throws ApiError carrying .status and the backend envelope message", async () => {
    mockFetch(makeRes(409, { error: "category still in use", code: "CONFLICT" }));
    const err = await deleteCategory("Food").catch((e: unknown) => e);
    expect(err).toBeInstanceOf(ApiError);
    expect(err).toMatchObject({ status: 409, code: "CONFLICT", message: "category still in use" });
  });

  it("preserves .status === 409 for the multi-tab budget conflict UX", async () => {
    mockFetch(makeRes(409, { error: "modified elsewhere" }));
    const err = await updateBudgetConfig(
      2026,
      {} as unknown as Parameters<typeof updateBudgetConfig>[1]
    ).catch((e: unknown) => e);
    expect(err).toBeInstanceOf(ApiError);
    expect((err as ApiError).status).toBe(409);
  });

  it("dispatches AUTH_REQUIRED on a bare 401", async () => {
    mockFetch(makeRes(401, { error: "unauthorized" }));
    const spy = vi.fn();
    window.addEventListener(AUTH_REQUIRED_EVENT, spy);
    await fetchTransactions("2026-03").catch(() => {});
    window.removeEventListener(AUTH_REQUIRED_EVENT, spy);
    expect(spy).toHaveBeenCalledOnce();
  });

  it("does not eject the session when set-password answers 401 (skipAuthEvent)", async () => {
    mockFetch(makeRes(401, { error: "current password is required and must match" }));
    const spy = vi.fn();
    window.addEventListener(AUTH_REQUIRED_EVENT, spy);
    const err = await setAppPassword({ password: "abcdefgh", current_password: "wrong" }).catch(
      (e: unknown) => e
    );
    window.removeEventListener(AUTH_REQUIRED_EVENT, spy);
    expect(spy).not.toHaveBeenCalled();
    expect((err as ApiError).message).toBe("current password is required and must match");
  });

  it("surfaces the login envelope message without ejecting the session", async () => {
    mockFetch(makeRes(401, { error: "invalid password" }));
    const spy = vi.fn();
    window.addEventListener(AUTH_REQUIRED_EVENT, spy);
    const err = await loginWithPassword("nope").catch((e: unknown) => e);
    window.removeEventListener(AUTH_REQUIRED_EVENT, spy);
    expect(spy).not.toHaveBeenCalled();
    expect((err as ApiError).message).toBe("invalid password");
  });
});
