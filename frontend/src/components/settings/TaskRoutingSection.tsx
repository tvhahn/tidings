import { type ReactNode } from "react";
import {
  effortItemsFor,
  modelItemsFor,
  selectValue,
  storedValue,
} from "@/components/settings/aiRoutingOptions";
import { SettingsSectionHeader } from "@/components/settings/SettingsSectionHeader";
import { Input } from "@/components/ui/input";
import {
  Select,
  SelectContent,
  SelectItem,
  SelectTrigger,
  SelectValue,
} from "@/components/ui/select";
import { Switch } from "@/components/ui/switch";
import { useConfig, useUpdateConfig } from "@/hooks/useConfig";
import type { AiProvider, CategorizationProvider, ReasoningEffort } from "@/types/api";

type ProviderOption = { value: string; label: string };

type RoutingRowProps = {
  title: string;
  description: string;
  providerOptions: ProviderOption[];
  /** Provider value → whether its connection is ready. Unready = disabled option. */
  availability: Record<string, boolean>;
  provider: string;
  model: string | null;
  effort: string | null;
  disabled: boolean;
  onProviderChange: (value: string) => void;
  onModelChange: (value: string | null) => void;
  onEffortChange: (value: string | null) => void;
  children?: ReactNode;
};

function RoutingRow({
  title,
  description,
  providerOptions,
  availability,
  provider,
  model,
  effort,
  disabled,
  onProviderChange,
  onModelChange,
  onEffortChange,
  children,
}: RoutingRowProps) {
  const modelItems = modelItemsFor(provider, model);
  const effortItems = effortItemsFor(provider, effort);

  return (
    <div className="rounded-lg border border-border/50 p-3 space-y-3">
      <div className="space-y-0.5">
        <p className="text-sm font-medium">{title}</p>
        <p className="text-xs text-muted-foreground">{description}</p>
      </div>
      <div className="flex flex-wrap gap-3">
        <div className="space-y-1">
          <span className="block text-xs text-muted-foreground">Provider</span>
          <Select value={provider} onValueChange={onProviderChange} disabled={disabled}>
            <SelectTrigger className="w-[200px]" aria-label={`${title} provider`}>
              <SelectValue />
            </SelectTrigger>
            <SelectContent>
              {providerOptions.map((opt) => {
                const ready = availability[opt.value] ?? false;
                return (
                  <SelectItem key={opt.value} value={opt.value} disabled={!ready}>
                    <span className="flex items-center gap-2">
                      {opt.label}
                      {!ready && (
                        <span className="text-xs text-muted-foreground">Set up in Connections</span>
                      )}
                    </span>
                  </SelectItem>
                );
              })}
            </SelectContent>
          </Select>
        </div>

        {modelItems && (
          <div className="space-y-1">
            <span className="block text-xs text-muted-foreground">Model</span>
            <Select
              value={selectValue(model)}
              onValueChange={(v) => onModelChange(storedValue(v))}
              disabled={disabled}
            >
              <SelectTrigger className="w-[240px]" aria-label={`${title} model`}>
                <SelectValue />
              </SelectTrigger>
              <SelectContent>
                {modelItems.map((item) => (
                  <SelectItem key={item.value} value={item.value}>
                    {item.label}
                  </SelectItem>
                ))}
              </SelectContent>
            </Select>
          </div>
        )}

        {effortItems && (
          <div className="space-y-1">
            <span className="block text-xs text-muted-foreground">Reasoning effort</span>
            <Select
              value={selectValue(effort)}
              onValueChange={(v) => onEffortChange(storedValue(v))}
              disabled={disabled}
            >
              <SelectTrigger className="w-[160px]" aria-label={`${title} reasoning effort`}>
                <SelectValue />
              </SelectTrigger>
              <SelectContent>
                {effortItems.map((item) => (
                  <SelectItem key={item.value} value={item.value}>
                    {item.label}
                  </SelectItem>
                ))}
              </SelectContent>
            </Select>
          </div>
        )}
      </div>
      {children}
    </div>
  );
}

export function TaskRoutingSection() {
  const { data: config } = useConfig();
  const updateConfig = useUpdateConfig();

  const disabled = updateConfig.isPending;

  // A provider is routable once its connection is ready. Codex counts either a
  // signed-in CLI or a connected ChatGPT account; "disabled" is always allowed.
  const availability: Record<string, boolean> = {
    disabled: true,
    openai: config?.openai_enabled ?? false,
    claude_cli: config?.claude_cli_available ?? false,
    codex: (config?.codex_available ?? false) || (config?.chatgpt_oauth_connected ?? false),
    gemini_cli: config?.gemini_cli_available ?? false,
  };

  const providerOptions: ProviderOption[] = [
    { value: "disabled", label: "Disabled" },
    { value: "openai", label: "OpenAI API" },
    { value: "claude_cli", label: "Claude Code" },
    { value: "codex", label: "OpenAI Codex" },
    { value: "gemini_cli", label: "Google Gemini" },
  ];

  const categorizationProviderOptions: ProviderOption[] = [
    { value: "disabled", label: "Disabled" },
    { value: "openai", label: "OpenAI API" },
    { value: "codex", label: "OpenAI Codex" },
  ];

  const dailyProvider = config?.daily_summary_provider ?? "disabled";
  const dailySummariesEnabled = config?.enable_daily_summaries ?? true;
  const scheduleTime = config?.daily_summary_schedule_time ?? "19:00";

  const handleDailySummariesToggle = (next: boolean) => {
    updateConfig.mutate({ enable_daily_summaries: next });
  };

  const handleScheduleTimeChange = (next: string) => {
    if (!/^([01]\d|2[0-3]):[0-5]\d$/.test(next)) return;
    updateConfig.mutate({ daily_summary_schedule_time: next });
  };

  return (
    <section className="space-y-3">
      <SettingsSectionHeader
        title="Task routing"
        infoHint={{
          label: "About task routing",
          content:
            "Each task picks its own provider, model, and reasoning effort. Leave a task on Disabled to skip it, or point it at any connected provider.",
        }}
      />
      <p className="text-sm text-muted-foreground">
        Route each task to a connected provider. Switching a task's provider resets its model and
        reasoning effort to that provider's default.
      </p>

      <RoutingRow
        title="Daily summaries"
        description="A short narrative for each day in your journal."
        providerOptions={providerOptions}
        availability={availability}
        provider={dailyProvider}
        model={config?.daily_summary_model ?? null}
        effort={config?.daily_summary_reasoning_effort ?? null}
        disabled={disabled}
        onProviderChange={(v) =>
          updateConfig.mutate({
            daily_summary_provider: v as AiProvider,
            daily_summary_model: null,
            daily_summary_reasoning_effort: null,
          })
        }
        onModelChange={(v) => updateConfig.mutate({ daily_summary_model: v })}
        onEffortChange={(v) =>
          updateConfig.mutate({ daily_summary_reasoning_effort: v as ReasoningEffort | null })
        }
      >
        {dailyProvider !== "disabled" && (
          <div className="space-y-3 border-t border-border/50 pt-3">
            <div className="flex flex-wrap items-center justify-between gap-3">
              <div className="min-w-0 flex-1 space-y-0.5">
                <p className="text-sm font-medium">Auto-generate daily journal summaries</p>
                <p className="text-xs text-muted-foreground">
                  When off, days aren't summarized automatically — you can still click Summarize on
                  any day to generate on demand. Monthly insights run independently of this setting.
                </p>
              </div>
              <Switch
                checked={dailySummariesEnabled}
                onCheckedChange={handleDailySummariesToggle}
                disabled={disabled}
                aria-label="Auto-generate daily journal summaries"
              />
            </div>
            {dailySummariesEnabled && (
              <div className="flex flex-wrap items-center justify-between gap-3">
                <div className="min-w-0 flex-1 space-y-0.5">
                  <p className="text-sm font-medium">Schedule time</p>
                  <p className="text-xs text-muted-foreground">
                    Generates today's summary at this time, in your local timezone. You can also
                    click Summarize on any day to generate on demand.
                  </p>
                </div>
                <Input
                  type="time"
                  id="settings-daily-summary-time"
                  aria-label="Daily summary schedule time"
                  value={scheduleTime}
                  onChange={(e) => handleScheduleTimeChange(e.target.value)}
                  disabled={disabled}
                  className="w-32"
                />
              </div>
            )}
          </div>
        )}
      </RoutingRow>

      <RoutingRow
        title="Monthly insights"
        description="The monthly spending briefing, written from your transactions."
        providerOptions={providerOptions}
        availability={availability}
        provider={config?.insights_provider ?? "disabled"}
        model={config?.insights_model ?? null}
        effort={config?.insights_reasoning_effort ?? null}
        disabled={disabled}
        onProviderChange={(v) =>
          updateConfig.mutate({
            insights_provider: v as AiProvider,
            insights_model: null,
            insights_reasoning_effort: null,
          })
        }
        onModelChange={(v) => updateConfig.mutate({ insights_model: v })}
        onEffortChange={(v) =>
          updateConfig.mutate({ insights_reasoning_effort: v as ReasoningEffort | null })
        }
      />

      <RoutingRow
        title="Categorization & email rescue"
        description="Suggests a category for new transactions, and reads emails no built-in parser can."
        providerOptions={categorizationProviderOptions}
        availability={availability}
        provider={config?.categorization_provider ?? "disabled"}
        model={config?.categorization_model ?? null}
        effort={config?.categorization_reasoning_effort ?? null}
        disabled={disabled}
        onProviderChange={(v) =>
          updateConfig.mutate({
            categorization_provider: v as CategorizationProvider,
            categorization_model: null,
            categorization_reasoning_effort: null,
          })
        }
        onModelChange={(v) => updateConfig.mutate({ categorization_model: v })}
        onEffortChange={(v) =>
          updateConfig.mutate({ categorization_reasoning_effort: v as ReasoningEffort | null })
        }
      />

      <RoutingRow
        title="Document parsing (statements and receipts)"
        description="Reads statement PDFs and receipts no built-in parser can. Amounts are verified before anything is saved."
        providerOptions={providerOptions}
        availability={availability}
        provider={config?.document_parsing_provider ?? "disabled"}
        model={config?.document_parsing_model ?? null}
        effort={config?.document_parsing_reasoning_effort ?? null}
        disabled={disabled}
        onProviderChange={(v) =>
          updateConfig.mutate({
            document_parsing_provider: v as AiProvider,
            document_parsing_model: null,
            document_parsing_reasoning_effort: null,
          })
        }
        onModelChange={(v) => updateConfig.mutate({ document_parsing_model: v })}
        onEffortChange={(v) =>
          updateConfig.mutate({ document_parsing_reasoning_effort: v as ReasoningEffort | null })
        }
      />
    </section>
  );
}
