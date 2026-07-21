#!/usr/bin/env tsx
/**
 * Prerender the marketing landing into dist/index.html (locked decision L1,
 * contract C1). Runs from `frontend/` as the final step of `demo:build`,
 * after `vite build --mode demo` (client) and
 * `vite build --mode demo --ssr src/entry-server.tsx --outDir dist-ssr`.
 *
 * No browser: a Vite SSR bundle rendered with renderToStaticMarkup, injected
 * into the client-built HTML shell. React clears and re-renders the identical
 * tree on mount (L2 — replace, not hydrate), so the prerendered HTML serves
 * crawlers and first paint while interactivity arrives with JS as today.
 *
 * Every step is fatal on failure (non-zero exit) so a broken prerender fails
 * the build loudly rather than shipping a blank landing.
 *
 * Usage (from frontend/): tsx ../scripts/media/prerender_marketing.ts
 */

import { existsSync, readFileSync, rmSync, writeFileSync } from "node:fs";
import { resolve } from "node:path";
import { pathToFileURL } from "node:url";

// cwd is frontend/ (invoked as the last step of the frontend demo:build chain).
const frontendRoot = process.cwd();

function fail(msg: string): never {
  console.error(`prerender_marketing: ${msg}`);
  process.exit(1);
}

// Wrapped in main() (not top-level await) so tsx can transform this repo-root
// script under either CJS or ESM resolution.
async function main(): Promise<void> {
  // 1. Render the marketing tree from the SSR bundle.
  const ssrEntry = resolve(frontendRoot, "dist-ssr/entry-server.js");
  if (!existsSync(ssrEntry)) {
    fail(`SSR bundle not found at ${ssrEntry} — did the --ssr build step run?`);
  }
  const mod: { render?: () => string } = await import(pathToFileURL(ssrEntry).href);
  if (typeof mod.render !== "function") {
    fail("dist-ssr/entry-server.js does not export a render() function");
  }
  const html = mod.render();

  // 2. Inject into the client-built shell's single empty root.
  const indexPath = resolve(frontendRoot, "dist/index.html");
  if (!existsSync(indexPath)) fail(`dist/index.html not found at ${indexPath}`);
  const shell = readFileSync(indexPath, "utf8");
  const rootMatches = shell.match(/<div id="root"><\/div>/g) ?? [];
  if (rootMatches.length !== 1) {
    fail(`expected exactly one empty <div id="root"></div>, found ${rootMatches.length}`);
  }
  const injected = shell.replace('<div id="root"></div>', `<div id="root">${html}</div>`);

  // 3. Content markers — prove the tree rendered (L5 FAQ answer, L7 item, CTA, h1).
  const markers = [
    "<h1",
    "Five Canadian institutions",
    "How is Tidings different",
    "Explore the demo",
  ];
  for (const marker of markers) {
    if (!html.includes(marker)) fail(`injected HTML is missing required marker: ${marker}`);
  }

  // 4. Asset-URL parity (Trap 6). Every /assets/… URL the render emits (via src
  //    or srcset) must resolve to a real file under dist/assets/ — Vite hashes
  //    are content-derived so the SSR and client builds should agree; assert it.
  const assetUrls = new Set<string>();
  for (const m of html.matchAll(/(?:src|srcset)="([^"]*)"/g)) {
    const attr = m[1];
    if (!attr) continue;
    // srcset is a comma-separated list of "url descriptor" pairs; src is one url.
    for (const part of attr.split(",")) {
      const url = part.trim().split(/\s+/)[0];
      if (url && url.startsWith("/assets/")) assetUrls.add(url);
    }
  }
  const missing: string[] = [];
  for (const url of assetUrls) {
    const filePath = resolve(frontendRoot, "dist", url.replace(/^\//, ""));
    if (!existsSync(filePath)) missing.push(url);
  }
  if (missing.length > 0) {
    fail(`injected asset URLs have no matching file under dist/:\n  ${missing.join("\n  ")}`);
  }

  // 5. Persist, clean up the SSR bundle, report.
  writeFileSync(indexPath, injected);
  rmSync(resolve(frontendRoot, "dist-ssr"), { recursive: true, force: true });
  console.log(
    `prerender_marketing: injected ${Buffer.byteLength(html, "utf8")} bytes into dist/index.html ` +
      `(${assetUrls.size} asset URLs verified)`
  );
}

main().catch((err: unknown) => {
  console.error(err);
  process.exit(1);
});
