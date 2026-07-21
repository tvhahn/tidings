import { useTheme } from "@/stores/theme";
import { useMediaQuery } from "./useMediaQuery";

const DARK_QUERY = "(prefers-color-scheme:dark)";

/** Whether the `.dark` class is currently on <html> — mode "dark", or "system"
 *  with the OS in dark. Mirrors applyTheme() in stores/theme.ts. Rerenders on
 *  store changes and on OS-level changes, so consumers swap live with the
 *  theme pickers. */
export function useIsDark(): boolean {
  const mode = useTheme((s) => s.mode);
  const systemDark = useMediaQuery(DARK_QUERY);
  return mode === "dark" || (mode === "system" && systemDark);
}
