import type { ReactNode } from "react";

interface PageHeaderProps {
  title: string;
  subtitle?: string;
  actions?: ReactNode;
  /** Optional small-caps eyebrow above the title (e.g. "Journal · 23 days in"). */
  eyebrow?: ReactNode;
  /** Node rendered inline beside the title — for adjacent decorations
   * like status pulses or primary-action buttons that belong next to
   * the heading rather than in the trailing actions slot. */
  titleAdornment?: ReactNode;
}

export function PageHeader({ title, subtitle, actions, eyebrow, titleAdornment }: PageHeaderProps) {
  return (
    <div className="flex flex-col gap-4 sm:flex-row sm:items-start sm:justify-between">
      <div>
        {eyebrow && (
          <div className="mb-2 text-meta font-medium uppercase tracking-[0.06em] text-fg-muted">
            {eyebrow}
          </div>
        )}
        <div className="flex items-center gap-3">
          <h1 className="t-h1 text-fg">{title}</h1>
          {titleAdornment}
        </div>
        <span className="page-title-rule" aria-hidden />
        {subtitle && (
          <p className="mt-2 text-[15px] leading-relaxed text-fg-secondary">{subtitle}</p>
        )}
      </div>
      {actions && <div className="flex flex-wrap items-center gap-3">{actions}</div>}
    </div>
  );
}
