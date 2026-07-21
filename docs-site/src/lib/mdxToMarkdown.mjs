// Turn raw MDX source into clean, readable markdown.
//
// Shared by two build-time consumers, so it lives in plain ESM rather than TS
// (`scripts/generate-llms-txt.mjs` runs under bare node, with no TS loader):
//   - src/lib/entryToMarkdown.ts  → the "Copy page" button + `<page>.md` routes
//   - scripts/generate-llms-txt.mjs → public/llms-full.txt
//
// Astro's `entry.body` for an .mdx file is the RAW MDX SOURCE — import
// statements, JSX tags and all. Handing that to an LLM (or a human hitting
// "Copy page") ships plumbing instead of writing, so we parse to mdast, drop
// the MDX-only nodes, and re-serialize.
//
// Unwrapping on the tree — rather than sweeping tags with a regex — is what
// keeps the inner text at the correct indentation. remark-mdx already strips
// the JSX indentation when it parses children, so tab-indented content inside
// <Card> comes back as paragraphs instead of an indented code block.
//
// Careful with wording here: Tailwind v4 scans this file for candidate class
// names without regard to syntax, so @tailwindcss/typography's class name (the
// one meaning "styled body text") must not appear even inside a comment — it
// makes the plugin emit its whole ~12.5kB ruleset into the CSS every docs page
// loads render-blocking, and nothing on this site uses that class.

import { unified } from 'unified';
import remarkParse from 'remark-parse';
import remarkGfm from 'remark-gfm';
import remarkMdx from 'remark-mdx';
import remarkStringify from 'remark-stringify';

/** Read a JSX string attribute. Expression values ({...}) are ignored. */
function attr(node, name) {
	const found = (node.attributes ?? []).find(
		(a) => a.type === 'mdxJsxAttribute' && a.name === name,
	);
	if (!found || typeof found.value !== 'string') return undefined;
	return found.value;
}

const text = (value) => ({ type: 'text', value });
const paragraph = (children) => ({ type: 'paragraph', children });

/**
 * Rewrite Starlight's semantic components into their closest markdown
 * equivalent. Returns replacement nodes, or `null` to fall back to a plain
 * unwrap (children spliced in place of the element).
 *
 * Anything user-visible — body text, titles, hrefs — must survive the trip.
 */
function componentToMarkdown(node, children) {
	switch (node.name) {
		// <Aside type="note" title="X"> → blockquote led by its title. The title
		// carries real meaning (quickstart's AI-categorization aside), so promote
		// it rather than drop it with the element.
		case 'Aside': {
			const title = attr(node, 'title') ?? attr(node, 'type');
			const body = title
				? [paragraph([{ type: 'strong', children: [text(title)] }]), ...children]
				: children;
			return [{ type: 'blockquote', children: body }];
		}

		// <Card title="X"> → heading + children.
		case 'Card': {
			const title = attr(node, 'title');
			if (!title) return null;
			return [
				{ type: 'heading', depth: 3, children: [text(title)] },
				...children,
			];
		}

		// <LinkCard title="X" description="Y" href="Z" /> has NO children — a bare
		// unwrap would erase it entirely. Rebuild it as a real markdown link.
		case 'LinkCard': {
			const title = attr(node, 'title');
			const href = attr(node, 'href');
			const description = attr(node, 'description');
			if (!title && !href) return null;
			const inline = [
				{ type: 'link', url: href ?? '', children: [text(title ?? href ?? '')] },
			];
			if (description) inline.push(text(` — ${description}`));
			return [{ type: 'listItem', spread: false, children: [paragraph(inline)] }];
		}

		// <Steps> wraps an ordered list; <CardGrid> is pure layout. Both unwrap.
		case 'Steps':
		case 'CardGrid':
			return null;

		default: {
			// Figure components (src/components/figures/) carry a `summary` prop —
			// their plain-text stand-in. Emit it as an italic line so llms.txt and
			// "Copy page" readers get the figure's content instead of silence.
			// Components without one (ThemedScreenshot) unwrap to nothing, as before.
			const summary = attr(node, 'summary');
			if (summary) {
				return [paragraph([{ type: 'emphasis', children: [text(summary)] }])];
			}
			return null;
		}
	}
}

/**
 * Walk the tree, dropping MDX plumbing and unwrapping JSX elements so the inner
 * content re-serializes as real markdown at the correct depth.
 */
function stripMdx(nodes, parentType = 'root') {
	const out = [];

	for (const node of nodes) {
		// `import ... from '@astrojs/starlight/components'` / exports.
		if (node.type === 'mdxjsEsm') continue;
		// `{expr}` — code, not content.
		if (node.type === 'mdxFlowExpression' || node.type === 'mdxTextExpression') {
			continue;
		}

		if (node.type === 'mdxJsxFlowElement' || node.type === 'mdxJsxTextElement') {
			const children = stripMdx(node.children ?? [], node.type);
			const replacement = componentToMarkdown(node, children);
			out.push(...(replacement ?? children));
			continue;
		}

		if (node.children) {
			out.push({ ...node, children: stripMdx(node.children, node.type) });
			continue;
		}

		out.push(node);
	}

	// Consecutive LinkCard list items collapse into one markdown list. Skipped
	// under a real list, whose own listItem children must not be re-wrapped.
	return parentType === 'list' ? out : groupListItems(out);
}

/** Wrap runs of loose `listItem` nodes (from LinkCard) in a real list. */
function groupListItems(nodes) {
	const out = [];
	let run = [];

	const flush = () => {
		if (run.length === 0) return;
		out.push({ type: 'list', ordered: false, spread: false, children: run });
		run = [];
	};

	for (const node of nodes) {
		if (node.type === 'listItem') {
			run.push(node);
			continue;
		}
		flush();
		out.push(node);
	}
	flush();
	return out;
}

// Sync-only pipeline: no async plugins, so `parse`/`stringify` are safe and both
// call sites (PageTitle.astro, [...slug].md.ts) stay synchronous.
const processor = unified()
	.use(remarkParse)
	.use(remarkGfm)
	.use(remarkMdx)
	.use(remarkStringify, {
		bullet: '-',
		fences: true,
		rule: '-',
		resourceLink: false,
	});

/**
 * @param {string} source raw MDX
 * @returns {string} clean markdown
 */
export function mdxToMarkdown(source) {
	const tree = processor.parse(source);
	return processor.stringify({ ...tree, children: stripMdx(tree.children ?? []) });
}
