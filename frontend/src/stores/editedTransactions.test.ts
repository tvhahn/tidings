import { beforeEach, describe, expect, it, vi } from "vitest";

async function freshStore() {
  vi.resetModules();
  const mod = await import("./editedTransactions");
  return mod;
}

describe("editedTransactions store", () => {
  beforeEach(() => {
    vi.resetModules();
  });

  it("starts with an empty edited map", async () => {
    const { useEditedTransactions } = await freshStore();
    expect(useEditedTransactions.getState().edited.size).toBe(0);
  });

  it("makeKey joins forwardedTo and dateFileName with a pipe", async () => {
    const { makeKey } = await freshStore();
    expect(makeKey("u@example.com", "2026.01.01_12.00_a.eml")).toBe(
      "u@example.com|2026.01.01_12.00_a.eml"
    );
  });

  it("markEdited records old/new categories under the key", async () => {
    const { useEditedTransactions } = await freshStore();
    useEditedTransactions.getState().markEdited("k1", "groceries", "dining");
    expect(useEditedTransactions.getState().isEdited("k1")).toBe(true);
    expect(useEditedTransactions.getState().edited.get("k1")).toEqual({
      oldCategory: "groceries",
      newCategory: "dining",
    });
  });

  it("markEdited overwrites a previous entry for the same key", async () => {
    const { useEditedTransactions } = await freshStore();
    useEditedTransactions.getState().markEdited("k1", "groceries", "dining");
    useEditedTransactions.getState().markEdited("k1", "dining", "rent");
    expect(useEditedTransactions.getState().edited.get("k1")?.newCategory).toBe("rent");
  });

  it("undo returns the old category and removes the entry", async () => {
    const { useEditedTransactions } = await freshStore();
    useEditedTransactions.getState().markEdited("k1", "groceries", "dining");
    const old = useEditedTransactions.getState().undo("k1");
    expect(old).toBe("groceries");
    expect(useEditedTransactions.getState().isEdited("k1")).toBe(false);
  });

  it("undo returns null when the key is unknown", async () => {
    const { useEditedTransactions } = await freshStore();
    expect(useEditedTransactions.getState().undo("missing")).toBeNull();
  });

  it("clear empties the map", async () => {
    const { useEditedTransactions } = await freshStore();
    useEditedTransactions.getState().markEdited("k1", "a", "b");
    useEditedTransactions.getState().markEdited("k2", "c", "d");
    useEditedTransactions.getState().clear();
    expect(useEditedTransactions.getState().edited.size).toBe(0);
  });
});
