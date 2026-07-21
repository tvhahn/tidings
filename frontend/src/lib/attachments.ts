/**
 * Pure display helpers for attachment metadata. Kept out of the dialog
 * components so they can be unit-tested without a render (frontend/CLAUDE.md:
 * "pull pure data transformations into src/lib/").
 */

/** True when the stored content-type is an image we can preview with <img>. */
export function isImageContentType(contentType: string): boolean {
  return contentType.startsWith("image/");
}

/** True when the attachment is a PDF (opened in a new tab rather than inlined). */
export function isPdfContentType(contentType: string): boolean {
  return contentType === "application/pdf";
}

/**
 * Human-readable file size. Binary units (1024) with at most one decimal, and
 * no trailing ".0" — 0 → "0 B", 1536 → "1.5 KB", 10 MB → "10 MB".
 */
export function formatBytes(bytes: number): string {
  if (!Number.isFinite(bytes) || bytes <= 0) return "0 B";
  const units = ["B", "KB", "MB", "GB"];
  let value = bytes;
  let unit = 0;
  while (value >= 1024 && unit < units.length - 1) {
    value /= 1024;
    unit += 1;
  }
  const rounded = unit === 0 ? value : Math.round(value * 10) / 10;
  return `${rounded} ${units[unit]}`;
}
