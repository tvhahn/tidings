import { useConfig, useUpdateConfig } from "@/hooks/useConfig";
import { cn } from "@/lib/utils";

export function DataModeSection() {
  const { data: appConfig } = useConfig();
  const updateConfigMutation = useUpdateConfig();

  return (
    <section className="space-y-3">
      <div className="flex items-center justify-between rounded-lg border border-border/50 px-4 py-3">
        <div>
          <p className="text-sm font-medium">Demo Mode</p>
          <p className="text-xs text-muted-foreground">
            {appConfig?.demo_mode
              ? "Showing sample data. Exit to use your own data."
              : "Try the app with sample transactions and budgets."}
          </p>
        </div>
        <button
          onClick={() => updateConfigMutation.mutate({ demo_mode: !appConfig?.demo_mode })}
          disabled={updateConfigMutation.isPending}
          className={cn(
            "rounded-lg px-4 py-2 text-sm font-medium transition-colors",
            appConfig?.demo_mode
              ? "bg-status-warning/10 text-status-warning hover:bg-status-warning/15"
              : "border border-border/50 hover:bg-accent"
          )}
        >
          {appConfig?.demo_mode ? "Exit Demo" : "Try Demo"}
        </button>
      </div>
    </section>
  );
}
