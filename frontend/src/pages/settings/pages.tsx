import { Lock } from "lucide-react";
import { useEffect } from "react";
import { useSearchParams } from "react-router-dom";
import { toast } from "sonner";
import { ActivityFeed } from "@/components/activity/ActivityFeed";
import {
  AccessDevModeSection,
  AccessPasswordSection,
  AccessSessionsSection,
} from "@/components/settings/AccessSection";
import { AiConsentSection } from "@/components/settings/AiConsentSection";
import { AppearanceSection } from "@/components/settings/AppearanceSection";
import { BriefingMemoSection } from "@/components/settings/BriefingMemoSection";
import { ConnectionsSection } from "@/components/settings/ConnectionsSection";
import { DataBackupSection } from "@/components/settings/DataBackupSection";
import { DataModeSection } from "@/components/settings/DataModeSection";
import { IngestionHealthSection } from "@/components/settings/IngestionHealthSection";
import { S3BackupSection } from "@/components/settings/S3BackupSection";
import { SystemStatusRow } from "@/components/settings/SystemStatusRow";
import { TabCustomizationSection } from "@/components/settings/TabCustomizationSection";
import { TaskRoutingSection } from "@/components/settings/TaskRoutingSection";
import { TaxTrackingSection } from "@/components/settings/TaxTrackingSection";
import { TimezoneSection } from "@/components/settings/TimezoneSection";
import { Card, CardContent } from "@/components/ui/card";
import { useDemoMode } from "@/hooks/useDemoMode";
import { SETUP_ANCHOR } from "@/lib/demoConstants";

export function DisplayPage() {
  return <AppearanceSection />;
}

export function NavigationPage() {
  return <TabCustomizationSection />;
}

export function TimezonePage() {
  return <TimezoneSection />;
}

export function FeaturesPage() {
  return <TaxTrackingSection />;
}

export function IntelligencePage() {
  const demo = useDemoMode();
  const [searchParams, setSearchParams] = useSearchParams();
  useEffect(() => {
    const status = searchParams.get("chatgpt");
    if (!status) return;
    if (status === "connected") {
      toast.success("ChatGPT connected");
    } else if (status === "error") {
      const reason = searchParams.get("reason") ?? "Connection failed";
      toast.error(`ChatGPT connection failed: ${reason}`);
    }
    setSearchParams(
      (prev) => {
        const p = new URLSearchParams(prev);
        p.delete("chatgpt");
        p.delete("reason");
        return p;
      },
      { replace: true }
    );
  }, [searchParams, setSearchParams]);

  if (demo) {
    return (
      <Card className="border-border/50 border-dashed">
        <CardContent className="p-4 flex items-start gap-3">
          <Lock className="h-4 w-4 text-muted-foreground mt-0.5 shrink-0" />
          <div className="text-sm">
            <p className="font-medium">AI provider config is self-hosted.</p>
            <p className="text-muted-foreground">
              Self-categorization and AI summaries run against your own API key.{" "}
              <a href={SETUP_ANCHOR} target="_blank" rel="noreferrer" className="underline">
                Set it up locally
              </a>
              . Category rules in the Categorize tab are editable in the demo and persist for this
              tab only.
            </p>
          </div>
        </CardContent>
      </Card>
    );
  }
  return (
    <div className="space-y-8">
      <ConnectionsSection />
      <TaskRoutingSection />
      <BriefingMemoSection />
      <AiConsentSection />
    </div>
  );
}

export function PasswordPage() {
  const demo = useDemoMode();
  if (demo) return null;
  return (
    <div className="space-y-8">
      <AccessPasswordSection />
      <AccessDevModeSection />
    </div>
  );
}

export function SessionsPage() {
  const demo = useDemoMode();
  if (demo) return null;
  return <AccessSessionsSection />;
}

export function ActivityPage() {
  return <ActivityFeed />;
}

export function SystemPage() {
  return (
    <div className="space-y-6">
      <DataModeSection />
      <SystemStatusRow />
      <IngestionHealthSection />
    </div>
  );
}

export function BackupPage() {
  const demo = useDemoMode();
  if (demo) {
    return (
      <Card className="border-border/50 border-dashed">
        <CardContent className="p-4 text-sm text-muted-foreground">
          Backup and restore are disabled in demo mode.
        </CardContent>
      </Card>
    );
  }
  return (
    <div className="space-y-8">
      <DataBackupSection />
      <S3BackupSection />
    </div>
  );
}
