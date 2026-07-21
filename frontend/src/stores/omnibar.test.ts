import { beforeEach, describe, expect, it, vi } from "vitest";
import type { OmniRecent } from "./omnibar";

async function freshStore() {
  vi.resetModules();
  const mod = await import("./omnibar");
  return mod.useOmnibarStore;
}

function recent(over: Partial<OmniRecent> = {}): OmniRecent {
  return { kind: "destination", label: "Summary", to: "/summary", at: 1, ...over };
}

describe("omnibar recents store", () => {
  beforeEach(() => {
    localStorage.clear();
    vi.resetModules();
  });

  it("defaults to an empty list when localStorage is empty", async () => {
    const useOmnibarStore = await freshStore();
    expect(useOmnibarStore.getState().recents).toEqual([]);
  });

  it("adds a recent to the front", async () => {
    const useOmnibarStore = await freshStore();
    useOmnibarStore.getState().addRecent(recent({ to: "/a", label: "A" }));
    useOmnibarStore.getState().addRecent(recent({ to: "/b", label: "B" }));
    expect(useOmnibarStore.getState().recents.map((r) => r.to)).toEqual(["/b", "/a"]);
  });

  it("dedupes by `to` and moves the re-added entry to the front", async () => {
    const useOmnibarStore = await freshStore();
    useOmnibarStore.getState().addRecent(recent({ to: "/a", label: "A" }));
    useOmnibarStore.getState().addRecent(recent({ to: "/b", label: "B" }));
    useOmnibarStore.getState().addRecent(recent({ to: "/c", label: "C" }));
    // Re-add /a with a newer label — it should jump to the front, not duplicate.
    useOmnibarStore.getState().addRecent(recent({ to: "/a", label: "A2" }));
    const recents = useOmnibarStore.getState().recents;
    expect(recents.map((r) => r.to)).toEqual(["/a", "/c", "/b"]);
    expect(recents[0]?.label).toBe("A2");
    expect(recents.filter((r) => r.to === "/a")).toHaveLength(1);
  });

  it("caps at 8 entries, evicting the oldest", async () => {
    const useOmnibarStore = await freshStore();
    for (let i = 0; i < 10; i++) {
      useOmnibarStore.getState().addRecent(recent({ to: `/${i}`, label: `R${i}` }));
    }
    const recents = useOmnibarStore.getState().recents;
    expect(recents).toHaveLength(8);
    // Newest first; the two oldest (/0, /1) are evicted.
    expect(recents.map((r) => r.to)).toEqual(["/9", "/8", "/7", "/6", "/5", "/4", "/3", "/2"]);
  });

  it("clearRecents empties the list and localStorage", async () => {
    const useOmnibarStore = await freshStore();
    useOmnibarStore.getState().addRecent(recent());
    expect(useOmnibarStore.getState().recents).toHaveLength(1);
    useOmnibarStore.getState().clearRecents();
    expect(useOmnibarStore.getState().recents).toEqual([]);
    expect(localStorage.getItem("omnibar.recents")).toBeNull();
  });

  it("persists across a store reload (round-trip)", async () => {
    const useOmnibarStore = await freshStore();
    useOmnibarStore.getState().addRecent(recent({ to: "/x", label: "X", kind: "query", at: 42 }));
    expect(localStorage.getItem("omnibar.recents")).not.toBeNull();

    // A fresh module reads the persisted entries back at init.
    const reloaded = await freshStore();
    expect(reloaded.getState().recents).toEqual([{ kind: "query", label: "X", to: "/x", at: 42 }]);
  });

  it("loads at most 8 persisted entries even if storage holds more", async () => {
    const overfull = Array.from({ length: 12 }, (_, i) => recent({ to: `/${i}` }));
    localStorage.setItem("omnibar.recents", JSON.stringify(overfull));
    const useOmnibarStore = await freshStore();
    expect(useOmnibarStore.getState().recents).toHaveLength(8);
  });

  it("ignores malformed persisted JSON", async () => {
    localStorage.setItem("omnibar.recents", "not-json");
    const useOmnibarStore = await freshStore();
    expect(useOmnibarStore.getState().recents).toEqual([]);
  });

  it("filters out entries with an invalid shape", async () => {
    localStorage.setItem(
      "omnibar.recents",
      JSON.stringify([{ kind: "query", label: "ok", to: "/ok", at: 1 }, { kind: "bogus" }, 5])
    );
    const useOmnibarStore = await freshStore();
    expect(useOmnibarStore.getState().recents).toEqual([
      { kind: "query", label: "ok", to: "/ok", at: 1 },
    ]);
  });
});
