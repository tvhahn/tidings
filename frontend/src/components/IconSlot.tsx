import { createElement, type ComponentType, type SVGProps } from "react";
import { cn } from "@/lib/utils";

interface IconSlotProps {
  icon: ComponentType<SVGProps<SVGSVGElement>>;
  /** Outer circle size in px (defaults to 30 — Tidings spec). */
  size?: number;
  /** Inner icon size in px (defaults to 15 — Tidings spec). */
  iconSize?: number;
  className?: string;
  "aria-label"?: string;
}

/** A 30×30 muted circular slot for transaction-row leading icons.
 *  Mirrors `.txn .slot` in design_handoff_tidings/design_system/app.css. */
export function IconSlot({
  icon,
  size = 30,
  iconSize = 15,
  className,
  "aria-label": ariaLabel,
}: IconSlotProps) {
  return (
    <span
      className={cn(
        "inline-flex shrink-0 items-center justify-center rounded-full bg-surface-muted text-fg-muted",
        className
      )}
      style={{ width: size, height: size }}
      aria-label={ariaLabel}
    >
      {createElement(icon, {
        width: iconSize,
        height: iconSize,
        "aria-hidden": ariaLabel ? undefined : true,
      })}
    </span>
  );
}
