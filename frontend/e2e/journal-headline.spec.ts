import { test, expect, type Page } from "@playwright/test";

/**
 * Commitment-aware journal headline — the demo's 2026-03 month is its pinned
 * "current" month, so the summary fixture carries a non-null pace.breakdown.
 * Covers: the default Standard strip with its clickable projection, the
 * shared breakdown sheet, and the Settings → Display variant toggle to
 * Timeline (one toggle test per non-default variant — no capture matrix).
 */

function trackConsoleErrors(page: Page): string[] {
  const errors: string[] = [];
  page.on("console", (msg) => {
    if (msg.type() === "error") errors.push(msg.text());
  });
  page.on("pageerror", (err) => errors.push(err.message));
  return errors;
}

test("journal headline shows the projection and opens the breakdown", async ({ page }) => {
  const errors = trackConsoleErrors(page);
  await page.goto("/demo/journal");
  await page.waitForLoadState("networkidle");

  // Standard (default): projection value labels the forecast diamond.
  const main = page.locator("main");
  const projection = main.getByRole("button", { name: /Projected .* by month end/i });
  await expect(projection).toBeVisible();

  // Opening it reveals the shared breakdown sheet with its section labels.
  await projection.click();
  const sheet = page.getByRole("dialog");
  await expect(sheet.getByText(/how it adds up/i)).toBeVisible();
  await expect(sheet.getByText("Spent so far", { exact: true })).toBeVisible();
  await expect(sheet.getByText(/Everyday spending, estimated/i)).toBeVisible();
  // Demo constraint: statement-lag states cannot occur (Statements is a
  // self-host callout), so the awaiting-statement section must be absent.
  await expect(sheet.getByText(/Awaiting your statement/i)).toHaveCount(0);
  await page.keyboard.press("Escape");
  await expect(page.getByRole("dialog")).toHaveCount(0);

  expect(errors, `console errors:\n${errors.join("\n")}`).toEqual([]);
});

test("headline style toggle switches Standard to Timeline", async ({ page }) => {
  const errors = trackConsoleErrors(page);
  await page.goto("/demo/journal");
  await page.waitForLoadState("networkidle");
  const main = page.locator("main");
  const standardStrip = await main.innerText();

  // Flip the per-device preference in Settings → Display.
  await page.goto("/demo/settings/display");
  await page.waitForLoadState("networkidle");
  const timelineOption = page.getByRole("button", { name: /^Timeline/ });
  await expect(timelineOption).toBeVisible();
  await timelineOption.click();
  await expect(timelineOption).toHaveAttribute("aria-pressed", "true");

  // Back on the journal, the strip is now the month timeline: day dots with
  // jump affordances and pencil circles that open the breakdown.
  await page.goto("/demo/journal");
  await page.waitForLoadState("networkidle");
  await expect(main.getByRole("button", { name: /jump to this day/i }).first()).toBeVisible();
  await expect(main.getByRole("button", { name: /open the breakdown/i }).first()).toBeVisible();
  const timelineStrip = await main.innerText();
  expect(timelineStrip).not.toEqual(standardStrip);

  expect(errors, `console errors:\n${errors.join("\n")}`).toEqual([]);
});
