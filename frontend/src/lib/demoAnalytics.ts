// ---------------------------------------------------------------------------
// Demo analytics kernels
//
// These three functions are deliberate, hand-ported TypeScript twins of tested
// backend Python. They exist so the static demo (which has no backend) can
// reproduce the same analytics numbers the real API computes. They are pure and
// synchronous; any fixture/I-O concerns live in the callers in `demoApi.ts`.
//
// Python counterparts (diff against these when the backend changes):
//   - topCategoryDeltas       ← `_compute_category_deltas`
//         src/finance/insights_context.py  (symbol: _compute_category_deltas)
//   - computeCategoryAnomalies ← `BudgetServiceBase.get_category_anomalies`
//         src/finance/budget_service_base.py (symbol: get_category_anomalies)
//   - inferMerchantType       ← `BudgetServiceBase.infer_category_type`
//         src/finance/budget_service_base.py (symbol: infer_category_type)
//
// IMPORTANT: these pin CURRENT demo behavior exactly. Do not "correct" any
// threshold or rounding toward the Python source — characterization tests in
// `demoAnalytics.test.ts` lock the observed numbers. If the backend drifts,
// update deliberately (and its tests), never as a silent fix.
// ---------------------------------------------------------------------------

import type {
  CategoryAnomaly,
  CategoryDelta,
  MerchantRecord,
  SummaryComparisonResponse,
} from "@/types/api";

type CategoryAmountMap = SummaryComparisonResponse["current"]["by_category"];

/**
 * Per-category month-over-month deltas, top N by absolute delta amount.
 *
 * `delta_pct` is `(current - previous) / previous * 100` rounded to 1 dp when
 * the previous amount is > 0, otherwise `null`. Amounts round to 2 dp. Sort is
 * by descending `|delta_amount|`; result is sliced to `topN`.
 *
 * Twin of `_compute_category_deltas` (insights_context.py).
 */
export function topCategoryDeltas(
  current: SummaryComparisonResponse["current"],
  previous: SummaryComparisonResponse["previous"],
  topN = 5
): CategoryDelta[] {
  const cur = current?.by_category ?? {};
  const prev = previous?.by_category ?? {};
  const cats = new Set([...Object.keys(cur), ...Object.keys(prev)]);
  const deltas: CategoryDelta[] = [];
  for (const cat of cats) {
    const c = cur[cat]?.amount ?? 0;
    const p = prev[cat]?.amount ?? 0;
    const delta = c - p;
    deltas.push({
      category: cat,
      current: Math.round(c * 100) / 100,
      previous: Math.round(p * 100) / 100,
      delta_amount: Math.round(delta * 100) / 100,
      delta_pct: p > 0 ? Math.round(((c - p) / p) * 1000) / 10 : null,
    });
  }
  deltas.sort((a, b) => Math.abs(b.delta_amount) - Math.abs(a.delta_amount));
  return deltas.slice(0, topN);
}

/**
 * Pure scoring core of the demo anomaly detector.
 *
 * Given the per-baseline-month `by_category` maps (oldest → newest) and the
 * target month's `by_category` map, compute the anomaly list. All fixture
 * loading stays in the caller (`computeAnomalies` in demoApi.ts) — this kernel
 * only does arithmetic and sorting.
 *
 * Per category (union of categories seen across the baseline months):
 *   - series = the category's amount in each baseline month (0 when absent)
 *   - mean   = sum(series) / series.length
 *   - "unexpected zero": current === 0, active in every baseline month, mean > 0
 *     → severity "medium", emitted before any z-score check
 *   - otherwise, with series.length >= 2: sample stdev (n-1); skip when
 *     stdev === 0 or mean === 0; z = (current - mean) / stdev; skip when |z| < 1.5
 *   - severity bands: |z| < 2 → "low", < 3 → "medium", else "high"
 * Sort: severity desc, then |current - baseline| desc.
 *
 * Twin of `BudgetServiceBase.get_category_anomalies` (budget_service_base.py).
 */
export function computeCategoryAnomalies(
  baselineByCategory: CategoryAmountMap[],
  targetByCategory: CategoryAmountMap
): CategoryAnomaly[] {
  const allCats = new Set<string>();
  for (const m of baselineByCategory) for (const c of Object.keys(m)) allCats.add(c);

  const anomalies: CategoryAnomaly[] = [];
  for (const cat of allCats) {
    const series = baselineByCategory.map((m) => m[cat]?.amount ?? 0);
    const current = targetByCategory[cat]?.amount ?? 0;
    const monthsActive = series.filter((v) => v > 0).length;
    const mean = series.reduce((s, v) => s + v, 0) / series.length;

    if (current === 0 && monthsActive === series.length && mean > 0) {
      anomalies.push({
        category: cat,
        current: 0,
        baseline: Math.round(mean * 100) / 100,
        severity: "medium",
        reason: `no activity this month — usually averages $${Math.round(mean).toLocaleString()}`,
        annotated_amount: 0,
      });
      continue;
    }
    if (series.length < 2) continue;
    const variance = series.reduce((s, v) => s + (v - mean) ** 2, 0) / (series.length - 1);
    const stdev = Math.sqrt(variance);
    if (stdev === 0 || mean === 0) continue;
    const z = (current - mean) / stdev;
    const absZ = Math.abs(z);
    if (absZ < 1.5) continue;
    const severity: "low" | "medium" | "high" = absZ < 2 ? "low" : absZ < 3 ? "medium" : "high";
    const direction = z > 0 ? "above" : "below";
    const pct = ((current - mean) / mean) * 100;
    anomalies.push({
      category: cat,
      current: Math.round(current * 100) / 100,
      baseline: Math.round(mean * 100) / 100,
      severity,
      reason: `roughly ${Math.abs(Math.round(pct))}% ${direction} the ${series.length}-month average of $${Math.round(mean).toLocaleString()}`,
      annotated_amount: 0,
    });
  }
  const sevRank: Record<string, number> = { high: 3, medium: 2, low: 1 };
  anomalies.sort((a, b) => {
    const r = (sevRank[b.severity] ?? 0) - (sevRank[a.severity] ?? 0);
    if (r !== 0) return r;
    return Math.abs(b.current - b.baseline) - Math.abs(a.current - a.baseline);
  });
  return anomalies;
}

/**
 * Infer a merchant's spending frequency type.
 *
 *   monthsActive === 0                → "none"
 *   monthsActive < total              → "lumpy"
 *   monthsActive === total, cv < 0.15 → "fixed"
 *   otherwise (cv >= 0.15 or unknown) → "variable"
 *
 * Twin of `BudgetServiceBase.infer_category_type` (budget_service_base.py).
 */
export function inferMerchantType(
  monthsActive: number,
  total: number,
  cv: number | null
): MerchantRecord["frequency_type"] {
  if (monthsActive === 0) return "none";
  if (monthsActive < total) return "lumpy";
  if (cv !== null && cv < 0.15) return "fixed";
  return "variable";
}
