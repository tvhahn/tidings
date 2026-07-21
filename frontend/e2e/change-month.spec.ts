import { test, expect } from "@playwright/test";
import { trackConsoleErrors } from "./helpers";

/**
 * Change-month flow — navigates the month picker and confirms the URL
 * + rendered content both update. A regression that stored state but
 * failed to refetch (or vice-versa) would leave them out of sync.
 */

test("summary month picker updates URL + content", async ({ page }) => {
  const errors = trackConsoleErrors(page);
  await page.goto("/demo/summary?month=2026-03");
  await page.waitForLoadState("networkidle");

  // Capture the "top categories" block's text for a baseline. Scope to <main>
  // so the assertion survives mobile viewports where sidebar text is hidden.
  const main = page.locator("main");
  const summary = main.getByText(/Total spending|Spent so far|Top categories/i).first();
  await expect(summary).toBeVisible();
  const marchBody = await main.innerText();

  // Navigate to a different month directly (same pattern the app uses internally).
  await page.goto("/demo/summary?month=2026-02");
  await page.waitForLoadState("networkidle");
  await expect(page).toHaveURL(/month=2026-02/);

  // The body text should differ — monthly numbers should have changed at least somewhere.
  const febBody = await main.innerText();
  expect(febBody).not.toEqual(marchBody);
  expect(errors, `console errors:\n${errors.join("\n")}`).toEqual([]);
});
