// Copy /openapi.json into docs-site/public/ so Scalar can fetch it at /openapi.json.
// CI already drift-checks the source via `make verify-openapi`, so the copy is
// safe to be a one-way snapshot. Re-run via package.json predev/prebuild.

import { copyFileSync, mkdirSync } from 'node:fs';
import { dirname, resolve } from 'node:path';
import { fileURLToPath } from 'node:url';

const here = dirname(fileURLToPath(import.meta.url));
const src = resolve(here, '..', '..', 'openapi.json');
const dest = resolve(here, '..', 'public', 'openapi.json');

mkdirSync(dirname(dest), { recursive: true });
copyFileSync(src, dest);
console.log(`copied ${src} → ${dest}`);
