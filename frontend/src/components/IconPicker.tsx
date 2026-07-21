import { Search } from "lucide-react";
import { createElement, useMemo, useState, type ComponentType } from "react";
import { Input } from "@/components/ui/input";
import { Popover, PopoverContent, PopoverTrigger } from "@/components/ui/popover";
import { ICON_CATALOG } from "@/lib/iconCatalog";
import { cn } from "@/lib/utils";

interface IconPickerProps {
  /** Current icon name, or null if using the default. */
  value: string | null;
  /** Icon component shown in the trigger circle. Resolved by the caller from override → default. */
  trigger: ComponentType<{ className?: string; "aria-hidden"?: boolean }>;
  /** Called with an icon name on select, or null to reset to default. */
  onChange: (iconName: string | null) => void;
  disabled?: boolean;
  /** Accessible label for the trigger button. */
  ariaLabel?: string;
  /** Size of the circle trigger. Defaults to "sm" (h-8 w-8). */
  size?: "sm" | "md";
}

export function IconPicker({
  value,
  trigger,
  onChange,
  disabled,
  ariaLabel = "Choose icon",
  size = "sm",
}: IconPickerProps) {
  const [open, setOpen] = useState(false);
  const [query, setQuery] = useState("");

  const filtered = useMemo(() => {
    const q = query.trim().toLowerCase();
    if (!q) return ICON_CATALOG;
    return ICON_CATALOG.map((group) => ({
      group: group.group,
      icons: group.icons.filter((i) => i.name.toLowerCase().includes(q)),
    })).filter((group) => group.icons.length > 0);
  }, [query]);

  const handleSelect = (iconName: string) => {
    onChange(iconName);
    setOpen(false);
    setQuery("");
  };

  const handleReset = () => {
    onChange(null);
    setOpen(false);
    setQuery("");
  };

  const circleClass = size === "sm" ? "h-8 w-8" : "h-10 w-10";

  return (
    <Popover
      open={disabled ? false : open}
      {...(disabled
        ? {}
        : {
            onOpenChange: (next: boolean) => {
              setOpen(next);
              if (!next) setQuery("");
            },
          })}
    >
      <PopoverTrigger asChild>
        <button
          type="button"
          aria-label={ariaLabel}
          disabled={disabled}
          className={cn(
            "shrink-0 flex items-center justify-center rounded-full bg-muted text-muted-foreground",
            "hover:bg-muted-foreground/15 hover:text-foreground transition-colors",
            "focus-visible:outline-none focus-visible:ring-2 focus-visible:ring-ring",
            "disabled:cursor-not-allowed disabled:opacity-50",
            circleClass
          )}
        >
          {createElement(trigger, { className: "h-4 w-4", "aria-hidden": true })}
        </button>
      </PopoverTrigger>
      <PopoverContent className="w-[320px] p-0" align="start">
        <div className="flex items-center border-b px-3">
          <Search className="mr-2 h-4 w-4 shrink-0 text-muted-foreground" />
          <Input
            placeholder="Search icons..."
            value={query}
            onChange={(e) => setQuery(e.target.value)}
            className="h-10 border-0 shadow-none focus-visible:ring-0 px-0"
          />
        </div>
        <div className="max-h-[360px] overflow-y-auto">
          {filtered.length === 0 && (
            <p className="py-6 text-center text-sm text-muted-foreground">No icon found.</p>
          )}
          {filtered.map((group) => (
            <div key={group.group} className="p-1">
              <div className="px-2 py-1.5 text-xs font-medium text-muted-foreground">
                {group.group}
              </div>
              <div className="grid grid-cols-8 gap-1 px-1 pb-1">
                {group.icons.map(({ name, icon: Icon }) => {
                  const selected = value === name;
                  return (
                    <button
                      key={name}
                      type="button"
                      onClick={() => handleSelect(name)}
                      aria-label={name}
                      title={name}
                      className={cn(
                        "flex items-center justify-center h-8 w-8 rounded-md transition-colors",
                        "hover:bg-accent hover:text-accent-foreground",
                        "focus-visible:outline-none focus-visible:ring-2 focus-visible:ring-ring",
                        selected
                          ? "bg-primary/15 text-primary ring-1 ring-primary/40"
                          : "text-foreground/80"
                      )}
                    >
                      <Icon className="h-4 w-4" aria-hidden />
                    </button>
                  );
                })}
              </div>
            </div>
          ))}
        </div>
        <div className="border-t p-2">
          <button
            type="button"
            onClick={handleReset}
            disabled={value === null}
            className={cn(
              "w-full rounded-md px-2 py-1.5 text-sm text-muted-foreground transition-colors",
              "hover:bg-muted hover:text-foreground",
              "disabled:opacity-40 disabled:cursor-not-allowed disabled:hover:bg-transparent"
            )}
          >
            Reset to default
          </button>
        </div>
      </PopoverContent>
    </Popover>
  );
}
