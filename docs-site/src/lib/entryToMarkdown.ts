import { readFileSync } from 'node:fs';
import { resolve } from 'node:path';

import type { CollectionEntry } from 'astro:content';
import { mdxToMarkdown } from './mdxToMarkdown.mjs';
import { openapiToMarkdown } from './openapiSummary.mjs';

type DocEntry = CollectionEntry<'docs'>;

// Full endpoint summary for the API page's markdown shadow route (L8/C5).
// Reads the snapshot copy-openapi.mjs wrote into public/openapi.json (earlier in
// the same predev/prebuild chain); parsed once and cached at module scope.
// Resolved from process.cwd() (the docs-site root during `astro build`/`dev`)
// rather than import.meta.url: Astro bundles this module into
// dist/.prerender/chunks/, which relocates import.meta.url and breaks a
// module-relative path (the standalone scripts keep import.meta.url because they
// run un-bundled).
let _apiMarkdown: string | undefined;
function apiMarkdown(): string {
	if (_apiMarkdown === undefined) {
		const specPath = resolve(process.cwd(), 'public', 'openapi.json');
		const spec = JSON.parse(readFileSync(specPath, 'utf8'));
		_apiMarkdown = openapiToMarkdown(spec);
	}
	return _apiMarkdown;
}

export function entryToMarkdown(entry: DocEntry): string {
	if (entry.id === 'api') return apiMarkdown();

	const title = entry.data.title ?? entry.id;
	const description = entry.data.description ?? '';
	const header = description
		? `# ${title}\n\n> ${description}\n\n`
		: `# ${title}\n\n`;

	const body = entry.body ?? '';

	// `.md` entries are already clean markdown — pass them through untouched so
	// their output stays byte-identical (a remark round-trip would reflow them).
	// Only `.mdx` bodies carry the import statements and JSX that need stripping.
	if (!entry.filePath?.endsWith('.mdx')) return header + body;

	return header + mdxToMarkdown(body);
}
