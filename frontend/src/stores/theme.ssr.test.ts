// @vitest-environment node
import { describe, expect, it, vi } from "vitest";

// The marketing prerender (entry-server.tsx) imports this store in Node, where
// window/localStorage/matchMedia don't exist. These tests pin the SSR-safety
// contract (spec 2026-07-16-seo-and-agent-reach, L3/C2): module import must not
// throw, and the store falls back to its defaults without touching the DOM.
describe("theme store under SSR (no window)", () => {
  it("imports without window and falls back to light mode and the warm-paper palette", async () => {
    vi.resetModules();
    expect(typeof window).toBe("undefined");
    const { useTheme } = await import("./theme");
    expect(useTheme.getState().mode).toBe("light");
    expect(useTheme.getState().palette).toBe("warm-paper");
  });
});
