import { CheckCircle, Loader2, XCircle } from "lucide-react";
import { useEffect, useState } from "react";
import { SettingsSectionHeader } from "@/components/settings/SettingsSectionHeader";
import { Input } from "@/components/ui/input";
import { Switch } from "@/components/ui/switch";
import { useConfig, useUpdateConfig } from "@/hooks/useConfig";
import { useS3BackupStatus } from "@/hooks/useS3BackupStatus";
import { testS3Backup } from "@/lib/api";
import { formatRelativeTime } from "@/lib/format";
import { cn } from "@/lib/utils";
import type { AppConfig } from "@/types/api";

/**
 * The status row polls the hourly-sync state (60s refetch). Mounted only when
 * `s3_backup_enabled` is true, so the query never fires while backup is off.
 */
function S3BackupStatusRow() {
  const { data: status } = useS3BackupStatus();
  if (!status) return null;

  return (
    <div className="space-y-1 rounded-lg border border-border/50 bg-muted/20 px-4 py-3">
      <p className="text-sm text-fg-secondary tabular-nums">
        {status.last_success_at
          ? `Last synced ${formatRelativeTime(status.last_success_at)}`
          : "No successful sync yet"}
        {" · "}
        {status.objects_total} {status.objects_total === 1 ? "file" : "files"} mirrored
      </p>
      {status.last_error && (
        <p className="text-xs text-muted-foreground">
          Last sync failed: {status.last_error}
          {status.consecutive_failures > 1 &&
            ` · ${status.consecutive_failures} attempts in a row have not completed`}
        </p>
      )}
    </div>
  );
}

function S3BackupSectionInner({ config }: { config: AppConfig }) {
  const updateConfig = useUpdateConfig();

  const savedBucket = config.s3_backup_bucket ?? "";
  const savedPrefix = config.s3_backup_prefix ?? "";
  const enabled = config.s3_backup_enabled;
  const hasSavedBucket = savedBucket.trim().length > 0;

  const [bucket, setBucket] = useState(savedBucket);
  const [prefix, setPrefix] = useState(savedPrefix);
  const [testState, setTestState] = useState<"idle" | "testing" | "success" | "error">("idle");
  const [testError, setTestError] = useState("");
  const [warnings, setWarnings] = useState<string[]>([]);

  // Re-sync the inputs when the persisted values change (initial load or a
  // refetch after saving). Stable while the user edits, so it never clobbers
  // an in-progress edit.
  useEffect(() => {
    setBucket(savedBucket);
    setPrefix(savedPrefix);
  }, [savedBucket, savedPrefix]);

  const handleVerify = async () => {
    const trimmedBucket = bucket.trim();
    if (!trimmedBucket || testState === "testing") return;
    const trimmedPrefix = prefix.trim() || null;
    setTestState("testing");
    setTestError("");
    setWarnings([]);
    try {
      const result = await testS3Backup(trimmedBucket, trimmedPrefix);
      if (result.ok) {
        setTestState("success");
        setWarnings(result.warnings);
        updateConfig.mutate({
          s3_backup_bucket: trimmedBucket,
          s3_backup_prefix: trimmedPrefix,
        });
      } else {
        setTestState("error");
        setTestError(result.error ?? "Verification failed");
      }
    } catch {
      setTestState("error");
      setTestError("Network error");
    }
  };

  return (
    <section className="space-y-3">
      <SettingsSectionHeader
        title="S3 backup"
        infoHint={{
          label: "About S3 backup",
          content:
            "Copies receipt and statement files to a bucket you control. Verify the bucket to save it, then turn the backup on. The docs cover bucket setup and the permissions the sync needs.",
        }}
      />
      <p className="text-sm text-muted-foreground">
        Mirror receipt and statement files to an S3 bucket you own. Syncs hourly; local deletions
        are mirrored on the next pass. The docs cover bucket setup.
      </p>

      <div className="space-y-3 rounded-lg border border-border/50 p-3">
        <div className="space-y-1.5">
          <label htmlFor="s3-backup-bucket" className="text-xs text-muted-foreground">
            Bucket
          </label>
          <Input
            id="s3-backup-bucket"
            value={bucket}
            placeholder="my-backup-bucket"
            onChange={(e) => {
              setBucket(e.target.value);
              setTestState("idle");
            }}
            className="font-mono text-sm"
          />
        </div>

        <div className="space-y-1.5">
          <label htmlFor="s3-backup-prefix" className="text-xs text-muted-foreground">
            Prefix (optional)
          </label>
          <Input
            id="s3-backup-prefix"
            value={prefix}
            placeholder="tidings/"
            onChange={(e) => {
              setPrefix(e.target.value);
              setTestState("idle");
            }}
            className="font-mono text-sm"
          />
        </div>

        <button
          onClick={handleVerify}
          disabled={!bucket.trim() || testState === "testing"}
          className={cn(
            "rounded-lg border px-4 py-2 text-sm font-medium transition-colors",
            testState === "success"
              ? "border-status-success/30 bg-status-success/[0.04] text-status-success"
              : testState === "error"
                ? "border-status-danger/30 bg-status-danger/[0.04] text-status-danger"
                : "border-border/50 hover:bg-accent",
            (!bucket.trim() || testState === "testing") && "opacity-50 cursor-not-allowed"
          )}
        >
          {testState === "testing" ? (
            <Loader2 className="h-4 w-4 animate-spin" />
          ) : testState === "success" ? (
            <span className="flex items-center gap-1.5">
              <CheckCircle className="h-4 w-4" /> Saved
            </span>
          ) : (
            "Verify and save"
          )}
        </button>

        {testState === "error" && (
          <p className="flex items-center gap-1.5 text-xs text-destructive">
            <XCircle className="h-3.5 w-3.5" /> {testError}
          </p>
        )}

        {testState === "success" && warnings.length > 0 && (
          <ul className="space-y-1 text-xs text-muted-foreground">
            {warnings.map((warning) => (
              <li key={warning}>{warning}</li>
            ))}
          </ul>
        )}
      </div>

      <div className="flex flex-wrap items-center justify-between gap-3 rounded-lg border border-border/50 p-3">
        <div className="min-w-0 flex-1 space-y-0.5">
          <p className="text-sm font-medium">Back up to S3</p>
          <p className="text-xs text-muted-foreground">
            {hasSavedBucket
              ? "Runs the hourly sync to the saved bucket."
              : "Verify a bucket first to turn this on."}
          </p>
        </div>
        <Switch
          checked={enabled}
          onCheckedChange={(next) => updateConfig.mutate({ s3_backup_enabled: next })}
          disabled={!hasSavedBucket || updateConfig.isPending}
          aria-label="Back up to S3"
        />
      </div>

      {enabled && <S3BackupStatusRow />}
    </section>
  );
}

/**
 * S3 backup is an AWS-only feature. The section is hidden entirely unless the
 * backend reports `aws_available`; gating here (rather than inside the inner
 * component) keeps the status poll from mounting when the feature is off.
 */
export function S3BackupSection() {
  const { data: config } = useConfig();
  if (!config?.aws_available) return null;
  return <S3BackupSectionInner config={config} />;
}
