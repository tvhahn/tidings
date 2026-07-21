import { useEffect, useState } from "react";

/** Subscribe to a CSS media query. Returns current match state and
 *  rerenders on change. SSR-safe: returns false when matchMedia isn't
 *  available on first render. */
export function useMediaQuery(query: string): boolean {
  const [matches, setMatches] = useState(() =>
    typeof matchMedia !== "undefined" ? matchMedia(query).matches : false
  );

  useEffect(() => {
    if (typeof matchMedia === "undefined") return;
    const mql = matchMedia(query);
    const handler = (e: MediaQueryListEvent) => setMatches(e.matches);
    setMatches(mql.matches);
    mql.addEventListener("change", handler);
    return () => mql.removeEventListener("change", handler);
  }, [query]);

  return matches;
}
