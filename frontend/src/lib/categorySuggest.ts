/**
 * Local merchant-history suggester for the CategoryPicker.
 *
 * Walks an iterable of cached transactions, finds those whose merchant matches
 * `targetCompany` (under both raw lowercase and `normalizeMerchant` form),
 * tallies category frequency, and returns the most-frequent category — when
 * that category differs from the current value and has at least two prior
 * matches.
 *
 * Pure function: no React, no fetches. Caller hands in whatever iterable they
 * have on hand (typically the transactions extracted from React Query cache).
 */

import { normalizeMerchant } from "./merchantNormalize";

export interface TransactionLike {
  company: string | null;
  category: string | null;
  ignored?: boolean | null;
  deleted_at?: string | null;
}

export interface LocalSuggestion {
  category: string;
  count: number;
}

const MIN_COUNT = 2;

export function suggestFromHistory(
  targetCompany: string | null | undefined,
  currentCategory: string | null,
  transactions: Iterable<TransactionLike>
): LocalSuggestion | null {
  if (!targetCompany) return null;
  const targetRaw = targetCompany.trim().toLowerCase();
  if (!targetRaw) return null;
  const targetNorm = normalizeMerchant(targetCompany).toLowerCase();
  const currentLower = currentCategory?.toLowerCase() ?? null;

  const counts = new Map<string, number>();

  for (const t of transactions) {
    if (!t.company || !t.category) continue;
    if (t.ignored) continue;
    if (t.deleted_at) continue;

    const company = t.company.toLowerCase();
    if (
      company !== targetRaw &&
      (!targetNorm || normalizeMerchant(t.company).toLowerCase() !== targetNorm)
    ) {
      continue;
    }

    const category = t.category.toLowerCase();
    if (category === "miscellaneous") continue;
    if (currentLower !== null && category === currentLower) continue;

    counts.set(category, (counts.get(category) ?? 0) + 1);
  }

  if (counts.size === 0) return null;

  let bestCategory: string | null = null;
  let bestCount = 0;
  for (const [category, count] of counts) {
    if (count > bestCount) {
      bestCategory = category;
      bestCount = count;
    }
  }

  if (bestCategory === null || bestCount < MIN_COUNT) return null;
  return { category: bestCategory, count: bestCount };
}
