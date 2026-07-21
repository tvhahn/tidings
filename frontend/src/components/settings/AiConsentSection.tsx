import { SettingsSectionHeader } from "@/components/settings/SettingsSectionHeader";
import { Switch } from "@/components/ui/switch";
import { useConfig, useUpdateConfig } from "@/hooks/useConfig";

type ConsentRowProps = {
  title: string;
  description: string;
  checked: boolean;
  disabled: boolean;
  onCheckedChange: (next: boolean) => void;
};

function ConsentRow({ title, description, checked, disabled, onCheckedChange }: ConsentRowProps) {
  return (
    <div className="flex flex-wrap items-center justify-between gap-3 rounded-lg border border-border/50 p-3">
      <div className="min-w-0 flex-1 space-y-0.5">
        <p className="text-sm font-medium">{title}</p>
        <p className="text-xs text-muted-foreground">{description}</p>
      </div>
      <Switch
        checked={checked}
        onCheckedChange={onCheckedChange}
        disabled={disabled}
        aria-label={title}
      />
    </div>
  );
}

export function AiConsentSection() {
  const { data: config } = useConfig();
  const updateConfig = useUpdateConfig();
  const disabled = updateConfig.isPending;

  return (
    <section className="space-y-3">
      <SettingsSectionHeader
        title="AI consents"
        infoHint={{
          label: "About AI consents",
          content:
            "What AI is allowed to do with your transactions and documents. Each stays off until you turn it on, and routes to the provider set in Task routing.",
        }}
      />
      <p className="text-sm text-muted-foreground">
        These control what your configured AI provider may do with incoming transactions and
        documents.
      </p>

      <ConsentRow
        title="Categorize with AI"
        description="Sends the merchant name and amount to your configured AI provider to suggest a category for each new transaction."
        checked={config?.ai_categorization_enabled ?? false}
        disabled={disabled}
        onCheckedChange={(next) => updateConfig.mutate({ ai_categorization_enabled: next })}
      />

      <ConsentRow
        title="Rescue unreadable emails with AI"
        description="Sends the full email body to your configured AI provider, only when no parser can read the email."
        checked={config?.ai_extraction_enabled ?? false}
        disabled={disabled}
        onCheckedChange={(next) => updateConfig.mutate({ ai_extraction_enabled: next })}
      />

      <ConsentRow
        title="Parse statements with AI"
        description="Sends a statement PDF's text to your configured AI provider, only when no built-in bank parser can read it. Amounts are verified against the PDF before anything is saved."
        checked={config?.ai_statement_parsing_enabled ?? false}
        disabled={disabled}
        onCheckedChange={(next) => updateConfig.mutate({ ai_statement_parsing_enabled: next })}
      />

      <ConsentRow
        title="Parse receipts with AI"
        description="Sends a receipt photo or PDF to your configured AI provider, only when you ask. Amounts are checked against your transactions before anything is linked."
        checked={config?.ai_receipt_parsing_enabled ?? false}
        disabled={disabled}
        onCheckedChange={(next) => updateConfig.mutate({ ai_receipt_parsing_enabled: next })}
      />
    </section>
  );
}
