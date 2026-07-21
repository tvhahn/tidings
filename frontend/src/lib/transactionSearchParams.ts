import type { SearchParams } from "@/types/api";

/**
 * URL ⇄ SearchParams mapping for the Transactions page's range mode.
 *
 * The URL is the source of truth for a cross-month search: it is shareable and
 * deep-linkable. Range mode is active only when BOTH `from` and `to` are
 * present. The optional params use short URL keys (`min`, `max`, `ignored`,
 * `trash`) that map onto the API's longer field names.
 */

function isTruthyParam(value: string | null): boolean {
  return value === "1" || value === "true";
}

/**
 * Build the API `SearchParams` from the current URL query, or `null` when the
 * URL is not in range mode (missing `from`/`to`). Returning `null` keeps
 * `useTransactionSearch` disabled in month mode.
 */
export function searchParamsFromUrl(url: URLSearchParams): SearchParams | null {
  const from = url.get("from");
  const to = url.get("to");
  if (from === null || to === null) return null;

  const params: SearchParams = { from, to };

  const q = url.get("q");
  if (q) params.q = q;

  const category = url.get("category");
  if (category) params.category = category;

  const institution = url.get("institution");
  if (institution) params.institution = institution;

  const type = url.get("type");
  if (type) params.type = type;

  const min = url.get("min");
  if (min) {
    const n = Number(min);
    if (Number.isFinite(n)) params.min_amount = n;
  }

  const max = url.get("max");
  if (max) {
    const n = Number(max);
    if (Number.isFinite(n)) params.max_amount = n;
  }

  if (isTruthyParam(url.get("ignored"))) params.include_ignored = true;
  if (isTruthyParam(url.get("trash"))) params.include_deleted = true;

  return params;
}

/**
 * Serialize `SearchParams` back into the range-mode URL query keys. Produces a
 * clean set (only `from`/`to` plus whichever optional filters are active) — the
 * caller layers on the anchor `month` separately.
 */
export function toRangeUrlParams(params: SearchParams): URLSearchParams {
  const url = new URLSearchParams();
  url.set("from", params.from);
  url.set("to", params.to);
  if (params.q) url.set("q", params.q);
  if (params.category) url.set("category", params.category);
  if (params.institution) url.set("institution", params.institution);
  if (params.type) url.set("type", params.type);
  if (params.min_amount != null) url.set("min", String(params.min_amount));
  if (params.max_amount != null) url.set("max", String(params.max_amount));
  if (params.include_ignored) url.set("ignored", "1");
  if (params.include_deleted) url.set("trash", "1");
  return url;
}
