import { Check, ChevronsUpDown, Globe } from "lucide-react";
import { useMemo, useState } from "react";
import {
  Command,
  CommandEmpty,
  CommandInput,
  CommandItem,
  CommandList,
} from "@/components/ui/command";
import { Popover, PopoverContent, PopoverTrigger } from "@/components/ui/popover";
import { useConfig, useUpdateConfig } from "@/hooks/useConfig";
import { cn } from "@/lib/utils";

const FALLBACK_TIMEZONE = "America/Los_Angeles";

function getSupportedZones(): string[] {
  const supported = (Intl as { supportedValuesOf?: (key: string) => string[] }).supportedValuesOf?.(
    "timeZone"
  );
  return supported && supported.length > 0 ? supported : [FALLBACK_TIMEZONE, "UTC"];
}

function getBrowserTimezone(): string {
  try {
    return Intl.DateTimeFormat().resolvedOptions().timeZone || FALLBACK_TIMEZONE;
  } catch {
    return FALLBACK_TIMEZONE;
  }
}

export function TimezoneSection() {
  const { data: appConfig } = useConfig();
  const updateConfigMutation = useUpdateConfig();
  const [open, setOpen] = useState(false);

  const zones = useMemo(() => getSupportedZones(), []);
  const current = appConfig?.timezone ?? FALLBACK_TIMEZONE;
  const browserZone = useMemo(() => getBrowserTimezone(), []);
  const browserMatches = browserZone === current;

  const handleSelect = (zone: string) => {
    setOpen(false);
    if (zone === current) return;
    updateConfigMutation.mutate({ timezone: zone });
  };

  return (
    <section className="space-y-2">
      <div className="flex items-baseline justify-between gap-3">
        <p className="text-sm text-muted-foreground">Timezone</p>
        <p className="text-xs text-muted-foreground">Applies to everyone using this instance</p>
      </div>
      <div className="flex flex-wrap items-center gap-2">
        <Popover open={open} onOpenChange={setOpen}>
          <PopoverTrigger asChild>
            <button
              type="button"
              aria-label="Timezone"
              disabled={updateConfigMutation.isPending}
              className={cn(
                "flex w-[260px] items-center justify-between rounded-md border border-border/50 bg-transparent px-3 py-2 text-sm",
                "hover:bg-accent disabled:opacity-50"
              )}
            >
              <span className="truncate">{current}</span>
              <ChevronsUpDown className="ml-2 h-4 w-4 shrink-0 opacity-50" />
            </button>
          </PopoverTrigger>
          <PopoverContent className="w-[320px] p-0" align="start">
            <Command>
              <CommandInput placeholder="Search timezones" />
              <CommandList>
                <CommandEmpty>No timezone found.</CommandEmpty>
                {zones.map((zone) => (
                  <CommandItem key={zone} value={zone} onSelect={() => handleSelect(zone)}>
                    <Check
                      className={cn("mr-2 h-4 w-4", zone === current ? "opacity-100" : "opacity-0")}
                    />
                    {zone}
                  </CommandItem>
                ))}
              </CommandList>
            </Command>
          </PopoverContent>
        </Popover>
        <button
          type="button"
          onClick={() => handleSelect(browserZone)}
          disabled={browserMatches || updateConfigMutation.isPending}
          className={cn(
            "inline-flex items-center gap-1.5 rounded-md border border-border/50 px-3 py-2 text-sm",
            "hover:bg-accent disabled:opacity-50"
          )}
          title={
            browserMatches
              ? `Already set to your browser zone (${browserZone})`
              : `Set to your browser zone (${browserZone})`
          }
        >
          <Globe className="h-4 w-4" aria-hidden />
          Detect from browser
        </button>
      </div>
      <p className="text-xs text-muted-foreground">
        Used to bucket transactions into days and months. Changing this after ingesting transactions
        is safe, but past rows keep their original day grouping.
      </p>
    </section>
  );
}
