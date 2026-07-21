import { Sun, Moon, Monitor } from "lucide-react";
import {
  Select,
  SelectContent,
  SelectItem,
  SelectTrigger,
  SelectValue,
} from "@/components/ui/select";
import { cn } from "@/lib/utils";
import { DATE_FORMATS, HEADLINE_VARIANTS, usePreferences } from "@/stores/preferences";
import { useTheme, PALETTES } from "@/stores/theme";

const themeOptions = [
  { value: "light" as const, label: "Light", icon: Sun },
  { value: "dark" as const, label: "Dark", icon: Moon },
  { value: "system" as const, label: "System", icon: Monitor },
];

export function AppearanceSection() {
  const { mode, setMode, palette, setPalette } = useTheme();
  const dateFormat = usePreferences((s) => s.dateFormat);
  const setDateFormat = usePreferences((s) => s.setDateFormat);
  const headlineVariant = usePreferences((s) => s.headlineVariant);
  const setHeadlineVariant = usePreferences((s) => s.setHeadlineVariant);

  return (
    <section className="space-y-5">
      <div className="space-y-2">
        <p className="text-sm text-muted-foreground">Mode</p>
        <div role="group" aria-label="Color mode" className="flex flex-wrap gap-2">
          {themeOptions.map((opt) => (
            <button
              key={opt.value}
              onClick={() => setMode(opt.value)}
              aria-pressed={mode === opt.value}
              className={cn(
                "flex items-center gap-2 rounded-lg border px-4 py-2.5 text-sm font-medium transition-colors",
                mode === opt.value
                  ? "border-primary bg-accent text-foreground ring-1 ring-primary/60"
                  : "border-border/50 hover:bg-accent"
              )}
            >
              <opt.icon className="h-4 w-4" />
              {opt.label}
            </button>
          ))}
        </div>
      </div>

      <div className="space-y-2">
        <p className="text-sm text-muted-foreground">Palette</p>
        <div
          role="group"
          aria-label="Color palette"
          className="grid grid-cols-2 gap-2 sm:flex sm:flex-wrap"
        >
          {PALETTES.map((opt) => (
            <button
              key={opt.id}
              onClick={() => setPalette(opt.id)}
              aria-pressed={palette === opt.id}
              className={cn(
                "flex items-center gap-2 rounded-lg border px-4 py-2.5 text-sm font-medium transition-colors",
                palette === opt.id
                  ? "border-primary bg-accent text-foreground ring-1 ring-primary/60"
                  : "border-border/50 hover:bg-accent"
              )}
            >
              <span className="flex h-4 overflow-hidden rounded border border-border/50">
                {opt.chips.map((c, i) => (
                  <span
                    key={i}
                    className="h-full w-3"
                    style={{ backgroundColor: c }}
                    aria-hidden="true"
                  />
                ))}
              </span>
              {opt.label}
            </button>
          ))}
        </div>
      </div>

      <div className="space-y-2">
        <p className="text-sm text-muted-foreground">Headline style</p>
        <div role="group" aria-label="Headline style" className="grid gap-2 sm:grid-cols-2">
          {HEADLINE_VARIANTS.map((opt) => (
            <button
              key={opt.id}
              onClick={() => setHeadlineVariant(opt.id)}
              aria-pressed={headlineVariant === opt.id}
              className={cn(
                "flex flex-col items-start gap-1 rounded-lg border px-4 py-2.5 text-left transition-colors",
                headlineVariant === opt.id
                  ? "border-primary bg-accent text-foreground ring-1 ring-primary/60"
                  : "border-border/50 hover:bg-accent"
              )}
            >
              <span className="text-sm font-medium">{opt.label}</span>
              <span className="text-xs text-muted-foreground">{opt.description}</span>
            </button>
          ))}
        </div>
      </div>

      <div className="space-y-2">
        <p className="text-sm text-muted-foreground">Date format</p>
        <Select value={dateFormat} onValueChange={(v) => setDateFormat(v as typeof dateFormat)}>
          <SelectTrigger className="w-auto min-w-[240px]" aria-label="Date format">
            <SelectValue />
          </SelectTrigger>
          <SelectContent>
            {DATE_FORMATS.map((opt) => (
              <SelectItem key={opt.id} value={opt.id}>
                <span className="flex items-baseline gap-2">
                  <span>{opt.label}</span>
                  <span className="text-xs text-muted-foreground">{opt.sample}</span>
                </span>
              </SelectItem>
            ))}
          </SelectContent>
        </Select>
      </div>
    </section>
  );
}
