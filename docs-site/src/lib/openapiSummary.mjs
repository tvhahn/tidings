// Summarize a parsed OpenAPI spec into endpoint groups and machine-readable
// markdown. Pure functions — no fs, no network; callers pass the parsed spec.
//
// One module feeds all three machine surfaces (L8): the markdown shadow route
// (`entryToMarkdown.ts` → /api.md), the llms generator (`generate-llms-txt.mjs`
// → llms-full.txt), and the on-page `<details>` index (`ApiEndpointIndex.astro`).
// They MUST share this module or api.md and llms-full.txt silently drift (Trap 5).

const METHODS = ['get', 'put', 'post', 'delete', 'patch'];

/**
 * @param {any} spec Parsed OpenAPI document.
 * @returns {{ tag: string, endpoints: { method: string, path: string, summary: string }[] }[]}
 */
export function endpointGroups(spec) {
	const paths = spec?.paths ?? {};

	// Collect endpoints in path key order, method order, tagging each one.
	const byTag = new Map();
	const encounterOrder = [];
	for (const [path, ops] of Object.entries(paths)) {
		if (!ops) continue;
		for (const method of METHODS) {
			const op = ops[method];
			if (!op) continue;
			const tag = op.tags?.[0] ?? 'untagged';
			const summary = op.summary ?? op.operationId ?? '';
			if (!byTag.has(tag)) {
				byTag.set(tag, []);
				encounterOrder.push(tag);
			}
			byTag.get(tag).push({ method: method.toUpperCase(), path, summary });
		}
	}

	// Group order: declared `spec.tags` order first (only tags that have
	// endpoints), then any unseen tags in first-encounter order.
	const declared = (spec?.tags ?? [])
		.map((t) => t?.name)
		.filter((name) => byTag.has(name));
	const seen = new Set(declared);
	const rest = encounterOrder.filter((tag) => !seen.has(tag));

	return [...declared, ...rest].map((tag) => ({
		tag,
		endpoints: byTag.get(tag),
	}));
}

/**
 * @param {any} spec Parsed OpenAPI document.
 * @returns {string} Machine-readable markdown summary of the API.
 */
export function openapiToMarkdown(spec) {
	const lines = [
		'# API reference',
		'',
		'> Versioned /api/v1/ routes with a unified error shape. Full machine-readable',
		'> schema: /openapi.json (OpenAPI 3.1).',
		'',
	];
	for (const { tag, endpoints } of endpointGroups(spec)) {
		lines.push(`## ${tag}`, '');
		for (const { method, path, summary } of endpoints) {
			lines.push(
				summary
					? `- \`${method} ${path}\` — ${summary}`
					: `- \`${method} ${path}\``,
			);
		}
		lines.push('');
	}
	return lines.join('\n');
}
