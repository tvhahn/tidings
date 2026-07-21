/** Tidings brand lockup: envelope-and-trend mark + serif wordmark.
 *
 * The SVG mark is inlined so its stroke inherits from `currentColor` (swap
 * `text-brand` to tint it for any palette). The wordmark uses the design
 * system serif and matches the sidebar header type scale.
 *
 * Source of truth for the SVG paths: docs/brand/assets/logo-mark-ink.svg.
 * Keep the <rect> and <path d="..."> values below in sync with that file. */
type WordmarkProps = {
  /** Optional size override for the mark (defaults to 20px). */
  size?: number;
  /** Additional className applied to the outer flex container. */
  className?: string;
};

export function Wordmark({ size = 20, className }: WordmarkProps) {
  const width = Math.round((size * 417) / 320);
  return (
    <div className={`flex items-center gap-2 ${className ?? ""}`.trim()}>
      <svg
        xmlns="http://www.w3.org/2000/svg"
        viewBox="0 0 417 320"
        width={width}
        height={size}
        fill="none"
        stroke="currentColor"
        strokeWidth={20}
        strokeLinecap="round"
        strokeLinejoin="round"
        aria-hidden
        className="text-brand shrink-0"
      >
        <rect x="29" y="24" width="355" height="273" rx="41" />
        <path d="M35 75 L103 129" />
        <path d="M91 242 C 131 212, 136 190, 164 190 C 192 190, 200 217, 228 217 C 256 217, 292 174, 332 144" />
      </svg>
      <span className="font-serif text-[19px] leading-none font-semibold tracking-[-0.015em] text-foreground">
        Tidings
      </span>
    </div>
  );
}
