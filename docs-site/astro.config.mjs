// @ts-check
import { defineConfig, fontProviders } from 'astro/config';
import starlight from '@astrojs/starlight';
import react from '@astrojs/react';
import tailwindcss from '@tailwindcss/vite';

/**
 * The `latin` subset range, copied verbatim from the `unicode-range` in each
 * fontsource package's own CSS (`source-serif-4/opsz.css`, `inter/wght.css`,
 * `jetbrains-mono/wght.css` — all three are identical). It is also the exact
 * range the previous Google-provider build emitted, so the subsetting behaviour
 * is unchanged. Deliberately latin-only: `<Font preload />` preloads every face
 * of a family and cannot filter by subset under the local provider, so adding
 * latin-ext would double the preloaded bytes that gate first paint for content
 * that is English throughout.
 * @type {[string, ...Array<string>]}
 */
const LATIN_SUBSET = [
	'U+0000-00FF',
	'U+0131',
	'U+0152-0153',
	'U+02BB-02BC',
	'U+02C6',
	'U+02DA',
	'U+02DC',
	'U+0304',
	'U+0308',
	'U+0329',
	'U+2000-206F',
	'U+20AC',
	'U+2122',
	'U+2191',
	'U+2193',
	'U+2212',
	'U+2215',
	'U+FEFF',
	'U+FFFD',
];

/**
 * Structural stand-in for the local provider's `Variant`, which Astro does not
 * export from a public subpath.
 * @typedef {{ weight: number, style: 'normal', src: [string], unicodeRange: [string, ...Array<string>] }} LocalVariant
 */

/**
 * One `@font-face` per weight, all pointing at the same variable woff2 — the
 * shape the Google provider used to emit, and what keeps Astro generating a
 * metrics-matched fallback per weight (notably Inter's separate `Arial Bold`
 * face at 700). The browser downloads the file once and instantiates the `wght`
 * axis per face.
 * @param {string} src Package-relative specifier of the variable woff2.
 * @param {[number, ...Array<number>]} weights Weights actually used by the site.
 * @returns {[LocalVariant, ...Array<LocalVariant>]}
 */
const variableWeights = (src, weights) => {
	const [first, ...rest] = weights;
	/** @param {number} weight @returns {LocalVariant} */
	const variant = (weight) => ({
		weight,
		style: 'normal',
		src: [src],
		unicodeRange: LATIN_SUBSET,
	});
	return [variant(first), ...rest.map(variant)];
};

export default defineConfig({
	site: 'https://docs.gettidings.com',
	server: { host: true },
	// Astro 6 deprecated `markdown.gfm`/`smartypants` and leaves them undefined;
	// the built-in `.md` processor still defaults them on, but Starlight 0.38's
	// bundled @astrojs/mdx 5.x reads `config.markdown.gfm` directly and treats
	// undefined as OFF — so `.mdx` pages silently lose GFM (tables render as
	// literal pipes). Set both explicitly until Starlight ships an Astro-6-aware
	// MDX integration; remove then.
	markdown: {
		gfm: true,
		smartypants: true,
	},
	vite: {
		plugins: [tailwindcss()],
	},
	// Fonts come from lockfile-pinned @fontsource-variable/* packages on disk and
	// are served from our own origin with content-hashed, immutable filenames —
	// no fonts.googleapis.com / fonts.gstatic.com request at runtime *or* at
	// build time. Three reasons:
	//   1. FOUT. The old <link> went to a third party, so the font sat behind a
	//      DNS + TLS + CSS round-trip and could not land before first paint:
	//      the wordmark painted its fallback and visibly reflowed (104.52px ->
	//      111.58px) when Source Serif 4 arrived. Served from our own origin and
	//      preloaded, it now arrives before first paint and the wordmark paints
	//      once at its final width.
	//      Astro additionally derives a metrics-matched fallback @font-face
	//      (size-adjust / ascent-override / descent-override, via capsize) that
	//      shrinks the reflow to ~1px if the swap does happen on a slow link.
	//      Caveat worth knowing before trusting it: that face is `src:
	//      local("Times New Roman")`, so it only applies where Times New Roman
	//      is actually installed (Windows/macOS). On a Linux box without the MS
	//      core fonts it is skipped and the stack falls through to Georgia, so
	//      the full ~7px reflow remains there on a slow connection.
	//   2. No third-party request from a project whose pitch is that your data
	//      does not leave your machine (docs/brand/positioning.md).
	//   3. Reproducible, offline builds. These used to be `fontProviders.google()`,
	//      which self-hosts at runtime but still fetches the woff2 from
	//      fonts.gstatic.com while building. That fetch failed intermittently on
	//      GitHub runners (`CannotFetchFontFile`) and took the docs-build job —
	//      and therefore the image publish it gates — down with it. The font
	//      bytes are now ordinary lockfile-pinned devDependencies, so the build
	//      makes no network request at all and the exact same bytes ship every
	//      time.
	// Families/weights mirror the token stacks in frontend/src/index.css. Only
	// `normal` is declared: the old Google URL asked for `opsz,wght` with no
	// `ital` axis, so today's `.tidings-hero h1 em` italic is synthesized —
	// wiring up one of the packages' `*-italic.woff2` files here would silently
	// change how the hero renders. Same reason the variants below point at
	// `latin` files only, and at the `wght`-axis build for Inter and JetBrains
	// Mono: those are the axes and subset Google was serving before. Verified
	// after the switch — every glyph-advance measurement on the docs home page
	// matches https://docs.gettidings.com exactly, wordmark included.
	// The generated CSS variables are mapped back onto the Tidings --font-*
	// tokens in src/styles/starlight-overrides.css (the token files themselves
	// are generated by scripts/sync-tokens.mjs and must not be hand-edited).
	fonts: [
		{
			name: 'Source Serif 4',
			cssVariable: '--font-source-serif-4',
			provider: fontProviders.local(),
			fallbacks: ['Georgia', 'Times New Roman', 'serif'],
			options: {
				// Source Serif 4 is optically sized, and the old Google URL asked for
				// `opsz,wght@8..60,...`. Pick the wrong file here and opsz pins to its
				// default, which renders visibly wider glyphs (the 20px wordmark
				// measured 119.39px instead of 111.58px). Fontsource ships three
				// flavours: `-wght-` (wght 200..900 only), `-standard-` and `-opsz-`
				// (both wght 200..900 + opsz 8..60). `-opsz-` is the one to use — it
				// keeps font-optical-sizing:auto picking opsz per size, as today.
				// Verify with fonttools if this is ever repointed:
				//   uv run --with 'fonttools[woff]' --with brotli python -c \
				//     "from fontTools.ttLib import TTFont; \
				//      print([(a.axisTag, a.minValue, a.maxValue) for a in \
				//      TTFont('<file>.woff2')['fvar'].axes])"
				//   -> [('wght', 200.0, 900.0), ('opsz', 8.0, 60.0)]
				variants: variableWeights(
					'@fontsource-variable/source-serif-4/files/source-serif-4-latin-opsz-normal.woff2',
					[400, 500, 600],
				),
			},
		},
		{
			name: 'Inter',
			cssVariable: '--font-inter',
			provider: fontProviders.local(),
			fallbacks: ['system-ui', 'sans-serif'],
			options: {
				// The `-wght-` build, not `-standard-`: Inter also has an opsz axis
				// (14..32), but the old Google URL never requested it, so opsz was
				// pinned to its default. `-wght-` is the flavour with opsz already
				// instanced out — swapping to `-standard-` would newly enable optical
				// sizing and change every sans glyph on the site.
				variants: variableWeights(
					'@fontsource-variable/inter/files/inter-latin-wght-normal.woff2',
					[400, 500, 600, 700],
				),
			},
		},
		{
			name: 'JetBrains Mono',
			cssVariable: '--font-jetbrains-mono',
			provider: fontProviders.local(),
			fallbacks: ['ui-monospace', 'Menlo', 'monospace'],
			options: {
				variants: variableWeights(
					'@fontsource-variable/jetbrains-mono/files/jetbrains-mono-latin-wght-normal.woff2',
					[400, 500],
				),
			},
		},
	],
	integrations: [
		react(),
		starlight({
			title: 'Tidings docs',
			description:
				'A private finance journal from the transaction emails you already receive.',
			logo: {
				src: './src/assets/logo.svg',
				alt: '',
			},
			components: {
				PageTitle: './src/overrides/PageTitle.astro',
				Hero: './src/overrides/Hero.astro',
				// Emits the self-hosted @font-face rules (see `fonts` above).
				Head: './src/overrides/Head.astro',
			},
			social: [
				{
					icon: 'github',
					label: 'GitHub',
					href: 'https://github.com/tvhahn/tidings',
				},
			],
			customCss: [
				'./src/styles/tidings.css',
				'./src/styles/starlight-overrides.css',
			],
			// Starlight toggles dark mode via [data-theme='dark']; Tidings tokens
			// activate via a `.dark` class. Mirror one to the other on every page.
			// The same script pins data-palette to warm-paper — the app's default
			// (DEFAULT_PALETTE in frontend/src/stores/theme.ts) — so the docs chrome
			// matches the product and the screenshots embedded in it. The docs site
			// has no palette picker; this is a constant, not a preference.
			head: [
				// Fonts are self-hosted via the top-level `fonts` config and
				// emitted by src/overrides/Head.astro — no <link> to Google here.
				//
				// Default social/OG image. Starlight already emits per-page
				// og:title/og:description/canonical and twitter:card
				// summary_large_image, but no image unless one is provided.
				// Absolute URL: unfurl scrapers do not resolve relative og:image
				// reliably. Card asset: regenerate with `pnpm og:images` (frontend/).
				{
					tag: 'meta',
					attrs: { property: 'og:image', content: 'https://docs.gettidings.com/og-image.png' },
				},
				{
					tag: 'meta',
					attrs: { name: 'twitter:image', content: 'https://docs.gettidings.com/og-image.png' },
				},
				{
					tag: 'script',
					content: `
						(function () {
							document.documentElement.dataset.palette = 'warm-paper';
							var sync = function () {
								var dark = document.documentElement.dataset.theme === 'dark';
								document.documentElement.classList.toggle('dark', dark);
							};
							sync();
							new MutationObserver(sync).observe(document.documentElement, {
								attributes: true,
								attributeFilter: ['data-theme'],
							});
						})();
					`,
				},
			],
			sidebar: [
				{ label: 'Welcome', slug: 'index' },
				{ label: 'Quickstart', slug: 'quickstart' },
				{ label: 'Tour', slug: 'tour' },
				{ label: 'Coming from another tool', slug: 'switching' },
				{
					label: 'Getting started',
					items: [
						{ label: 'Docker setup', slug: 'self-hosting/docker' },
						{ label: 'Set up email (IMAP)', slug: 'self-hosting/email' },
						{ label: 'Set up notifications', slug: 'notifications' },
					],
				},
				{
					label: 'Using Tidings',
					items: [
						{ label: 'How Tidings works', slug: 'using/how-it-works' },
						{ label: 'Journal', slug: 'using/journal' },
						{ label: 'Transactions', slug: 'using/transactions' },
						{ label: 'Categorization', slug: 'using/categorization' },
						{ label: 'Needs review', slug: 'using/needs-review' },
						{ label: 'Summary', slug: 'using/summary' },
						{ label: 'Budgets', slug: 'using/budgets' },
						{ label: 'Insights', slug: 'using/insights' },
						{ label: 'Merchants', slug: 'using/merchants' },
						{ label: 'Income statement', slug: 'using/income-statement' },
						{ label: 'Statements', slug: 'using/statements' },
						{ label: 'Tax receipts', slug: 'using/tax' },
						{ label: 'Settings', slug: 'using/settings' },
					],
				},
				{
					label: 'Running it',
					items: [
						{ label: 'Configuration', slug: 'configuration' },
						{ label: 'Backup and restore', slug: 'backup-and-restore' },
						{ label: 'Upgrading', slug: 'upgrading' },
						{ label: 'Troubleshooting', slug: 'troubleshooting' },
						{ label: 'FAQ', slug: 'faq' },
					],
				},
				{
					label: 'Advanced (AWS)',
					items: [
						{ label: 'Email-to-S3 setup', slug: 'self-hosting/email-to-s3' },
						{ label: 'Lambda deployment', slug: 'self-hosting/aws' },
						{ label: 'S3 backup', slug: 's3-backup' },
					],
				},
				{
					label: 'Contributing',
					items: [
						{ label: 'Add a parser', slug: 'add-a-parser' },
					],
				},
				{
					label: 'Reference',
					items: [
						{ label: 'Architecture', slug: 'architecture' },
						{ label: 'Agent access', slug: 'agent-access' },
						{ label: 'Tidings for agents', slug: 'for-agents' },
						{ label: 'API reference', slug: 'api' },
						{ label: 'More guides', slug: 'guides' },
					],
				},
			],
		}),
	],
});
