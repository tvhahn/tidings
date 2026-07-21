import { test, expect } from "@playwright/test";
import { trackConsoleErrors } from "./helpers";

/**
 * Insights-view flow — in demo mode the app ships pre-generated
 * briefings (see InsightsPage.tsx:112-114). Exercising the full
 * generate-then-stream flow would require a backend; this spec
 * confirms the pre-generated briefing for a demo month renders and
 * contains narrative content.
 *
 * A regression that broke the briefing renderer, the month → briefing
 * lookup, or the static-data loader would fail this check.
 */

test("demo insights page renders a pre-generated briefing", async ({ page }) => {
  const errors = trackConsoleErrors(page);
  await page.goto("/demo/insights?month=2026-03");
  await page.waitForLoadState("networkidle");

  // Scope to <main> so sidebar-nav text doesn't race the real content.
  const main = page.locator("main");

  // Either the "Generated" timestamp line (when content is loaded) or the
  // pre-generated hint (idle state fallback) proves the briefing wiring is
  // alive. The fixture ships a briefing for 2026-03, so the timestamp should
  // appear.
  await expect(main.getByText(/Generated/i).first()).toBeVisible({ timeout: 5000 });

  // Persona-anchored briefing: the body carries Mira's narrative for the
  // month and uses the canonical 6-heading layout. The first H2 is "Headline".
  const bodyText = await main.innerText();
  expect(bodyText.length).toBeGreaterThanOrEqual(1500);
  expect(bodyText).toMatch(/Headline/);

  expect(errors, `console errors:\n${errors.join("\n")}`).toEqual([]);
});
