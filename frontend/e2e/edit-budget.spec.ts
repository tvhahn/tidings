import { test, expect } from "@playwright/test";
import { trackConsoleErrors } from "./helpers";

/**
 * Budget edit flow — modifying a category target persists and survives
 * navigation. Catches regressions in the demo SPA's sessionStorage-backed
 * budget overlay (`frontend/src/lib/demoApi.ts:474`) which is the path the
 * `/demo/budgets/edit` mutation goes through in the production demo build.
 */

test("editing a budget target persists across navigation", async ({ page }) => {
  const errors = trackConsoleErrors(page);
  await page.goto("/demo/budgets/edit");
  await page.waitForLoadState("networkidle");

  // The page renders one <input type="number"> per category × per input
  // mode (monthly/yearly), but only one is *visible* per row at a time.
  // Pick the first visible numeric input.
  const firstInput = page.locator('input[type="number"]').filter({ visible: true }).first();
  await expect(firstInput).toBeVisible({ timeout: 5000 });

  const before = await firstInput.inputValue();
  // Bump the value by an arbitrary non-zero delta — using "1" isn't safe
  // because the field might already be 1; pick a value unlikely to collide.
  const after = "9876";

  await firstInput.fill(after);
  await firstInput.blur();

  // Save lives in the page header.
  const saveButton = page.getByRole("button", { name: /^Save$/i }).first();
  await expect(saveButton).toBeEnabled();
  await saveButton.click();

  // Successful save navigates to /budgets (or /demo/budgets in the
  // production demo build).
  await page.waitForURL(/\/budgets(?:\?|$)/, { timeout: 5000 });

  // Navigate back into the edit view; the modified value should still be
  // populated from the session-overlay snapshot.
  await page.goto("/demo/budgets/edit");
  await page.waitForLoadState("networkidle");
  const persistedInput = page.locator('input[type="number"]').filter({ visible: true }).first();
  await expect(persistedInput).toBeVisible();
  const persisted = await persistedInput.inputValue();

  expect(persisted, `expected the new target ${after} to survive a reload, before=${before}`).toBe(
    after
  );
  expect(errors, `console errors:\n${errors.join("\n")}`).toEqual([]);
});
