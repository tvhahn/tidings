// @vitest-environment jsdom
import { act, renderHook } from "@testing-library/react";
import { afterEach, describe, expect, it, vi } from "vitest";
import { useMediaQuery } from "./useMediaQuery";

type ChangeHandler = (e: MediaQueryListEvent) => void;

function installMatchMedia(initialMatches: boolean) {
  const listeners = new Set<ChangeHandler>();
  const mql = {
    matches: initialMatches,
    media: "(min-width: 640px)",
    onchange: null,
    addEventListener: (_event: "change", handler: ChangeHandler) => {
      listeners.add(handler);
    },
    removeEventListener: (_event: "change", handler: ChangeHandler) => {
      listeners.delete(handler);
    },
    dispatchEvent: () => true,
    // legacy API on MediaQueryList — unused here
    addListener: () => {},
    removeListener: () => {},
  };
  vi.stubGlobal(
    "matchMedia",
    vi.fn(() => mql)
  );
  return {
    fire(matches: boolean) {
      mql.matches = matches;
      for (const h of listeners) h({ matches } as MediaQueryListEvent);
    },
    listenerCount: () => listeners.size,
  };
}

describe("useMediaQuery", () => {
  afterEach(() => {
    vi.unstubAllGlobals();
  });

  it("returns the initial match state", () => {
    installMatchMedia(true);
    const { result } = renderHook(() => useMediaQuery("(min-width: 640px)"));
    expect(result.current).toBe(true);
  });

  it("re-renders when the MediaQueryList fires a change event", () => {
    const mql = installMatchMedia(false);
    const { result } = renderHook(() => useMediaQuery("(min-width: 640px)"));
    expect(result.current).toBe(false);
    act(() => {
      mql.fire(true);
    });
    expect(result.current).toBe(true);
  });

  it("removes its listener on unmount", () => {
    const mql = installMatchMedia(false);
    const { unmount } = renderHook(() => useMediaQuery("(min-width: 640px)"));
    expect(mql.listenerCount()).toBe(1);
    unmount();
    expect(mql.listenerCount()).toBe(0);
  });
});
