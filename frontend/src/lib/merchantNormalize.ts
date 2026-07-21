/**
 * JS port of `src/finance/merchant_normalizer.py`. Strips store/location numbers,
 * trailing province/country codes, and trailing punctuation so two phrasings of
 * the same merchant ("Safeway #1234" and "Safeway Vancouver BC") collapse to a
 * shared key for local history lookup.
 *
 * Pure regex cleanup — alias resolution lives elsewhere (the picker has no
 * cheap access to the alias map). Keep this in lockstep with the Python rules
 * via `merchantNormalize.test.ts`.
 */

const CLEANUP_PATTERNS: RegExp[] = [
  /\s*#\s*\d+\s*$/i,
  /\s+(?:store|loc(?:ation)?|branch|unit)\s*#?\s*\d+\s*$/i,
  /\s+(?:AB|BC|MB|NB|NL|NS|NT|NU|ON|PE|QC|SK|YT)\s*$/i,
  /\s+(?:CA|CAN|US|USA)\s*$/i,
  /[\s\-*#]+$/,
];

export function normalizeMerchant(name: string | null | undefined): string {
  if (!name) return "";

  let cleaned = name.trim();
  let changed = true;
  while (changed) {
    changed = false;
    for (const pattern of CLEANUP_PATTERNS) {
      const result = cleaned.replace(pattern, "").trim();
      if (result !== cleaned) {
        cleaned = result;
        changed = true;
      }
    }
  }

  if (!cleaned) return name.trim();
  return cleaned;
}
