// Generate /llms.txt and /llms-full.txt at build time, per llmstxt.org.
//
// - llms.txt: curated index pointing agents at the markdown shadow URLs
//   (`<page>.md`), grouped by sidebar section.
// - llms-full.txt: every page concatenated, for one-shot ingest.
//
// Run after sync-content.mjs so the synced docs are already in
// docs-site/src/content/docs/.

import { readFileSync, writeFileSync, readdirSync, statSync } from 'node:fs';
import { dirname, join, relative, resolve, sep } from 'node:path';
import { fileURLToPath } from 'node:url';

import { mdxToMarkdown } from '../src/lib/mdxToMarkdown.mjs';
import { openapiToMarkdown } from '../src/lib/openapiSummary.mjs';

const here = dirname(fileURLToPath(import.meta.url));
const docsRoot = resolve(here, '..', 'src', 'content', 'docs');
const publicRoot = resolve(here, '..', 'public');

const SITE_URL = 'https://docs.gettidings.com';
const SITE_TITLE = 'Tidings docs';
const SITE_SUMMARY =
	'A private finance journal built from the transaction emails you already receive. Self-hosted with Docker or AWS Lambda; data stays on your machine.';

// Mirror the sidebar order in astro.config.mjs so llms.txt sections match the
// human-facing nav. Each entry is { section, slug }; missing pages are skipped
// silently so this script tolerates docs being added/removed.
const sections = [
	{
		title: 'Welcome',
		slugs: ['index', 'quickstart', 'tour', 'switching'],
	},
	{
		title: 'Getting started',
		slugs: ['self-hosting/docker', 'self-hosting/email', 'notifications'],
	},
	{
		title: 'Using Tidings',
		slugs: [
			'using/how-it-works',
			'using/journal',
			'using/transactions',
			'using/categorization',
			'using/needs-review',
			'using/summary',
			'using/budgets',
			'using/insights',
			'using/merchants',
			'using/income-statement',
			'using/statements',
			'using/tax',
			'using/settings',
		],
	},
	{
		title: 'Running it',
		slugs: [
			'configuration',
			'backup-and-restore',
			'upgrading',
			'troubleshooting',
			'faq',
		],
	},
	{
		title: 'Advanced (AWS)',
		slugs: ['self-hosting/email-to-s3', 'self-hosting/aws', 's3-backup'],
	},
	{
		title: 'Contributing',
		slugs: ['add-a-parser'],
	},
	{
		title: 'Reference',
		slugs: ['architecture', 'agent-access', 'for-agents', 'agent-guide', 'api', 'guides'],
	},
];

function* walk(dir) {
	for (const name of readdirSync(dir)) {
		const full = join(dir, name);
		if (statSync(full).isDirectory()) yield* walk(full);
		else if (name.endsWith('.md') || name.endsWith('.mdx')) yield full;
	}
}

function parseFrontmatter(raw) {
	const match = raw.match(/^---\n([\s\S]*?)\n---\n?/);
	if (!match) return { data: {}, body: raw };
	const data = {};
	for (const line of match[1].split('\n')) {
		const m = line.match(/^([A-Za-z0-9_-]+):\s*(.*)$/);
		if (!m) continue;
		let value = m[2].trim();
		if (
			(value.startsWith('"') && value.endsWith('"')) ||
			(value.startsWith("'") && value.endsWith("'"))
		) {
			value = value.slice(1, -1);
		}
		data[m[1]] = value;
	}
	return { data, body: raw.slice(match[0].length) };
}

function loadEntries() {
	const entries = new Map();
	for (const file of walk(docsRoot)) {
		const slug = relative(docsRoot, file)
			.replace(/\.(md|mdx)$/, '')
			.split(sep)
			.join('/')
			// Normalize directory index files: `guides/index` → `guides`. Matches
			// how Starlight's docsLoader names entries (and our [...slug].md.ts
			// route). Top-level `index` stays as-is.
			.replace(/\/index$/, '');
		const raw = readFileSync(file, 'utf8');
		const { data, body } = parseFrontmatter(raw);
		entries.set(slug, {
			slug,
			title: data.title ?? slug,
			description: data.description ?? '',
			// `.mdx` bodies are raw MDX source; strip the imports and JSX so
			// llms-full.txt ships real markdown. `.md` bodies pass through, minus any
			// injected `<figure class="docs-figure">` blocks — those are site-only, and
			// the ASCII fence that follows carries the same content for text readers.
			body: file.endsWith('.mdx')
				? mdxToMarkdown(body)
				: body.replace(/<figure class="docs-figure"[\s\S]*?<\/figure>\s*/g, ''),
		});
	}
	return entries;
}

function buildLlmsTxt(entries) {
	const lines = [`# ${SITE_TITLE}`, '', `> ${SITE_SUMMARY}`, ''];
	for (const { title, slugs } of sections) {
		const items = slugs
			.map((slug) => entries.get(slug))
			.filter(Boolean);
		if (items.length === 0) continue;
		lines.push(`## ${title}`, '');
		for (const e of items) {
			const url = `${SITE_URL}/${e.slug}.md`;
			lines.push(
				e.description
					? `- [${e.title}](${url}): ${e.description}`
					: `- [${e.title}](${url})`,
			);
		}
		lines.push('');
	}
	return lines.join('\n');
}

function buildLlmsFullTxt(entries) {
	const ordered = [];
	for (const { slugs } of sections) {
		for (const slug of slugs) {
			const e = entries.get(slug);
			if (e) ordered.push(e);
		}
	}
	// Append any pages not listed in the sidebar so nothing is silently dropped.
	const listed = new Set(ordered.map((e) => e.slug));
	for (const e of entries.values()) {
		if (!listed.has(e.slug)) ordered.push(e);
	}

	const out = [`# ${SITE_TITLE}`, '', `> ${SITE_SUMMARY}`, ''];
	for (const e of ordered) {
		out.push(
			`---`,
			`# ${e.title}`,
			`Source: ${SITE_URL}/${e.slug}.md`,
			'',
		);
		if (e.description) out.push(`> ${e.description}`, '');
		out.push(e.body.trim(), '');
	}
	return out.join('\n');
}

const entries = loadEntries();

// Replace the API page's body with a full endpoint summary generated from the
// OpenAPI snapshot (L8/C5), so llms-full.txt lists real routes instead of the
// stub. Keyed on the `api` slug — NOT on the hand-maintained `sections` map
// (L14-g). Shares openapiSummary.mjs with the markdown shadow route so the two
// surfaces cannot drift (Trap 5).
const apiEntry = entries.get('api');
if (apiEntry) {
	const spec = JSON.parse(
		readFileSync(resolve(publicRoot, 'openapi.json'), 'utf8'),
	);
	apiEntry.body = openapiToMarkdown(spec);
}

const llms = buildLlmsTxt(entries);
const llmsFull = buildLlmsFullTxt(entries);

writeFileSync(resolve(publicRoot, 'llms.txt'), llms);
writeFileSync(resolve(publicRoot, 'llms-full.txt'), llmsFull);
console.log(
	`generated public/llms.txt (${entries.size} pages) and public/llms-full.txt`,
);
