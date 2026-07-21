import { test, expect } from "@playwright/test";
import { trackConsoleErrors } from "./helpers";

/**
 * Omnibar (⌘K command palette) flows against the demo fixtures. Covers the
 * three answer paths the spec promises — merchant totals, category budget
 * position, and persisted recents — plus the keyboard open/close contract.
 *
 * Fixture choices (verified against frontend/public/demo-data/):
 *  - Merchant "Balzac's King West" appears in transactions-2026-0{1,2,3}.json,
 *    inside the Omnibar's trailing-12-month window (2025-04 → 2026-03, since
 *    demo currentMonth() is pinned to 2026-03). Typing "balzac" substring-
 *    matches it (demoApi.searchTransactions lowercases the company filter).
 *  - Category "Restaurant/Dining" is in categories.json; typing "dining"
 *    substring-matches it, and summary-2026-03.json carries its spend.
 */

test("merchant answer drills into search with results", async ({ page }) => {
  const errors = trackConsoleErrors(page);
  await page.goto("/demo/journal");
  await page.waitForLoadState("networkidle");

  // Open via the global ⌘K / Ctrl+K shortcut.
  await page.keyboard.press("ControlOrMeta+k");
  const dialog = page.getByRole("dialog");
  await expect(dialog).toBeVisible();

  // Type a fixture merchant; the answer row is debounced (250 ms) then renders
  // "<n> visits · $<m> this month · $<y> this year".
  await dialog.getByRole("combobox").fill("balzac");
  await expect(dialog.getByText(/\$\d/).first()).toBeVisible({ timeout: 5000 });
  // The answer row leads with the normalized merchant name.
  await expect(dialog.getByText(/balzac/i).first()).toBeVisible();

  // Enter on the merchant answer drills into the Transactions range view.
  await page.keyboard.press("Enter");
  await page.waitForLoadState("networkidle");
  // The Transactions range view hydrates its free-text box from `q`; assert the
  // pathname plus the hydrated filter input.
  await expect(page).toHaveURL(/\/demo\/transactions/);
  await expect(page.locator("main").getByPlaceholder("Search merchants...")).toHaveValue("balzac");

  // A results row for the merchant is visible.
  await expect(
    page
      .locator("main")
      .getByText(/Balzac/i)
      .first()
  ).toBeVisible({ timeout: 5000 });

  expect(errors, `console errors:\n${errors.join("\n")}`).toEqual([]);
});

test("category answer shows this-month spend; Escape closes", async ({ page }) => {
  const errors = trackConsoleErrors(page);
  await page.goto("/demo/journal");
  await page.waitForLoadState("networkidle");

  await page.keyboard.press("ControlOrMeta+k");
  const dialog = page.getByRole("dialog");
  await expect(dialog).toBeVisible();

  // A fixture category name; the answer row reads "$<amount> this month".
  await dialog.getByRole("combobox").fill("dining");
  await expect(dialog.getByText(/this month/i).first()).toBeVisible({ timeout: 5000 });

  // Escape closes the palette.
  await page.keyboard.press("Escape");
  await expect(dialog).not.toBeVisible();

  expect(errors, `console errors:\n${errors.join("\n")}`).toEqual([]);
});

test("recents persist across a reload", async ({ page }) => {
  const errors = trackConsoleErrors(page);
  await page.goto("/demo/journal");
  await page.waitForLoadState("networkidle");

  // Run a merchant query so it lands in the recents store (persisted to
  // localStorage, keyed by the destination URL).
  await page.keyboard.press("ControlOrMeta+k");
  const dialog = page.getByRole("dialog");
  await expect(dialog).toBeVisible();
  await dialog.getByRole("combobox").fill("balzac");
  await expect(dialog.getByText(/\$\d/).first()).toBeVisible({ timeout: 5000 });
  await page.keyboard.press("Enter");
  await page.waitForLoadState("networkidle");
  // The Transactions range view hydrates its free-text box from `q` (see the
  // merchant test), so assert the pathname plus the hydrated filter input.
  await expect(page).toHaveURL(/\/demo\/transactions/);
  await expect(page.locator("main").getByPlaceholder("Search merchants...")).toHaveValue("balzac");

  // Reload, reopen with empty input — the Recent group lists the prior query.
  await page.goto("/demo/journal");
  await page.waitForLoadState("networkidle");
  await page.keyboard.press("ControlOrMeta+k");
  const reopened = page.getByRole("dialog");
  await expect(reopened).toBeVisible();
  await expect(reopened.getByText(/^Recent$/)).toBeVisible({ timeout: 5000 });
  await expect(reopened.getByText(/balzac/i).first()).toBeVisible();

  expect(errors, `console errors:\n${errors.join("\n")}`).toEqual([]);
});
