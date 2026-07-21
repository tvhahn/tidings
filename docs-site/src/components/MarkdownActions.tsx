import { useState } from 'react';

interface Props {
	mdHref: string;
	markdown: string;
}

// The Clipboard API is gated on a secure context, so it is absent whenever the
// docs are read over plain http — a dev server reached at its LAN address, most
// often. `execCommand` is deprecated and synchronous, but it is the only copy
// path that still works there, so it backstops rather than replaces writeText.
function legacyCopy(text: string): boolean {
	const field = document.createElement('textarea');
	field.value = text;
	field.setAttribute('readonly', '');
	// Off-screen rather than hidden: `select()` is a no-op on a display:none
	// node, and `position: fixed` keeps selecting it from scrolling the page.
	field.style.cssText = 'position:fixed;top:-9999px;opacity:0';
	document.body.appendChild(field);

	const selection = document.getSelection();
	const restore = selection && selection.rangeCount > 0 ? selection.getRangeAt(0) : null;

	try {
		field.select();
		return document.execCommand('copy');
	} catch {
		return false;
	} finally {
		field.remove();
		// Leave whatever the reader had highlighted untouched.
		if (restore && selection) {
			selection.removeAllRanges();
			selection.addRange(restore);
		}
	}
}

export default function MarkdownActions({ mdHref, markdown }: Props) {
	const [copied, setCopied] = useState(false);
	const [error, setError] = useState(false);

	// `writeText` must run inside the click handler with no awaits before it,
	// or stricter browsers (Firefox/Safari, Chrome with extensions/policies)
	// drop transient user activation and throw NotAllowedError.
	async function handleCopy() {
		let ok = false;
		let reason: unknown;

		// Optional-chained: on a non-secure origin `navigator.clipboard` is
		// undefined outright, so a bare `.writeText` throws TypeError rather
		// than rejecting.
		if (navigator.clipboard?.writeText) {
			try {
				await navigator.clipboard.writeText(markdown);
				ok = true;
			} catch (err) {
				reason = err;
			}
		}
		if (!ok) ok = legacyCopy(markdown);

		if (ok) {
			setCopied(true);
			setError(false);
			setTimeout(() => setCopied(false), 1500);
		} else {
			// A silent catch here hid this bug through an entire investigation;
			// keep the reason reachable from the console.
			console.warn('[markdown-actions] copy failed', reason);
			setError(true);
			setTimeout(() => setError(false), 1500);
		}
	}

	return (
		<div className="markdown-actions" role="group" aria-label="Page markdown">
			<button type="button" onClick={handleCopy} className="markdown-action">
				<CopyIcon />
				<span>{error ? 'Failed' : copied ? 'Copied' : 'Copy page'}</span>
			</button>
			<a href={mdHref} className="markdown-action" target="_blank" rel="noopener">
				<MarkdownIcon />
				<span>View as Markdown</span>
			</a>
		</div>
	);
}

function CopyIcon() {
	return (
		<svg width="14" height="14" viewBox="0 0 24 24" fill="none" stroke="currentColor" strokeWidth="2" strokeLinecap="round" strokeLinejoin="round" aria-hidden="true">
			<rect x="9" y="9" width="13" height="13" rx="2" ry="2" />
			<path d="M5 15H4a2 2 0 0 1-2-2V4a2 2 0 0 1 2-2h9a2 2 0 0 1 2 2v1" />
		</svg>
	);
}

function MarkdownIcon() {
	return (
		<svg width="14" height="14" viewBox="0 0 24 24" fill="none" stroke="currentColor" strokeWidth="2" strokeLinecap="round" strokeLinejoin="round" aria-hidden="true">
			<path d="M14 2H6a2 2 0 0 0-2 2v16a2 2 0 0 0 2 2h12a2 2 0 0 0 2-2V8z" />
			<polyline points="14 2 14 8 20 8" />
		</svg>
	);
}
