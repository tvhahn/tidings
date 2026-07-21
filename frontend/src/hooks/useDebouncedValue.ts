import { useEffect, useState } from "react";

/**
 * Returns a debounced version of `value`. Updates lag by `delayMs`.
 * Used by the CategoryRulesSection add-rule form to avoid firing a
 * /match request on every keystroke.
 */
export function useDebouncedValue<T>(value: T, delayMs: number): T {
  const [debounced, setDebounced] = useState(value);

  useEffect(() => {
    const handle = setTimeout(() => setDebounced(value), delayMs);
    return () => clearTimeout(handle);
  }, [value, delayMs]);

  return debounced;
}
