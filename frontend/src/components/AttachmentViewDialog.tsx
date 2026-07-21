import { AlertTriangle, ExternalLink, FileText, Loader2, Paperclip, Trash2 } from "lucide-react";
import { Button } from "@/components/ui/button";
import {
  Dialog,
  DialogContent,
  DialogDescription,
  DialogHeader,
  DialogTitle,
} from "@/components/ui/dialog";
import { useDeleteAttachment } from "@/hooks/useDeleteAttachment";
import { getAttachmentFileUrl } from "@/lib/api";
import { formatBytes, isImageContentType } from "@/lib/attachments";
import { formatCurrency, formatDate, formatRelativeTime } from "@/lib/format";
import type { AttachmentResponse } from "@/types/api";

// parse_json is a generic bag in the OpenAPI schema; these narrow, read-only
// shapes mirror the backend receipt schema (L6/L7) for display only.
interface ReceiptLineItem {
  description: string;
  amount: number;
  qty?: number;
  unit_price?: number;
}

interface ReceiptProvenance {
  provider?: string;
  model?: string;
  parsed_at?: string;
}

interface ParsedReceipt {
  merchant?: string;
  date?: string;
  total?: number;
  line_items?: ReceiptLineItem[];
  provenance?: ReceiptProvenance;
}

function readParsedReceipt(parseJson: AttachmentResponse["parse_json"]): ParsedReceipt | null {
  if (!parseJson || typeof parseJson !== "object") return null;
  return parseJson as ParsedReceipt;
}

// Display names for provider ids, matching the Settings provider picker. CLI
// providers stamp `model = provider` (the CLI's internal model is unknown), so
// the model is only shown when it carries new information.
const PROVIDER_LABELS: Record<string, string> = {
  claude_cli: "Claude Code",
  codex: "OpenAI Codex",
  gemini_cli: "Google Gemini",
  openai: "OpenAI",
};

/** "Claude Code" or "OpenAI · gpt-5.4-nano" — never a duplicated internal id. */
function provenanceLabel(p: ReceiptProvenance): string {
  const parts: string[] = [];
  if (p.provider) parts.push(PROVIDER_LABELS[p.provider] ?? p.provider);
  if (p.model && p.model !== p.provider) parts.push(p.model);
  return parts.join(" · ");
}

interface AttachmentViewDialogProps {
  attachments: AttachmentResponse[];
  open: boolean;
  onOpenChange: (open: boolean) => void;
  /** Header label. Defaults to "Receipts". */
  title?: string;
  /** Optional "attach another" affordance shown in the footer. */
  onAttachAnother?: () => void;
}

/**
 * Read-only view of a transaction's (or unfiled) attachments: an image preview
 * or a PDF open-in-tab link, the file metadata, and a delete action. The
 * parsed line-item table arrives in Phase 4.
 */
export function AttachmentViewDialog({
  attachments,
  open,
  onOpenChange,
  title = "Receipts",
  onAttachAnother,
}: AttachmentViewDialogProps) {
  const del = useDeleteAttachment();

  return (
    <Dialog open={open} onOpenChange={onOpenChange}>
      <DialogContent className="max-h-[85vh] max-w-lg overflow-y-auto">
        <DialogHeader>
          <DialogTitle>{title}</DialogTitle>
          <DialogDescription className="sr-only">
            Attached receipts and documents for this transaction
          </DialogDescription>
        </DialogHeader>

        {attachments.length === 0 ? (
          <p className="py-8 text-center text-sm text-fg-muted">No receipts attached.</p>
        ) : (
          <ul className="space-y-3">
            {attachments.map((att) => {
              const url = getAttachmentFileUrl(att.id);
              const isImage = isImageContentType(att.content_type);
              const isDeleting = del.isPending && del.variables === att.id;
              const parsed = readParsedReceipt(att.parse_json);
              const lineItems = parsed?.line_items ?? [];
              return (
                <li key={att.id} className="rounded-lg border border-border p-3">
                  {isImage ? (
                    <a href={url} target="_blank" rel="noreferrer" className="block">
                      <img
                        src={url}
                        alt={att.original_filename}
                        className="max-h-64 w-full rounded-md object-contain"
                      />
                    </a>
                  ) : (
                    <a
                      href={url}
                      target="_blank"
                      rel="noreferrer"
                      className="flex items-center gap-2 rounded-md border border-border bg-surface-muted/50 px-3 py-2 text-sm hover:bg-accent"
                    >
                      <FileText className="h-4 w-4 text-fg-muted" />
                      <span className="min-w-0 flex-1 truncate">{att.original_filename}</span>
                      <ExternalLink className="h-3.5 w-3.5 text-fg-muted" />
                    </a>
                  )}
                  <div className="mt-2 flex items-center justify-between gap-2">
                    <div className="min-w-0 text-xs text-fg-muted">
                      <span className="block truncate">{att.original_filename}</span>
                      <span>
                        {formatBytes(att.size_bytes)} · added {formatRelativeTime(att.created_at)}
                      </span>
                    </div>
                    <button
                      type="button"
                      aria-label="Delete receipt"
                      disabled={isDeleting}
                      onClick={() => del.mutate(att.id)}
                      className="rounded p-1 text-fg-muted transition-colors hover:bg-status-danger/10 hover:text-status-danger disabled:opacity-50"
                    >
                      {isDeleting ? (
                        <Loader2 className="h-4 w-4 animate-spin" />
                      ) : (
                        <Trash2 className="h-4 w-4" />
                      )}
                    </button>
                  </div>

                  {att.parse_status === "failed" && att.parse_error && (
                    <p className="mt-2 flex items-start gap-1.5 text-xs text-fg-muted">
                      <AlertTriangle className="mt-0.5 h-3.5 w-3.5 shrink-0" />
                      <span>{att.parse_error}</span>
                    </p>
                  )}

                  {parsed && (
                    <div className="mt-3 border-t border-border pt-3">
                      {(parsed.merchant || parsed.total !== undefined || parsed.date) && (
                        <p className="text-xs text-fg-muted">
                          {[
                            parsed.merchant,
                            parsed.date ? formatDate(parsed.date) : null,
                            parsed.total !== undefined ? formatCurrency(parsed.total) : null,
                          ]
                            .filter(Boolean)
                            .join(" · ")}
                        </p>
                      )}

                      {lineItems.length > 0 && (
                        <table className="mt-2 w-full text-xs">
                          <thead>
                            <tr className="text-left text-fg-muted">
                              <th className="pb-1 font-normal">Item</th>
                              <th className="pb-1 text-right font-normal">Qty</th>
                              <th className="pb-1 text-right font-normal">Amount</th>
                            </tr>
                          </thead>
                          <tbody>
                            {lineItems.map((item, i) => (
                              <tr key={`${att.id}-${i}`} className="border-t border-border/50">
                                <td className="py-1 pr-2">{item.description}</td>
                                <td className="py-1 pl-2 text-right text-fg-muted">
                                  {item.qty ?? ""}
                                </td>
                                <td className="py-1 pl-2 text-right tabular-nums">
                                  {formatCurrency(item.amount)}
                                </td>
                              </tr>
                            ))}
                          </tbody>
                        </table>
                      )}

                      {parsed.provenance && provenanceLabel(parsed.provenance) && (
                        <p className="mt-2 text-[11px] text-fg-muted">
                          Read by {provenanceLabel(parsed.provenance)}
                          {parsed.provenance.parsed_at
                            ? ` · ${formatRelativeTime(parsed.provenance.parsed_at)}`
                            : ""}
                        </p>
                      )}
                    </div>
                  )}
                </li>
              );
            })}
          </ul>
        )}

        {onAttachAnother && (
          <div className="flex justify-end">
            <Button type="button" variant="outline" onClick={onAttachAnother} className="gap-2">
              <Paperclip className="h-4 w-4" />
              Attach another
            </Button>
          </div>
        )}
      </DialogContent>
    </Dialog>
  );
}
