// Shadow `.md` routes — every docs page is also fetchable as raw markdown at
// `<page>.md`. Lets agents (and humans piping into ChatGPT/Claude) grab the
// source without scraping rendered HTML. Mirrors the pattern used on
// docs.anthropic.com.

import type { APIRoute, GetStaticPaths } from 'astro';
import { getCollection, type CollectionEntry } from 'astro:content';
import { entryToMarkdown } from '../lib/entryToMarkdown';

type DocEntry = CollectionEntry<'docs'>;

export const getStaticPaths: GetStaticPaths = async () => {
	const entries = await getCollection('docs');
	return entries.map((entry) => ({
		params: { slug: entry.id },
		props: { entry },
	}));
};

export const GET: APIRoute = ({ props }) => {
	const entry = props.entry as DocEntry;
	return new Response(entryToMarkdown(entry), {
		headers: {
			'Content-Type': 'text/markdown; charset=utf-8',
			'Cache-Control': 'public, max-age=300',
		},
	});
};
