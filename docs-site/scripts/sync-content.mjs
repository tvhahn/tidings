// Sync source markdown from /docs/ into Starlight's content collection.
// Source of truth stays in /docs/; this prepends Starlight frontmatter and
// strips the leading `# H1` so the page title isn't rendered twice.
// Re-run on every dev/build via package.json predev/prebuild.

import { readFileSync, writeFileSync, mkdirSync, existsSync } from 'node:fs';
import { dirname, resolve, relative, sep } from 'node:path';
import { fileURLToPath } from 'node:url';

const here = dirname(fileURLToPath(import.meta.url));
const repoRoot = resolve(here, '..', '..');
const outRoot = resolve(repoRoot, 'docs-site/src/content/docs');

const pages = [
	{
		src: 'docs/ARCHITECTURE.md',
		dest: 'architecture.md',
		title: 'Architecture',
		description: 'How Tidings turns bank emails into a transaction journal.',
	},
	{
		src: 'docs/guides/aws-deployment.md',
		dest: 'self-hosting/aws.md',
		title: 'AWS deployment',
		description: 'Build the Docker image and deploy the parser to AWS Lambda.',
	},
	{
		src: 'docs/guides/self-hosted-email-setup.md',
		dest: 'self-hosting/email.md',
		title: 'Email setup',
		description: 'Wire a dedicated Gmail inbox to the IMAP poller.',
	},
	{
		src: 'docs/guides/notifications-setup.md',
		dest: 'notifications.md',
		title: 'Notifications',
		description: 'Pick a push or SMS provider for new-transaction alerts.',
	},
	{
		src: 'docs/guides/configuration.md',
		dest: 'configuration.md',
		title: 'Configuration',
		description:
			'Every data/config.json key: type, default, behavior, and what lives in .env instead.',
	},
	{
		src: 'docs/guides/agent-access.md',
		dest: 'agent-access.md',
		title: 'Agent access',
		description: 'Issue a bearer token so a local agent can call the Tidings API.',
	},
	{
		src: 'docs/guides/add-a-parser.md',
		dest: 'add-a-parser.md',
		title: 'Add a parser',
		description: "Write a parser so Tidings recognizes a new bank's alert emails.",
	},
	{
		src: 'docs/guides/troubleshooting.md',
		dest: 'troubleshooting.md',
		title: 'Troubleshooting',
		description: 'Diagnose the failures self-hosters actually hit, most common first.',
	},
	{
		src: 'docs/guides/backup-and-restore.md',
		dest: 'backup-and-restore.md',
		title: 'Backup and restore',
		description: 'Back up the data directory, restore it, and leave cleanly.',
	},
	{
		src: 'docs/guides/upgrading.md',
		dest: 'upgrading.md',
		title: 'Upgrading',
		description: 'Pull-and-restart upgrades, automatic migrations, and rolling back.',
	},
	{
		src: 'docs/guides/faq.md',
		dest: 'faq.md',
		title: 'FAQ',
		description: 'Short answers on privacy, bank support, costs, and importing history.',
	},
	{
		src: 'docs/guides/email-to-s3-setup.md',
		dest: 'self-hosting/email-to-s3.md',
		title: 'Email-to-S3 setup',
		description:
			'Route bank alert emails into the S3 bucket the AWS Lambda watches, using SES, a verified domain, and a receipt rule.',
	},
	{
		src: 'docs/guides/s3-backup.md',
		dest: 's3-backup.md',
		title: 'S3 backup',
		description:
			'Mirror receipt attachments and statement PDFs to a bucket you own — the durability answer for the files the backup zip leaves out.',
	},
];

// repo-relative source path → site slug (e.g. 'docs/guides/agent-access.md' →
// '/agent-access/'). Used to turn cross-guide relative links into on-site links.
const slugBySrc = new Map(
	pages.map(({ src, dest }) => [
		src,
		'/' + dest.replace(/\.mdx?$/, '') + '/',
	]),
);

// Rewrite one markdown link target for the on-site context.
//   (a) https://docs.gettidings.com/<path>  → /<path>            (site-internal)
//   (b) relative link to a repo file, resolved against srcPath's dir:
//         - synced source → its site slug (+#anchor preserved)
//         - otherwise     → GitHub blob URL for the repo-relative path
//   (c) any other absolute URL, root-relative link, or bare anchor → untouched
function rewriteTarget(target, srcPath) {
	// (a) site-internal absolute → root-relative
	if (target.startsWith('https://docs.gettidings.com')) {
		return target.slice('https://docs.gettidings.com'.length) || '/';
	}
	// (c) other absolute URLs, protocol-relative, root-relative, or anchors
	if (/^([a-z][a-z0-9+.-]*:|\/\/|\/|#|mailto:)/i.test(target)) {
		return target;
	}
	// (b) relative link to a repo file
	const [path, anchor] = target.split('#');
	if (!path) return target; // pure anchor already handled above
	const abs = resolve(repoRoot, dirname(srcPath), path);
	const repoRel = relative(repoRoot, abs).split(sep).join('/');
	const hash = anchor ? `#${anchor}` : '';
	const slug = slugBySrc.get(repoRel);
	if (slug) return slug + hash;
	return `https://github.com/tvhahn/tidings/blob/main/${repoRel}${hash}`;
}

// Apply link rewriting to every markdown link target in the body. The guides use
// bare URLs inside fenced code blocks, never `](...)`, so a plain regex over link
// targets never touches code — no fence tracking needed.
function rewriteLinks(body, srcPath) {
	return body.replace(
		/\]\(([^)\s]+)\)/g,
		(_, target) => `](${rewriteTarget(target, srcPath)})`,
	);
}

// Directory holding the hand-drawn HTML figure snippets that replace ASCII
// diagrams on-site.
const figuresDir = resolve(repoRoot, 'docs-site/src/figures');

// Swap each `<!-- docs-site:figure:<name> -->` marker line for the contents of
// docs-site/src/figures/<name>.html (trimmed). The marker sits one blank line
// above an ASCII-diagram code fence; we replace ONLY the marker line, so the
// blank line + fence survive — the fence stays in the source (GitHub) and in
// llms.txt, while CSS (`.docs-figure + .expressive-code`) hides it on-site right
// after the injected figure. A missing snippet throws so the build fails loudly
// rather than shipping a page with a dangling marker.
function injectFigures(body, srcPath) {
	return body.replace(
		/^[ \t]*<!--\s*docs-site:figure:([a-z0-9-]+)\s*-->[ \t]*$/gm,
		(_, name) => {
			const file = resolve(figuresDir, `${name}.html`);
			if (!existsSync(file)) {
				throw new Error(
					`${srcPath}: figure marker "${name}" has no snippet at docs-site/src/figures/${name}.html`,
				);
			}
			return readFileSync(file, 'utf8').trim();
		},
	);
}

for (const { src, dest, title, description } of pages) {
	const raw = readFileSync(resolve(repoRoot, src), 'utf8');
	const stripped = raw.replace(/^\s*#\s.+\n+/, '');
	const rewritten = injectFigures(rewriteLinks(stripped, src), src);
	const escaped = (s) => s.replace(/"/g, '\\"');
	const frontmatter = `---\ntitle: "${escaped(title)}"\ndescription: "${escaped(description)}"\n---\n\n`;
	const target = resolve(outRoot, dest);
	mkdirSync(dirname(target), { recursive: true });
	writeFileSync(target, frontmatter + rewritten);
	console.log(`synced ${src} → docs-site/src/content/docs/${dest}`);
}
