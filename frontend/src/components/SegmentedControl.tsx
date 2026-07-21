import { cn } from "@/lib/utils";

interface SegmentedControlProps<T extends string> {
  options: { value: T; label: string }[];
  value: T;
  onChange: (v: T) => void;
  ariaLabel: string;
}

/** L13 — the one segmented control. Extracted verbatim from the Summary
 * page's ViewToggle (rounded-md container, rounded-[5px] segments,
 * aria-pressed); consumed for Trend/Flow and, later, Budgets YTD/Monthly. */
export function SegmentedControl<T extends string>({
  options,
  value,
  onChange,
  ariaLabel,
}: SegmentedControlProps<T>) {
  const base =
    "rounded-[5px] px-2.5 py-1 text-xs font-medium transition-colors focus-visible:outline-none focus-visible:ring-1 focus-visible:ring-ring";
  const inactive = "text-fg-muted hover:text-fg";
  const active = "bg-accent text-accent-foreground";
  return (
    <div
      role="group"
      aria-label={ariaLabel}
      className="inline-flex items-center rounded-md border border-input bg-background p-0.5"
    >
      {options.map((opt) => (
        <button
          key={opt.value}
          type="button"
          aria-pressed={value === opt.value}
          className={cn(base, value === opt.value ? active : inactive)}
          onClick={() => onChange(opt.value)}
        >
          {opt.label}
        </button>
      ))}
    </div>
  );
}
