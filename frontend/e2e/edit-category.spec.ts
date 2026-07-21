import { test, expect } from "@playwright/test";
import { trackConsoleErrors } from "./helpers";

/**
 * Edit-category flow — stronger than the smoke-level check in
 * demo-smoke.spec.ts. Asserts that the category pill text actually
 * changes after the user picks a different category, not just that
 * the page still renders post-interaction.
 */

test("category edit changes the pill text", async ({ page }) => {
  const errors = trackConsoleErrors(page);
  await page.goto("/demo/transactions?month=2026-03");
  await page.waitForLoadState("networkidle");

  // TransactionsPage renders BOTH the desktop <TransactionTable> (hidden on
  // mobile via `hidden md:block`) and mobile <TransactionCard> list (hidden
  // on desktop via `md:hidden`) in the DOM. `.first()` alone picks up a
  // display:none picker from whichever block is hidden on the current
  // viewport, so filter to visible.
  const firstPicker = page
    .getByRole("button", { name: "Edit category" })
    .filter({ visible: true })
    .first();
  await expect(firstPicker).toBeVisible({ timeout: 5000 });
  const before = (await firstPicker.innerText()).trim();

  await firstPicker.click();
  // Pick an option that differs from the current pill text. The picker
  // shows canonical category names ("Restaurant/Dining"); the pill renders
  // them through `titleCase` which collapses slashes to spaces ("Restaurant
  // Dining"). Without normalization the test would pick the canonical
  // version of the *same* category and the pill text wouldn't change.
  const norm = (s: string) => s.toLowerCase().replace(/\//g, " ").replace(/\s+/g, " ").trim();
  const options = page.getByRole("option");
  const optionCount = await options.count();
  let picked = false;
  for (let i = 0; i < optionCount; i++) {
    const label = (await options.nth(i).innerText()).trim();
    if (label && norm(label) !== norm(before)) {
      await options.nth(i).click();
      picked = true;
      break;
    }
  }
  expect(picked, "expected at least one category option distinct from the current pill").toBe(true);

  // Pill text should update after mutation settles.
  await expect(firstPicker).not.toHaveText(before, { timeout: 5000 });
  expect(errors, `console errors:\n${errors.join("\n")}`).toEqual([]);
});
