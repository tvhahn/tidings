import { test, expect } from "@playwright/test";
import { trackConsoleErrors } from "./helpers";

/**
 * Anti-rot smoke for the marketing landing at `/`.
 * Asserts the hero renders, the primary CTA navigates into the demo SPA,
 * and the cross-surface boundary is clean of console errors.
 */

test.describe("marketing smoke — landing page + cross-surface flow", () => {
  test("/ renders the hero and CTAs link to /demo", async ({ page }) => {
    const errors = trackConsoleErrors(page);
    await page.goto("/");
    await page.waitForLoadState("networkidle");

    // Hero h1 has both halves; the second half is wrapped in <em>.
    const hero = page.getByRole("heading", { name: /Your spending,\s*delivered\./i, level: 1 });
    await expect(hero).toBeVisible();

    // Sticky nav has the brand wordmark.
    await expect(page.getByRole("link", { name: /Tidings/i }).first()).toBeVisible();

    // The nav's "Try the demo" CTA survives every viewport — on mobile the
    // anchor links collapse but the conversion action stays.
    const navCta = page.locator("nav").getByRole("link", { name: /Try the demo/i });
    await expect(navCta).toBeVisible();
    await expect(navCta).toHaveAttribute("href", /\/demo\/?$/);

    // The hero art is a real product screenshot, not a DOM mock.
    await expect(page.locator(".hero .shot img")).toBeVisible();

    // Section anchors the nav links to (Pricing is gone; Open source is in).
    for (const id of ["how", "features", "privacy", "open-source", "agents", "faq"]) {
      await expect(page.locator(`section[id="${id}"]`)).toHaveCount(1);
    }
    // The open-source section keeps its id as a deep-link target, but the nav
    // no longer links to it — the GitHub CTA covers that job.
    await expect(page.locator('a[href="#open-source"]')).toHaveCount(0);
    await expect(page.locator('a[href="#pricing"]')).toHaveCount(0);

    // Counted rather than visibility-checked: `.nav-links` collapses to
    // display:none on mobile, so the role/visibility path would fail there.
    await expect(page.locator('nav a[href="https://docs.gettidings.com/"]')).toHaveCount(1);

    expect(errors, `console errors on /:\n${errors.join("\n")}`).toEqual([]);
  });

  test("clicking the hero CTA lands on the demo with the banner visible", async ({ page }) => {
    const errors = trackConsoleErrors(page);
    await page.goto("/");
    await page.waitForLoadState("networkidle");

    await page
      .getByRole("link", { name: /Try the demo/i })
      .first()
      .click();
    await page.waitForLoadState("networkidle");

    // basename strips the trailing slash off Navigate to="/" so /demo or
    // /demo/ both end up here. Tolerate either.
    await expect(page).toHaveURL(/\/demo\/?$/);
    await expect(page.getByText(/Demo mode/i).first()).toBeVisible();

    expect(errors, `console errors on cross-surface flow:\n${errors.join("\n")}`).toEqual([]);
  });

  test("FAQ toggles and all answers are in the DOM", async ({ page }) => {
    const errors = trackConsoleErrors(page);
    await page.goto("/");
    await page.waitForLoadState("networkidle");

    // All seven answers (six original + the comparison item) live in the DOM
    // unconditionally (L5) — visibility is CSS, so crawlers and no-JS readers
    // see every answer.
    const answers = page.locator(".marketing .faq-a");
    await expect(answers).toHaveCount(7);

    // Exactly one is visible on load (the first item starts open).
    const visible = page.locator(".marketing .faq-item.is-open .faq-a");
    await expect(visible).toHaveCount(1);
    await expect(answers.first()).toBeVisible();

    // Clicking the third question reveals its answer and closes the first.
    const questions = page.locator(".marketing .faq-item");
    await questions.nth(2).click();
    await expect(answers.nth(2)).toBeVisible();
    await expect(answers.first()).toBeHidden();

    expect(errors, `console errors on FAQ interaction:\n${errors.join("\n")}`).toEqual([]);
  });

  test("returning to / via the demo banner link works", async ({ page }) => {
    const errors = trackConsoleErrors(page);
    await page.goto("/demo/");
    await page.waitForLoadState("networkidle");

    const back = page.getByRole("link", { name: /Back to gettidings\.com/i });
    await expect(back).toBeVisible();
    await back.click();
    await page.waitForLoadState("networkidle");

    await expect(page).toHaveURL(/\/$/);
    await expect(
      page.getByRole("heading", { name: /Your spending,\s*delivered\./i, level: 1 })
    ).toBeVisible();

    expect(errors, `console errors on demo→marketing return:\n${errors.join("\n")}`).toEqual([]);
  });
});
