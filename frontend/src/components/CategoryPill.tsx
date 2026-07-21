import { forwardRef, type ButtonHTMLAttributes, type ReactNode } from "react";
import { cn } from "@/lib/utils";

interface CategoryPillProps extends Omit<ButtonHTMLAttributes<HTMLButtonElement>, "children"> {
  children: ReactNode;
  /** Status-warning tinted variant for over-budget / needs-attention rows. */
  warn?: boolean;
  /** When true, renders the small triangle chevron after the label. */
  chevron?: boolean;
}

/** Soft pill — Tidings category-picker affordance.
 *  Mirrors `.pill` in design_handoff_tidings/design_system/app.css. */
export const CategoryPill = forwardRef<HTMLButtonElement, CategoryPillProps>(function CategoryPill(
  { children, warn, chevron = true, className, type, ...rest },
  ref
) {
  return (
    <button
      ref={ref}
      type={type ?? "button"}
      className={cn(
        "inline-flex items-center gap-0.5 rounded-full border-0 px-2.5 py-[2.5px] text-[11.5px] font-medium leading-tight transition-colors",
        "focus-visible:outline-none focus-visible:ring-2 focus-visible:ring-ring/40",
        warn
          ? "bg-status-warning-muted text-status-warning hover:bg-status-warning-muted/80"
          : "bg-pill-bg text-pill-fg hover:bg-pill-bg-hover hover:text-fg-2",
        className
      )}
      {...rest}
    >
      <span className="truncate">{children}</span>
      {chevron && (
        <span
          aria-hidden
          className="ml-0.5 inline-block h-0 w-0 opacity-55"
          style={{
            borderLeft: "3px solid transparent",
            borderRight: "3px solid transparent",
            borderTop: "3px solid currentColor",
          }}
        />
      )}
    </button>
  );
});
