import { fireEvent, render, screen } from "@testing-library/react";
import { afterEach, describe, expect, it, vi } from "vitest";
import { S3BackupSection } from "@/components/settings/S3BackupSection";
import type { AppConfig, S3BackupStatus } from "@/types/api";

// --- Mocks ------------------------------------------------------------------
const { mutateSpy, testS3BackupSpy } = vi.hoisted(() => ({
  mutateSpy: vi.fn(),
  testS3BackupSpy: vi.fn(),
}));

let configValue: Partial<AppConfig> = {};
let statusValue: S3BackupStatus | undefined;

vi.mock("@/hooks/useConfig", () => ({
  useConfig: () => ({ data: configValue }),
  useUpdateConfig: () => ({ mutate: mutateSpy, isPending: false }),
}));

vi.mock("@/hooks/useS3BackupStatus", () => ({
  useS3BackupStatus: () => ({ data: statusValue }),
}));

vi.mock("@/lib/api", () => ({
  testS3Backup: testS3BackupSpy,
}));

function setConfig(over: Partial<AppConfig>) {
  configValue = { aws_available: true, s3_backup_enabled: false, ...over };
}

afterEach(() => {
  vi.clearAllMocks();
  configValue = {};
  statusValue = undefined;
});

describe("S3BackupSection", () => {
  it("renders nothing when aws_available is false", () => {
    setConfig({ aws_available: false });
    const { container } = render(<S3BackupSection />);
    expect(container.firstChild).toBeNull();
  });

  it("verifies, saves the trimmed values, and lists advisory warnings", async () => {
    setConfig({ s3_backup_bucket: null, s3_backup_prefix: null });
    testS3BackupSpy.mockResolvedValue({
      ok: true,
      error: null,
      warnings: ["Bucket has no lifecycle policy set."],
    });

    render(<S3BackupSection />);

    fireEvent.change(screen.getByLabelText("Bucket"), { target: { value: "  my-bucket  " } });
    fireEvent.change(screen.getByLabelText("Prefix (optional)"), {
      target: { value: "  tidings/  " },
    });
    fireEvent.click(screen.getByRole("button", { name: "Verify and save" }));

    // The button flips to "Saved" and the warning renders once the resolved
    // promise settles — await that before asserting the follow-on save.
    expect(await screen.findByText("Bucket has no lifecycle policy set.")).toBeInTheDocument();
    expect(screen.getByRole("button", { name: "Saved" })).toBeInTheDocument();
    expect(testS3BackupSpy).toHaveBeenCalledWith("my-bucket", "tidings/");
    expect(mutateSpy).toHaveBeenCalledWith({
      s3_backup_bucket: "my-bucket",
      s3_backup_prefix: "tidings/",
    });
  });

  it("shows the error text and does not save when verification fails", async () => {
    setConfig({ s3_backup_bucket: null });
    testS3BackupSpy.mockResolvedValue({
      ok: false,
      error: "Access denied to the bucket.",
      warnings: [],
    });

    render(<S3BackupSection />);

    fireEvent.change(screen.getByLabelText("Bucket"), { target: { value: "locked-bucket" } });
    fireEvent.click(screen.getByRole("button", { name: "Verify and save" }));

    expect(await screen.findByText("Access denied to the bucket.")).toBeInTheDocument();
    expect(mutateSpy).not.toHaveBeenCalled();
  });

  it("disables the enable toggle until a bucket is saved", () => {
    setConfig({ s3_backup_bucket: null });
    const { rerender } = render(<S3BackupSection />);
    expect(screen.getByRole("switch", { name: "Back up to S3" })).toBeDisabled();

    setConfig({ s3_backup_bucket: "saved-bucket" });
    rerender(<S3BackupSection />);
    expect(screen.getByRole("switch", { name: "Back up to S3" })).toBeEnabled();
  });

  it("shows the status block with last sync time and error line when enabled", () => {
    setConfig({ s3_backup_enabled: true, s3_backup_bucket: "saved-bucket" });
    statusValue = {
      enabled: true,
      bucket: "saved-bucket",
      prefix: null,
      last_attempt_at: "2026-07-18T12:00:00Z",
      last_success_at: "2026-07-18T11:00:00Z",
      last_error: "Timed out reaching the bucket.",
      consecutive_failures: 3,
      uploaded_count: 12,
      deleted_count: 1,
      objects_total: 42,
    };

    render(<S3BackupSection />);

    expect(screen.getByText(/Last synced/)).toBeInTheDocument();
    expect(screen.getByText(/42 files mirrored/)).toBeInTheDocument();
    expect(
      screen.getByText(/Last sync failed: Timed out reaching the bucket\./)
    ).toBeInTheDocument();
  });
});
