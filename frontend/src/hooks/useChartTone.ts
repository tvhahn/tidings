import { useEffect, useState } from "react";
import type { ChartTone } from "@/lib/categoryGroups";
import { useTheme, isWarmPalette } from "@/stores/theme";

const DARK_QUERY = "(prefers-color-scheme:dark)";

/** Resolve {isDark, isWarm} for the current theme + palette so chart
 *  consumers can pick the right tone from CATEGORY_HUES. Rerenders on
 *  store changes and on OS-level dark-mode changes (when mode === system). */
export function useChartTone(): ChartTone {
  const mode = useTheme((s) => s.mode);
  const palette = useTheme((s) => s.palette);

  const [systemDark, setSystemDark] = useState(
    () => typeof matchMedia !== "undefined" && matchMedia(DARK_QUERY).matches
  );

  useEffect(() => {
    if (mode !== "system") return;
    const mql = matchMedia(DARK_QUERY);
    const handler = (e: MediaQueryListEvent) => setSystemDark(e.matches);
    mql.addEventListener("change", handler);
    return () => mql.removeEventListener("change", handler);
  }, [mode]);

  const isDark = mode === "dark" || (mode === "system" && systemDark);
  return { isDark, isWarm: isWarmPalette(palette) };
}
