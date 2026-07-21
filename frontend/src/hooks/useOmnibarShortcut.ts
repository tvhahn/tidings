import { useEffect } from "react";

/**
 * Registers the global ⌘K / Ctrl+K shortcut that toggles the Omnibar.
 *
 * The listener is added and removed in a single effect so it never leaks. No
 * `/` shortcut — ⌘K always wins, matching the cmdk convention.
 */
export function useOmnibarShortcut(toggle: () => void): void {
  useEffect(() => {
    const onKeyDown = (event: KeyboardEvent) => {
      if ((event.metaKey || event.ctrlKey) && event.key === "k") {
        event.preventDefault();
        toggle();
      }
    };
    window.addEventListener("keydown", onKeyDown);
    return () => window.removeEventListener("keydown", onKeyDown);
  }, [toggle]);
}
