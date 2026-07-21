import { readFileSync } from "node:fs";
import { fileURLToPath } from "node:url";
import { test, expect, type Page } from "@playwright/test";
import { trackConsoleErrors } from "./helpers";

/**
 * Anti-rot smoke for the static hosted demo.
 * Every top-level route must render with zero console errors and at least
 * one page-specific content marker.
 *
 * Routes come from scripts/demo/demo_routes.json so this spec and the
 * deployed-site gate (scripts/checks/check_prod_surfaces.mjs) can never drift
 * apart — read via fs rather than `import` to keep the same file usable from
 * plain .mjs without a tsconfig resolveJsonModule dependency.
 */

const manifestPath = fileURLToPath(new URL("../../scripts/demo/demo_routes.json", import.meta.url));
const ROUTES: Array<{ path: string; marker: RegExp }> = (
  JSON.parse(readFileSync(manifestPath, "utf8")) as {
    routes: Array<{ path: string; marker: string }>;
  }
).routes.map(({ path, marker }) => ({ path, marker: new RegExp(marker, "i") }));

test.describe("demo smoke — all top-level pages", () => {
  for (const { path, marker } of ROUTES) {
    test(`${path} renders cleanly`, async ({ page }) => {
      const errors = trackConsoleErrors(page);
      await page.goto(path);
      await page.waitForLoadState("networkidle");
      // Banner visible
      await expect(page.getByText(/Demo mode/i).first()).toBeVisible();
      // Content marker present — scope to <main> so the sidebar nav (hidden
      // on mobile viewports, visible on desktop) never matches first.
      await expect(page.locator("main").getByText(marker).first()).toBeVisible({ timeout: 5000 });
      // No stale spinner after 2s
      await page.waitForTimeout(2000);
      const spinners = page.locator('[role="status"], [aria-busy="true"]');
      const count = await spinners.count();
      // Presence of the element is fine; it must not be visible after settle.
      for (let i = 0; i < count; i++) {
        await expect(spinners.nth(i))
          .not.toBeVisible()
          .catch(() => undefined);
      }
      expect(errors, `console errors on ${path}:\n${errors.join("\n")}`).toEqual([]);
    });
  }
});

test.describe("demo smoke — interaction persistence", () => {
  test("category edit on /demo/transactions persists across nav", async ({ page }) => {
    await page.goto("/demo/transactions?month=2026-03");
    await page.waitForLoadState("networkidle");
    // Open the first VISIBLE category picker (mobile + desktop blocks both
    // render to DOM; only one is visible per viewport).
    const firstPicker = page
      .getByRole("button", { name: "Edit category" })
      .filter({ visible: true })
      .first();
    if (await firstPicker.count()) {
      await firstPicker.click();
      const option = page.getByRole("option").nth(1);
      await option.click();
    }
    // Navigate away and back
    await page.goto("/demo/summary?month=2026-03");
    await page.waitForLoadState("networkidle");
    await page.goto("/demo/transactions?month=2026-03");
    await page.waitForLoadState("networkidle");
    // Smoke: page still renders without crash
    await expect(page.getByText(/Demo mode/i).first()).toBeVisible();
  });
});

test.describe("demo smoke — routing", () => {
  test("unknown route redirects to /demo with flash", async ({ page }) => {
    await page.goto("/demo/this-does-not-exist");
    await page.waitForLoadState("networkidle");
    // react-router strips the trailing slash when navigating to "/" inside the
    // basename, so the redirect lands on /demo rather than /demo/.
    await expect(page).toHaveURL(/\/demo\/?$/);
    await expect(page.getByText(/requires live data/i)).toBeVisible({ timeout: 3000 });
  });
});

test.describe("demo parity — persona attribution", () => {
  test("/demo/transactions surfaces >=3 distinct institutions, no Demo Bank", async ({ page }) => {
    await page.goto("/demo/transactions?month=2026-03");
    await page.waitForLoadState("networkidle");

    // Pull the Institution facet: read the underlying fixture rather than
    // trying to scrape the rendered table (which paginates / virtualizes on
    // mobile). Static fixtures live at /demo-data/ regardless of the SPA's
    // /demo basename — the path is set in src/lib/demoFetch.ts.
    const txs = await page.evaluate(async () => {
      const res = await fetch("/demo-data/transactions-2026-03.json");
      const doc: { transactions: Array<{ institution: string }> } = await res.json();
      return doc.transactions.map((t) => t.institution);
    });
    const unique = new Set(txs);
    expect(unique.size).toBeGreaterThanOrEqual(3);
    expect(unique.has("Demo Bank")).toBe(false);
  });
});

test.describe("demo parity — manual add overlay", () => {
  test("manual + Add dialog opens on /demo/transactions", async ({ page }) => {
    await page.goto("/demo/transactions?month=2026-03");
    await page.waitForLoadState("networkidle");

    // The trigger is a Plus icon-button rendered as the page-header adornment.
    const trigger = page
      .getByRole("button", { name: /add|new transaction|plus/i })
      .filter({ visible: true })
      .first();
    await trigger.click();

    // Dialog renders with Date / Amount / Company inputs.
    await expect(page.getByRole("dialog")).toBeVisible({ timeout: 3000 });
    await expect(page.getByLabel(/date/i).first()).toBeVisible();
  });
});

test.describe("demo coherence — one persona, one clock (2026-06-11 spec)", () => {
  test("/demo/merchants renders Mira merchants and zero old-persona tokens", async ({ page }) => {
    await page.goto("/demo/merchants");
    await page.waitForLoadState("networkidle");

    // Merchant intelligence is computed client-side from the summary fixtures —
    // a Mira merchant here proves the summary family is on the same persona as
    // the transaction family.
    await expect(
      page
        .locator("main")
        .getByText(/Liberty Market Lofts|Bell Fibe|Toronto Hydro|Rogers Wireless|Balzac/i)
        .first()
    ).toBeVisible({ timeout: 5000 });

    const text = await page.locator("main").innerText();
    for (const banned of ["Telus", "Safeway", "Chevron", "Landlord", "Demo Bank"]) {
      expect(text, `old-persona token "${banned}" on /demo/merchants`).not.toContain(banned);
    }
  });

  test("/demo/statements row click opens the self-hosted modal", async ({ page }) => {
    await page.goto("/demo/statements");
    await page.waitForLoadState("networkidle");

    const row = page
      .getByRole("button")
      .filter({ hasText: /RBC|CIBC|Simplii|Tangerine/ })
      .filter({ visible: true })
      .first();
    await row.click();

    const dialog = page.getByRole("dialog");
    await expect(dialog).toBeVisible({ timeout: 3000 });
    await expect(dialog.getByText(/self-hosted/i).first()).toBeVisible();
  });

  test("/demo/settings hides the Password and Sessions nav entries", async ({ page }) => {
    await page.goto("/demo/settings");
    await page.waitForLoadState("networkidle");

    await expect(page.getByRole("heading", { name: "Settings" })).toBeVisible();
    await expect(page.locator("main").getByText(/^Password$/)).toHaveCount(0);
    await expect(page.locator("main").getByText(/^Sessions$/)).toHaveCount(0);
  });

  test("/demo/settings/system renders the ingestion coverage rows", async ({ page }) => {
    const errors = trackConsoleErrors(page);
    await page.goto("/demo/settings/system");
    await page.waitForLoadState("networkidle");

    // The coverage fixture carries the demo institutions; at least one row
    // renders inside the ingestion-coverage section.
    await expect(page.locator("main").getByText(/^RBC$/).first()).toBeVisible({ timeout: 5000 });
    expect(errors, `console errors on /demo/settings/system:\n${errors.join("\n")}`).toEqual([]);
  });

  test("/demo/ journal reads as a month in progress as of Mar 19", async ({ page }) => {
    await page.goto("/demo/");
    await page.waitForLoadState("networkidle");

    await expect(
      page
        .locator("main")
        .getByText(/as of Mar 19/i)
        .first()
    ).toBeVisible({ timeout: 5000 });
    await expect(
      page
        .locator("main")
        .getByText(/\d+ days left/i)
        .first()
    ).toBeVisible();
    const daysLeft = await page
      .locator("main")
      .getByText(/\d+ days left/i)
      .first()
      .innerText();
    // Mar 19 of 31 days → 12 days left — anything else means the demo clock
    // leaked. (The commitment-aware headline replaced the "% of month elapsed"
    // sentence with the quiet "12 days left" caption fragment.)
    const match = /(\d+) days left/i.exec(daysLeft);
    const days = match?.[1] ? parseInt(match[1], 10) : NaN;
    expect(days).toBe(12);
  });
});

// ---------------------------------------------------------------------------
// Synthetic source emails (2026-06-11 spec, Phase 2). The mail icon on any row
// must open a plausible bank-notification email derived from the row — never
// the old "[Demo] … not available" stub.
// ---------------------------------------------------------------------------

/**
 * Pick a fixture transaction whose company is unique within the month and
 * whose name renders unchanged through the UI's titleCase (so the row can be
 * located by its visible text). Returns null only if the fixture is empty.
 */
async function pickEmailProbeRow(
  page: Page,
  fixturePath: string
): Promise<{ company: string; amount: number } | null> {
  return page.evaluate(async (path) => {
    const res = await fetch(path);
    const doc: unknown = await res.json();
    const txns: Array<{ company: string | null; amount: number }> = Array.isArray(
      (doc as { transactions?: unknown }).transactions
    )
      ? (doc as { transactions: Array<{ company: string | null; amount: number }> }).transactions
      : (
          doc as {
            days: Array<{ transactions: Array<{ company: string | null; amount: number }> }>;
          }
        ).days.flatMap((d) => d.transactions);
    const counts = new Map<string, number>();
    for (const t of txns) {
      if (t.company) counts.set(t.company, (counts.get(t.company) ?? 0) + 1);
    }
    const titleCaseStable = (s: string) =>
      s ===
      s
        .split(/\s+/)
        .map((w) => w.charAt(0).toUpperCase() + w.slice(1).toLowerCase())
        .join(" ");
    const candidate = txns.find(
      (t) => t.company && counts.get(t.company) === 1 && titleCaseStable(t.company)
    );
    return candidate ? { company: candidate.company as string, amount: candidate.amount } : null;
  }, fixturePath);
}

function formatCad(amount: number): string {
  return new Intl.NumberFormat("en-CA", { style: "currency", currency: "CAD" }).format(amount);
}

/**
 * Open the email dialog for the row showing `company`. Desktop surfaces show
 * the mail icon inline, but the action cluster is now lazy-mounted on first
 * row hover/focus — so we hover the merchant first to reveal it. Mobile tucks
 * the action behind the "Transaction actions" kebab popover.
 */
async function openEmailDialogFor(page: Page, company: string): Promise<void> {
  const merchant = page.locator("main").getByText(company).filter({ visible: true }).first();
  await merchant.scrollIntoViewIfNeeded();
  // Reveal the lazy desktop hover cluster (no-op on touch). Scope the button to
  // the merchant's own row so a different, already-revealed row (e.g. the demo
  // tour's first row) can't be picked instead.
  await merchant.hover();
  const row = merchant.locator(
    "xpath=ancestor::*[.//button[@aria-label='View original email' or @aria-label='Transaction actions']][1]"
  );
  const kebab = row
    .locator("button[aria-label='Transaction actions']")
    .filter({ visible: true })
    .first();
  if ((await kebab.count()) > 0) {
    // Mobile: actions live behind the kebab popover.
    await kebab.click();
    await page
      .locator("button[aria-label='View original email']")
      .filter({ visible: true })
      .first()
      .click();
    return;
  }
  // Desktop: the inline mail icon (auto-waits for the hover-revealed mount).
  await row
    .locator("button[aria-label='View original email']")
    .filter({ visible: true })
    .first()
    .click();
}

test.describe("demo realism — synthetic source emails", () => {
  test("transactions row mail icon opens a bank email with merchant and amount", async ({
    page,
  }) => {
    await page.goto("/demo/transactions?month=2026-03");
    await page.waitForLoadState("networkidle");

    const probe = await pickEmailProbeRow(page, "/demo-data/transactions-2026-03.json");
    expect(probe).not.toBeNull();
    if (!probe) return;

    await openEmailDialogFor(page, probe.company);

    const dialog = page.getByRole("dialog");
    await expect(dialog).toBeVisible({ timeout: 3000 });
    await expect(dialog).toContainText(probe.company);
    await expect(dialog).toContainText(formatCad(probe.amount));
    await expect(dialog).not.toContainText("not available in the demo");
  });

  test("journal row mail icon opens a bank email with merchant and amount", async ({ page }) => {
    await page.goto("/demo/");
    await page.waitForLoadState("networkidle");

    const probe = await pickEmailProbeRow(page, "/demo-data/journal-2026-03.json");
    expect(probe).not.toBeNull();
    if (!probe) return;

    await openEmailDialogFor(page, probe.company);

    const dialog = page.getByRole("dialog");
    await expect(dialog).toBeVisible({ timeout: 3000 });
    await expect(dialog).toContainText(probe.company);
    await expect(dialog).toContainText(formatCad(probe.amount));
    await expect(dialog).not.toContainText("not available in the demo");
  });
});

test.describe("demo parity — CSV export", () => {
  test("/demo/transactions export button triggers a CSV download", async ({ page }) => {
    // Range mode (from+to present) auto-expands the Advanced search panel and
    // runs the query, so the result table and Export button render without an
    // extra click. `q` seeds the free-text filter.
    await page.goto("/demo/transactions?from=2026-03&to=2026-03&q=Tim");
    await page.waitForLoadState("networkidle");

    const exportBtn = page
      .getByRole("button", { name: /export csv/i })
      .filter({ visible: true })
      .first();
    await expect(exportBtn).toBeVisible({ timeout: 5000 });

    const downloadPromise = page.waitForEvent("download", { timeout: 5000 });
    await exportBtn.click();
    const download = await downloadPromise;
    expect(download.suggestedFilename()).toMatch(/\.csv$/);
  });
});
