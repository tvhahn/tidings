import type { Page } from "@playwright/test";

/**
 * Attach console + page-error listeners and return the growing error array.
 *
 * Demo fixtures cover a fixed month window. The SPA probes adjacent months for
 * navigation chrome, and missing files surface as benign 404s on the resource
 * load. Those are filtered so specs stay focused on real React/runtime errors;
 * the filter is harmless for specs that never navigate outside the window.
 *
 * Shared by every e2e spec — call it before `page.goto(...)` and assert the
 * returned array is empty at the end of the test.
 */
export function trackConsoleErrors(page: Page): string[] {
  const errors: string[] = [];
  const isExpectedFixture404 = (text: string): boolean =>
    /Failed to load resource:.*\b404\b/.test(text);
  page.on("console", (msg) => {
    if (msg.type() !== "error") return;
    const text = msg.text();
    if (isExpectedFixture404(text)) return;
    errors.push(text);
  });
  page.on("pageerror", (err) => {
    errors.push(err.message);
  });
  return errors;
}
