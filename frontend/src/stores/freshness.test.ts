import { beforeEach, describe, expect, it, vi } from "vitest";

async function freshStore() {
  vi.resetModules();
  const mod = await import("./freshness");
  return mod.useFreshness;
}

describe("freshness store", () => {
  beforeEach(() => {
    vi.resetModules();
  });

  it("starts with null state and zero pulseToken", async () => {
    const useFreshness = await freshStore();
    const s = useFreshness.getState();
    expect(s.lastSyncAt).toBeNull();
    expect(s.lastLatest).toBeNull();
    expect(s.isPolling).toBe(false);
    expect(s.pulseToken).toBe(0);
  });

  it("setSync stamps lastSyncAt and stores lastLatest", async () => {
    const useFreshness = await freshStore();
    const before = Date.now();
    useFreshness.getState().setSync("2026.04.28_12.00_test.eml", false);
    const s = useFreshness.getState();
    expect(s.lastLatest).toBe("2026.04.28_12.00_test.eml");
    expect(s.lastSyncAt).toBeGreaterThanOrEqual(before);
  });

  it("setSync increments pulseToken when pulsed=true", async () => {
    const useFreshness = await freshStore();
    expect(useFreshness.getState().pulseToken).toBe(0);
    useFreshness.getState().setSync("a", true);
    expect(useFreshness.getState().pulseToken).toBe(1);
    useFreshness.getState().setSync("b", true);
    expect(useFreshness.getState().pulseToken).toBe(2);
  });

  it("setSync does not increment pulseToken when pulsed=false", async () => {
    const useFreshness = await freshStore();
    useFreshness.getState().setSync("a", true);
    const token = useFreshness.getState().pulseToken;
    useFreshness.getState().setSync("a", false);
    expect(useFreshness.getState().pulseToken).toBe(token);
  });

  it("setPolling toggles the polling flag", async () => {
    const useFreshness = await freshStore();
    useFreshness.getState().setPolling(true);
    expect(useFreshness.getState().isPolling).toBe(true);
    useFreshness.getState().setPolling(false);
    expect(useFreshness.getState().isPolling).toBe(false);
  });
});
