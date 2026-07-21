import { test, expect } from "@playwright/test";
import { trackConsoleErrors } from "./helpers";

/**
 * Statements-page flow — in demo mode, upload is disabled and the page
 * renders a self-host CTA card in place of the drag-drop zone. The
 * statements.json fixture ships a populated upload history (Mira's
 * persona stack, post-parity rewrite). This test pins: the page must
 * render the self-host CTA AND the populated upload history.
 *
 * The full upload → parse → reconcile → import flow requires a backend
 * and is out of scope for the demo-build Playwright target.
 */

test("demo statements page renders self-host callout", async ({ page }) => {
  const errors = trackConsoleErrors(page);
  await page.goto("/demo/statements");
  await page.waitForLoadState("networkidle");

  // Scope to <main> so the sidebar nav's "Statements" link (hidden on mobile
  // viewports, visible on desktop) never wins the locator race.
  const main = page.locator("main");

  // Page header rendered
  await expect(main.getByText(/^Statements$/).first()).toBeVisible();
  // Self-host CTA card copy (anchored on a unique phrase)
  await expect(main.getByText(/PDF upload runs on your own machine/i)).toBeVisible({
    timeout: 5000,
  });
  // Populated upload history: the heading is required, no empty-state branch.
  const uploadHistoryHeading = main.getByRole("heading", { name: /Upload History/i });
  await expect(uploadHistoryHeading).toBeVisible({ timeout: 5000 });

  // Each row in the history is a clickable div with role="button" rendered
  // inside the StatementHistory card list. The fixture ships >=10 entries;
  // pin a floor of 5 so a partial render still fails.
  const rows = main.locator('div[role="button"][tabindex="0"]');
  expect(await rows.count()).toBeGreaterThanOrEqual(5);

  expect(errors, `console errors:\n${errors.join("\n")}`).toEqual([]);
});
