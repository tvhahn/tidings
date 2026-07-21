import { useConfig } from "@/hooks/useConfig";

export function SystemStatusRow() {
  const { data: appConfig } = useConfig();
  if (!appConfig) return null;
  return (
    <p className="text-xs text-muted-foreground">
      Storage: {appConfig.storage} &middot; OpenAI:{" "}
      {appConfig.openai_enabled ? "connected" : "not configured"}
    </p>
  );
}
