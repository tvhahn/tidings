import { beforeEach, describe, expect, it, vi } from "vitest";

async function freshStore() {
  vi.resetModules();
  const mod = await import("./preferences");
  return mod.usePreferences;
}

describe("preferences store", () => {
  beforeEach(() => {
    localStorage.clear();
    vi.resetModules();
  });

  it("defaults to medium when localStorage is empty", async () => {
    const usePreferences = await freshStore();
    expect(usePreferences.getState().dateFormat).toBe("medium");
  });

  it("loads a saved date format from localStorage", async () => {
    localStorage.setItem("pref.dateFormat", "iso");
    const usePreferences = await freshStore();
    expect(usePreferences.getState().dateFormat).toBe("iso");
  });

  it("falls back to medium when localStorage has an unknown id", async () => {
    localStorage.setItem("pref.dateFormat", "not-a-format");
    const usePreferences = await freshStore();
    expect(usePreferences.getState().dateFormat).toBe("medium");
  });

  it("setDateFormat persists to localStorage", async () => {
    const usePreferences = await freshStore();
    usePreferences.getState().setDateFormat("dmy");
    expect(usePreferences.getState().dateFormat).toBe("dmy");
    expect(localStorage.getItem("pref.dateFormat")).toBe("dmy");
  });

  it("setDateFormat ignores unknown formats", async () => {
    const usePreferences = await freshStore();
    usePreferences.getState().setDateFormat("bogus" as never);
    expect(usePreferences.getState().dateFormat).toBe("medium");
    expect(localStorage.getItem("pref.dateFormat")).toBeNull();
  });

  it("defaults headlineVariant to standard when localStorage is empty", async () => {
    const usePreferences = await freshStore();
    expect(usePreferences.getState().headlineVariant).toBe("standard");
  });

  it("loads a saved headline variant from localStorage", async () => {
    localStorage.setItem("pref.headlineVariant", "timeline");
    const usePreferences = await freshStore();
    expect(usePreferences.getState().headlineVariant).toBe("timeline");
  });

  it("falls back to standard when localStorage has an unknown variant", async () => {
    localStorage.setItem("pref.headlineVariant", "not-a-variant");
    const usePreferences = await freshStore();
    expect(usePreferences.getState().headlineVariant).toBe("standard");
  });

  it("setHeadlineVariant persists to localStorage", async () => {
    const usePreferences = await freshStore();
    usePreferences.getState().setHeadlineVariant("timeline");
    expect(usePreferences.getState().headlineVariant).toBe("timeline");
    expect(localStorage.getItem("pref.headlineVariant")).toBe("timeline");
  });

  it("setHeadlineVariant ignores unknown variants", async () => {
    const usePreferences = await freshStore();
    usePreferences.getState().setHeadlineVariant("bogus" as never);
    expect(usePreferences.getState().headlineVariant).toBe("standard");
    expect(localStorage.getItem("pref.headlineVariant")).toBeNull();
  });
});
