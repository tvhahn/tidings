// Sync the canonical Tidings brand-token CSS from /frontend/src/ into this
// package so its bare package imports (`@import "tailwindcss"`, `@plugin
// "@tailwindcss/typography"`) resolve against docs-site/node_modules. The
// deploy environment (Cloudflare Pages) installs only docs-site dependencies,
// so importing across the package boundary via a relative path fails there —
// resolution starts from frontend/src/, which has no node_modules.
// Source of truth stays in /frontend/src/; edit there, never the copies.
// Re-run on every dev/build via package.json predev/prebuild.

import { mkdirSync, readFileSync, writeFileSync } from 'node:fs';
import { dirname, resolve } from 'node:path';
import { fileURLToPath } from 'node:url';

const here = dirname(fileURLToPath(import.meta.url));
const repoRoot = resolve(here, '..', '..');
const outRoot = resolve(repoRoot, 'docs-site/src/styles/tidings-tokens');

// Destinations mirror the source layout so index.css's relative
// `@import "./styles/themes.css"` keeps resolving.
const files = [
	{ src: 'frontend/src/index.css', dest: 'index.css' },
	{ src: 'frontend/src/styles/themes.css', dest: 'styles/themes.css' },
];

// The frontend self-hosts its fonts via @fontsource imports at the top of
// index.css. This package has no @fontsource dependencies — the docs site
// registers its fonts through astro.config.mjs — so those imports are dropped
// on copy; the `--font-serif` token's "Source Serif 4 Variable" first entry
// falls through to the Astro-registered "Source Serif 4".
const isFontsourceImport = (line) => /^@import "@fontsource[-/]/.test(line.trim());

for (const { src, dest } of files) {
	const target = resolve(outRoot, dest);
	mkdirSync(dirname(target), { recursive: true });
	const css = readFileSync(resolve(repoRoot, src), 'utf8')
		.split('\n')
		.filter((line) => !isFontsourceImport(line))
		.join('\n');
	writeFileSync(target, css);
	console.log(`synced ${src} → docs-site/src/styles/tidings-tokens/${dest}`);
}
