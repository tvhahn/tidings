// Copy the repo-root INSTALL.md into docs-site/public/ so it is served at
// /install.md — the stable URL the "install by prompt" flow hands to an agent.
// The source is canon; this copy is a one-way snapshot, re-run via
// package.json predev/prebuild.

import { copyFileSync, mkdirSync } from 'node:fs';
import { dirname, resolve } from 'node:path';
import { fileURLToPath } from 'node:url';

const here = dirname(fileURLToPath(import.meta.url));
const src = resolve(here, '..', '..', 'INSTALL.md');
const dest = resolve(here, '..', 'public', 'install.md');

mkdirSync(dirname(dest), { recursive: true });
copyFileSync(src, dest);
console.log(`copied ${src} → ${dest}`);
