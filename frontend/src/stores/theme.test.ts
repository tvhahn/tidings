import { beforeEach, describe, expect, it, vi } from "vitest";

async function freshStore() {
  vi.resetModules();
  const mod = await import("./theme");
  return mod;
}

describe("theme store", () => {
  beforeEach(() => {
    localStorage.clear();
    document.documentElement.className = "";
    delete document.documentElement.dataset.palette;
    delete document.documentElement.dataset.surface;
    vi.resetModules();
  });

  it("defaults to light mode and the warm-paper palette when storage is empty", async () => {
    const { useTheme } = await freshStore();
    expect(useTheme.getState().mode).toBe("light");
    expect(useTheme.getState().palette).toBe("warm-paper");
  });

  it("honors a stored default palette (explicit base-palette choice)", async () => {
    localStorage.setItem("theme.palette", "default");
    const { useTheme } = await freshStore();
    expect(useTheme.getState().palette).toBe("default");
  });

  it("defaults to light mode on the demo and marketing surfaces", async () => {
    document.documentElement.dataset.surface = "demo";
    expect((await freshStore()).useTheme.getState().mode).toBe("light");
    vi.resetModules();
    document.documentElement.dataset.surface = "marketing";
    expect((await freshStore()).useTheme.getState().mode).toBe("light");
  });

  it("a stored choice still wins over the demo surface default", async () => {
    document.documentElement.dataset.surface = "demo";
    localStorage.setItem("theme", "dark");
    expect((await freshStore()).useTheme.getState().mode).toBe("dark");
  });

  it("loads a saved palette from localStorage on init", async () => {
    localStorage.setItem("theme.palette", "nord");
    const { useTheme } = await freshStore();
    expect(useTheme.getState().palette).toBe("nord");
  });

  it("falls back to warm-paper palette when localStorage has an unknown id", async () => {
    localStorage.setItem("theme.palette", "not-a-real-palette");
    const { useTheme } = await freshStore();
    expect(useTheme.getState().palette).toBe("warm-paper");
  });

  it("setMode persists to localStorage and toggles the dark class", async () => {
    const { useTheme } = await freshStore();
    useTheme.getState().setMode("dark");
    expect(useTheme.getState().mode).toBe("dark");
    expect(localStorage.getItem("theme")).toBe("dark");
    expect(document.documentElement.classList.contains("dark")).toBe(true);
  });

  it("setPalette writes data-palette and persists", async () => {
    const { useTheme } = await freshStore();
    useTheme.getState().setPalette("midnight");
    expect(useTheme.getState().palette).toBe("midnight");
    expect(document.documentElement.dataset.palette).toBe("midnight");
    expect(localStorage.getItem("theme.palette")).toBe("midnight");
  });

  it("setPalette to default removes the data-palette attribute", async () => {
    const { useTheme } = await freshStore();
    useTheme.getState().setPalette("nord");
    useTheme.getState().setPalette("default");
    expect(document.documentElement.dataset.palette).toBeUndefined();
  });

  it("setPalette ignores unknown palette ids", async () => {
    const { useTheme } = await freshStore();
    const before = useTheme.getState().palette;
    useTheme.getState().setPalette("bogus" as never);
    expect(useTheme.getState().palette).toBe(before);
  });

  it("isWarmPalette returns true for warm-paper and gruvbox", async () => {
    const { isWarmPalette } = await freshStore();
    expect(isWarmPalette("warm-paper")).toBe(true);
    expect(isWarmPalette("gruvbox")).toBe(true);
    expect(isWarmPalette("nord")).toBe(false);
    expect(isWarmPalette("midnight")).toBe(false);
  });
});
