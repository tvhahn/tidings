// @vitest-environment jsdom
import { beforeEach, describe, expect, it, vi } from "vitest";
import { DEFAULT_ORDER, SETTINGS_HREF } from "@/config/navTabs";

async function freshStore() {
  vi.resetModules();
  const mod = await import("./navPreferences");
  return mod.useNavPreferences;
}

describe("navPreferences store", () => {
  beforeEach(() => {
    localStorage.clear();
    vi.resetModules();
  });

  it("initialises with the default order when localStorage is empty", async () => {
    const useNavPreferences = await freshStore();
    expect(useNavPreferences.getState().tabOrder).toEqual(DEFAULT_ORDER);
    expect(useNavPreferences.getState().hiddenTabs).toEqual([]);
  });

  it("restores a saved order from localStorage", async () => {
    const saved = ["/transactions", "/", "/summary"];
    localStorage.setItem("nav.tabOrder", JSON.stringify(saved));
    const useNavPreferences = await freshStore();
    const order = useNavPreferences.getState().tabOrder;
    // Saved entries come first, missing defaults are appended
    expect(order.slice(0, 3)).toEqual(saved);
    expect(order).toHaveLength(DEFAULT_ORDER.length);
    expect(new Set(order)).toEqual(new Set(DEFAULT_ORDER));
  });

  it("appends newly introduced tabs to the end (migration)", async () => {
    // User's saved order is missing /insights and /statements
    const saved = ["/", "/transactions", "/summary", "/budgets"];
    localStorage.setItem("nav.tabOrder", JSON.stringify(saved));
    const useNavPreferences = await freshStore();
    const order = useNavPreferences.getState().tabOrder;
    expect(order.slice(0, 4)).toEqual(saved);
    expect(order).toContain("/insights");
    expect(order).toContain("/statements");
  });

  it("strips unknown hrefs and /settings from saved order", async () => {
    localStorage.setItem(
      "nav.tabOrder",
      JSON.stringify(["/", "/bogus", SETTINGS_HREF, "/transactions"])
    );
    const useNavPreferences = await freshStore();
    const order = useNavPreferences.getState().tabOrder;
    expect(order).not.toContain("/bogus");
    expect(order).not.toContain(SETTINGS_HREF);
    expect(order).toContain("/");
    expect(order).toContain("/transactions");
  });

  it("toggleHidden adds and removes an href idempotently", async () => {
    const useNavPreferences = await freshStore();
    useNavPreferences.getState().toggleHidden("/insights");
    expect(useNavPreferences.getState().hiddenTabs).toEqual(["/insights"]);
    useNavPreferences.getState().toggleHidden("/insights");
    expect(useNavPreferences.getState().hiddenTabs).toEqual([]);
  });

  it("toggleHidden is a no-op for /settings", async () => {
    const useNavPreferences = await freshStore();
    useNavPreferences.getState().toggleHidden(SETTINGS_HREF);
    expect(useNavPreferences.getState().hiddenTabs).toEqual([]);
  });

  it("toggleHidden ignores unknown hrefs", async () => {
    const useNavPreferences = await freshStore();
    useNavPreferences.getState().toggleHidden("/bogus");
    expect(useNavPreferences.getState().hiddenTabs).toEqual([]);
  });

  it("setOrder persists to localStorage and filters invalid hrefs", async () => {
    const useNavPreferences = await freshStore();
    useNavPreferences.getState().setOrder(["/transactions", SETTINGS_HREF, "/bogus", "/"]);
    const order = useNavPreferences.getState().tabOrder;
    expect(order[0]).toBe("/transactions");
    expect(order[1]).toBe("/");
    expect(order).not.toContain(SETTINGS_HREF);
    expect(order).not.toContain("/bogus");
    const persisted = JSON.parse(localStorage.getItem("nav.tabOrder") ?? "null");
    expect(persisted).toEqual(order);
  });

  it("reset clears both keys and returns to defaults", async () => {
    const useNavPreferences = await freshStore();
    useNavPreferences.getState().setOrder(["/transactions", "/"]);
    useNavPreferences.getState().toggleHidden("/insights");
    useNavPreferences.getState().reset();
    expect(useNavPreferences.getState().tabOrder).toEqual(DEFAULT_ORDER);
    expect(useNavPreferences.getState().hiddenTabs).toEqual([]);
    expect(localStorage.getItem("nav.tabOrder")).toBeNull();
    expect(localStorage.getItem("nav.hiddenTabs")).toBeNull();
  });

  it("ignores corrupt localStorage values", async () => {
    localStorage.setItem("nav.tabOrder", "{not json");
    localStorage.setItem("nav.hiddenTabs", "also not json");
    const useNavPreferences = await freshStore();
    expect(useNavPreferences.getState().tabOrder).toEqual(DEFAULT_ORDER);
    expect(useNavPreferences.getState().hiddenTabs).toEqual([]);
  });
});
