import { useQueryClient } from "@tanstack/react-query";
import { Download, Loader2, Upload } from "lucide-react";
import { useRef, useState } from "react";
import { ImportPreviewModal } from "@/components/settings/ImportPreviewModal";
import { SettingsSectionHeader } from "@/components/settings/SettingsSectionHeader";
import { Button } from "@/components/ui/button";
import { commitImport, downloadBackup, previewImport } from "@/lib/api";
import type { ImportPreviewResponse, ImportResult, ImportStrategy } from "@/types/api";

export function DataBackupSection() {
  const [isExporting, setIsExporting] = useState(false);
  const [isPreviewing, setIsPreviewing] = useState(false);
  const [preview, setPreview] = useState<ImportPreviewResponse | null>(null);
  const [modalOpen, setModalOpen] = useState(false);
  const [flash, setFlash] = useState<{ kind: "success" | "error"; text: string } | null>(null);
  const fileInputRef = useRef<HTMLInputElement>(null);
  const queryClient = useQueryClient();

  const handleExport = async () => {
    setIsExporting(true);
    setFlash(null);
    try {
      await downloadBackup();
      setFlash({ kind: "success", text: "Backup downloaded." });
    } catch (e) {
      setFlash({ kind: "error", text: e instanceof Error ? e.message : String(e) });
    } finally {
      setIsExporting(false);
    }
  };

  const handleFileSelected = async (file: File) => {
    setIsPreviewing(true);
    setFlash(null);
    setPreview(null);
    try {
      const result = await previewImport(file);
      setPreview(result);
      setModalOpen(true);
    } catch (e) {
      setFlash({ kind: "error", text: e instanceof Error ? e.message : String(e) });
    } finally {
      setIsPreviewing(false);
      // Reset the input so selecting the same file twice still triggers onChange.
      if (fileInputRef.current) fileInputRef.current.value = "";
    }
  };

  const handleApply = async (
    strategy: ImportStrategy,
    applyConfig: boolean
  ): Promise<ImportResult> => {
    if (!preview) throw new Error("No staged preview");
    return commitImport(preview.token, strategy, applyConfig);
  };

  const handleImportSuccess = (result: ImportResult) => {
    // Imports touch everything — broadly invalidate so stale caches refetch.
    queryClient.invalidateQueries();
    const parts = [
      `${result.inserted} inserted`,
      result.updated > 0 ? `${result.updated} updated` : null,
      result.skipped > 0 ? `${result.skipped} skipped` : null,
      result.invalid > 0 ? `${result.invalid} invalid` : null,
    ].filter(Boolean);
    setFlash({ kind: "success", text: `Import complete: ${parts.join(", ")}.` });
    setPreview(null);
  };

  return (
    <>
      <section className="space-y-6">
        {/* Export */}
        <div className="space-y-3">
          <SettingsSectionHeader
            title="Download backup"
            infoHint={{
              label: "About backups",
              content:
                "A single .zip containing all transactions (CSV with every field — including the original email body and category history), categories, overrides, merchant aliases, and budgets. Treat this file as sensitive: it contains raw transaction data.",
            }}
          />
          <div className="flex items-center justify-between rounded-lg border border-border/50 px-4 py-3">
            <div>
              <p className="text-sm font-medium">Full-data backup</p>
              <p className="text-xs text-muted-foreground">
                Transactions (CSV) + categories, overrides, merchant aliases, budgets (JSON).
              </p>
            </div>
            <Button onClick={handleExport} disabled={isExporting} variant="ghost">
              {isExporting ? (
                <>
                  <Loader2 className="mr-2 h-4 w-4 animate-spin" /> Exporting…
                </>
              ) : (
                <>
                  <Download className="mr-2 h-4 w-4" /> Download backup
                </>
              )}
            </Button>
          </div>
        </div>

        {/* Import */}
        <div className="space-y-3">
          <SettingsSectionHeader
            title="Restore from backup"
            infoHint={{
              label: "About restore",
              content:
                "Upload a backup .zip produced here, or a plain transactions CSV from the Search tab. A dry-run preview shows how many rows are new vs. duplicates before anything is written.",
            }}
          />
          <div className="flex items-center justify-between rounded-lg border border-border/50 px-4 py-3">
            <div>
              <p className="text-sm font-medium">Import backup or CSV</p>
              <p className="text-xs text-muted-foreground">
                Accepts a backup .zip or a plain transactions CSV (like the Search-tab export).
              </p>
            </div>
            <div>
              <input
                ref={fileInputRef}
                type="file"
                accept=".zip,.csv"
                onChange={(e) => {
                  const f = e.target.files?.[0];
                  if (f) handleFileSelected(f);
                }}
                className="hidden"
                id="data-import-file"
              />
              <Button
                variant="ghost"
                disabled={isPreviewing}
                onClick={() => fileInputRef.current?.click()}
              >
                {isPreviewing ? (
                  <>
                    <Loader2 className="mr-2 h-4 w-4 animate-spin" /> Previewing…
                  </>
                ) : (
                  <>
                    <Upload className="mr-2 h-4 w-4" /> Choose file…
                  </>
                )}
              </Button>
            </div>
          </div>
        </div>

        {flash && (
          <div
            role="status"
            className={
              flash.kind === "success"
                ? "rounded-md border border-status-success/30 bg-status-success/5 p-3 text-xs text-status-success"
                : "rounded-md border border-status-danger/30 bg-status-danger/5 p-3 text-xs text-status-danger"
            }
          >
            {flash.text}
          </div>
        )}
      </section>

      <ImportPreviewModal
        preview={preview}
        open={modalOpen}
        onOpenChange={(open) => {
          setModalOpen(open);
          if (!open) setPreview(null);
        }}
        onApply={handleApply}
        onSuccess={handleImportSuccess}
      />
    </>
  );
}
