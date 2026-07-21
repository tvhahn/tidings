import { useMemo } from "react";
import { NAV_TABS, SETTINGS_HREF, TAX_HREF, type NavTab } from "@/config/navTabs";
import { useTaxTrackingEnabled } from "@/hooks/useTaxTrackingEnabled";
import { useNavPreferences } from "@/stores/navPreferences";

/**
 * Resolves the nav-preferences-aware tab list — ordered by `tabOrder`, with
 * `hiddenTabs` excluded and Settings always appended. The single source of
 * truth for both `Layout` and the Omnibar Pages group, so the two never drift.
 * The Tax receipts tab is also dropped when tax tracking is disabled in Settings.
 */
export function useNavItems(): NavTab[] {
  const tabOrder = useNavPreferences((s) => s.tabOrder);
  const hiddenTabs = useNavPreferences((s) => s.hiddenTabs);
  const taxEnabled = useTaxTrackingEnabled();

  return useMemo<NavTab[]>(() => {
    const byHref = new Map(NAV_TABS.map((t) => [t.href, t]));
    const settings = byHref.get(SETTINGS_HREF);
    const hidden = new Set(hiddenTabs);
    const ordered = tabOrder
      .map((h) => byHref.get(h))
      .filter(
        (t): t is NavTab => !!t && !hidden.has(t.href) && (taxEnabled || t.href !== TAX_HREF)
      );
    return settings ? [...ordered, settings] : ordered;
  }, [tabOrder, hiddenTabs, taxEnabled]);
}
