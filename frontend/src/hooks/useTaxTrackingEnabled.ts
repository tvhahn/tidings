import { useConfig } from "@/hooks/useConfig";

/**
 * Instance-level gate for the tax receipts feature. Drives the Tax receipts nav
 * tab, the `/tax` route, and the per-row "Flag as tax item" control on the
 * Transactions and Journal pages, so the four surfaces can never drift.
 *
 * Defaults to `true` while config is loading or absent (a pre-flag config merges
 * to the backend default of on), matching the historical always-visible behavior.
 */
export function useTaxTrackingEnabled(): boolean {
  const { data: config } = useConfig();
  return config?.tax_tracking_enabled ?? true;
}
