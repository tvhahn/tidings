import { useIsDark } from "../hooks/useIsDark";

interface Props {
  src: string;
  /** Dark-theme twin of `src`, same dimensions. Omit and the light shot serves
   *  both themes. */
  srcDark?: string;
  alt: string;
  /** Address-bar text in the frame head, e.g. "tidings.local · journal". */
  label: string;
  width: number;
  height: number;
  className?: string;
  loading?: "eager" | "lazy";
}

/** A product screenshot in a minimal browser frame — the marketing art.
 *  The theme is a `.dark` class on <html>, not a media query, so the shot is
 *  picked in React rather than by <picture media>: the browser fetches only the
 *  plate the active theme applies, and the footer's picker swaps it live. */
export function BrowserShot({
  src,
  srcDark,
  alt,
  label,
  width,
  height,
  className,
  loading,
}: Props) {
  const isDark = useIsDark();
  return (
    <figure className={className ? `shot ${className}` : "shot"}>
      <div className="shot-head" aria-hidden="true">
        <span className="shot-dot" />
        <span className="shot-dot" />
        <span className="shot-dot" />
        <span className="shot-label">{label}</span>
      </div>
      <img
        src={isDark && srcDark ? srcDark : src}
        alt={alt}
        width={width}
        height={height}
        loading={loading ?? "lazy"}
        decoding="async"
      />
    </figure>
  );
}
