import { test, expect } from "@playwright/test";
import { trackConsoleErrors } from "./helpers";

/**
 * Tax-receipts page flow — in demo mode the page renders from the generated
 * tax-pack-2026.json fixture (a backend snapshot, never computed client-side).
 * This test pins: the page renders its header, the seven CRA claim lines, and
 * the calm tax-advice disclaimer; a line section expands to reveal its detail
 * region; and the console stays clean. The export is demo-gated and out of
 * scope for the demo-build Playwright target.
 */

test("demo tax page renders the claim lines and expands one", async ({ page }) => {
  const errors = trackConsoleErrors(page);
  await page.goto("/demo/tax");
  await page.waitForLoadState("networkidle");

  // Scope to <main> so the sidebar nav's "Tax receipts" link never wins the
  // locator race on desktop viewports.
  const main = page.locator("main");

  // Page header rendered.
  await expect(main.getByText(/^Tax receipts$/).first()).toBeVisible();

  // The seven CRA claim lines are present (labels come straight from the seed).
  const charitable = main.getByText("Charitable donations");
  await expect(charitable).toBeVisible({ timeout: 5000 });
  await expect(main.getByText("Medical expenses")).toBeVisible();
  await expect(main.getByText("Child care expenses")).toBeVisible();

  // The calm disclaimer sentence (verbatim from the spec).
  await expect(
    main.getByText("Tidings organizes your records; it doesn't give tax advice.")
  ).toBeVisible();

  // Expand a line section — its detail region appears. The demo dataset carries
  // no claimable transactions, so the calm per-line empty text is the marker.
  const lineRow = main.locator('[role="button"]').filter({ hasText: "Charitable donations" });
  await lineRow.first().click();
  await expect(main.getByText(/No claimable transactions for 2026\./).first()).toBeVisible({
    timeout: 5000,
  });

  expect(errors, `console errors:\n${errors.join("\n")}`).toEqual([]);
});
