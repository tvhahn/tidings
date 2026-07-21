import { Camera, Check, Images, Link2, Loader2, Sparkles, Undo2, Upload } from "lucide-react";
import { useEffect, useRef, useState } from "react";
import { Button } from "@/components/ui/button";
import {
  Dialog,
  DialogContent,
  DialogDescription,
  DialogHeader,
  DialogTitle,
  DialogTrigger,
} from "@/components/ui/dialog";
import { useConfig } from "@/hooks/useConfig";
import { useLinkAttachment } from "@/hooks/useLinkAttachment";
import { useMediaQuery } from "@/hooks/useMediaQuery";
import { useParseReceipt } from "@/hooks/useParseReceipt";
import { useReceiptCandidates } from "@/hooks/useReceiptCandidates";
import { useUploadAttachment } from "@/hooks/useUploadAttachment";
import { formatCurrency, formatDate } from "@/lib/format";
import type { AttachmentResponse, ReceiptCandidate } from "@/types/api";

// Both paths (photo library, file browser) accept the same set the backend
// stores; "Take photo" narrows to images and asks for the camera.
const IMAGE_AND_PDF = "image/*,application/pdf";

type CaptureState = "pick" | "uploading" | "uploaded";

/**
 * Quiet, human proximity text for a match candidate — never tier jargon (L16).
 * Combines how close in time and in amount the transaction is, e.g.
 * "same day · exact amount" or "2 days away · $3.40 difference".
 */
function candidateProximity(c: ReceiptCandidate): string {
  const dayPart =
    c.day_distance === 0
      ? "same day"
      : c.day_distance === 1
        ? "1 day away"
        : `${c.day_distance} days away`;
  const amountPart =
    c.amount_distance < 0.01 ? "exact amount" : `${formatCurrency(c.amount_distance)} difference`;
  return `${dayPart} · ${amountPart}`;
}

interface ReceiptReviewProps {
  /** The uploaded (or already-stored) attachment to parse and match. */
  attachment: AttachmentResponse;
  /**
   * Show ranked candidates after a parse. True for unlinked receipts; false for
   * pre-linked uploads, where parsing only enriches the row (no matching, L16).
   */
  matching: boolean;
  /** Called after a successful link or auto-link so the parent can close/refresh. */
  onLinked?: () => void;
}

/**
 * The parse → review → link flow shared by the capture dialog and the "Receipts
 * to file" list. Offers parsing only when the user asks (a quiet Settings hint
 * replaces the button when consent is off), then presents matches as calm
 * proximity text with one-tap linking. An auto-linked receipt shows a
 * confirmation with an undo affordance.
 */
export function ReceiptReview({ attachment, matching, onLinked }: ReceiptReviewProps) {
  const { data: config } = useConfig();
  const consent = config?.ai_receipt_parsing_enabled ?? false;

  const parse = useParseReceipt();
  const link = useLinkAttachment();

  // After an explicit undo we stop querying candidates so the single-strong-match
  // signal (exactly one tier-1 + unlinked) doesn't immediately re-link.
  const [undone, setUndone] = useState(false);
  // The transaction we auto-linked to, latched once the link mutation succeeds.
  // Held locally (not read off the query) because setting it also disables the
  // query — see the effect below.
  const [autoLinkedTo, setAutoLinkedTo] = useState<ReceiptCandidate | null>(null);
  // Set when the auto-link mutation itself fails, so we fall through to the
  // manual candidate list instead of falsely confirming a link.
  const [autoLinkFailed, setAutoLinkFailed] = useState(false);

  const parsed = parse.data ?? (attachment.parse_status === "parsed" ? attachment : null);
  const isParsed = parsed !== null;
  const candidates = useReceiptCandidates(
    attachment.id,
    matching && isParsed && !undone && !autoLinkedTo
  );

  // Single strong match (L8): the candidates GET is now a pure read that only
  // signals eligibility (`auto_link_candidate`) — the client owns the write. Fire
  // the existing link mutation exactly once per dialog lifecycle, then latch
  // `autoLinkedTo` on success (which stops the query so a refetch can't drop the
  // confirmation). The mutation's factory owns cache invalidation. A ref guards
  // against double-fire: it latches synchronously the moment we dispatch, so
  // StrictMode's double-invoke and query refetches can't fire a second link.
  const data = candidates.data;
  const autoLinkFired = useRef(false);
  useEffect(() => {
    if (autoLinkFired.current || undone || autoLinkedTo) return;
    const winner = data?.auto_link_candidate ? data.candidates[0] : null;
    if (!winner) return;
    autoLinkFired.current = true;
    link.mutate(
      { id: attachment.id, txId: winner.tx_id },
      {
        onSuccess: () => setAutoLinkedTo(winner),
        onError: () => setAutoLinkFailed(true),
      }
    );
  }, [data, undone, autoLinkedTo, link, attachment.id]);

  // Not parsed yet: offer the parse action, or the calm enable-in-Settings hint.
  if (!isParsed) {
    if (!consent) {
      return (
        <p className="rounded-lg border border-border bg-surface-muted/50 p-3 text-xs text-fg-muted">
          To read receipts, turn on Parse receipts with AI in Settings → Intelligence.
        </p>
      );
    }
    return (
      <div className="space-y-2">
        <Button
          type="button"
          variant="outline"
          className="w-full gap-2"
          disabled={parse.isPending}
          onClick={() => parse.mutate(attachment.id)}
        >
          {parse.isPending ? (
            <>
              <Loader2 className="h-4 w-4 animate-spin" />
              Reading receipt…
            </>
          ) : (
            <>
              <Sparkles className="h-4 w-4" />
              Parse receipt
            </>
          )}
        </Button>
        {parse.isError && (
          <p className="text-xs text-destructive">
            {parse.error instanceof Error ? parse.error.message : "Couldn't read the receipt."}
          </p>
        )}
      </div>
    );
  }

  const summary = readParseSummary(parsed.parse_json);

  // Pre-linked upload: parsing only enriches the row — no matching.
  if (!matching) {
    return (
      <div className="rounded-lg border border-border bg-surface-muted/50 p-3 text-sm">
        <div className="flex items-center gap-2">
          <Check className="h-4 w-4 text-status-success" />
          <span>Receipt read.</span>
        </div>
        {summary && <p className="mt-1 text-xs text-fg-muted">{summary}</p>}
      </div>
    );
  }

  // Undone: the receipt is back in "Receipts to file".
  if (undone) {
    return (
      <p className="rounded-lg border border-border bg-surface-muted/50 p-3 text-xs text-fg-muted">
        Moved back to Receipts to file.
      </p>
    );
  }

  // Auto-linked: exactly one strong match; confirm calmly with an undo. Falls
  // back to the signalled candidate for the frame between the GET returning and
  // the link mutation resolving, so no candidate list flashes; if that mutation
  // fails we drop the fallback and let the user pick manually.
  const autoLinked =
    autoLinkedTo ??
    (!autoLinkFailed && data?.auto_link_candidate ? (data.candidates[0] ?? null) : null);
  if (autoLinked) {
    return (
      <div className="rounded-lg border border-border bg-surface-muted/50 p-3 text-sm">
        <div className="flex items-center gap-2">
          <Check className="h-4 w-4 text-status-success" />
          <span className="min-w-0 break-words">Linked to {autoLinked.company}.</span>
        </div>
        <button
          type="button"
          disabled={link.isPending}
          onClick={() =>
            link.mutate({ id: attachment.id, txId: null }, { onSuccess: () => setUndone(true) })
          }
          className="mt-2 inline-flex items-center gap-1 text-xs text-fg-muted underline-offset-2 hover:text-fg hover:underline disabled:opacity-50"
        >
          <Undo2 className="h-3.5 w-3.5" />
          Undo
        </button>
      </div>
    );
  }

  if (candidates.isPending) {
    return (
      <div className="flex items-center justify-center gap-2 py-4 text-sm text-fg-muted">
        <Loader2 className="h-4 w-4 animate-spin" />
        Finding matches…
      </div>
    );
  }

  const rows = data?.candidates ?? [];
  if (rows.length === 0) {
    return (
      <p className="rounded-lg border border-border bg-surface-muted/50 p-3 text-xs text-fg-muted">
        No matching transactions found. You can file it from Receipts to file later.
      </p>
    );
  }

  return (
    <div className="space-y-2">
      <p className="text-xs text-fg-muted">
        {summary ? `${summary}. ` : ""}
        Pick the transaction this receipt belongs to.
      </p>
      <ul className="space-y-2">
        {rows.map((c) => {
          const isLinking = link.isPending && link.variables?.id === attachment.id;
          return (
            <li
              key={c.tx_id}
              className="flex items-center gap-3 rounded-lg border border-border p-2.5"
            >
              <div className="min-w-0 flex-1">
                <p className="truncate text-sm font-medium">{c.company}</p>
                <p className="text-xs text-fg-muted">
                  {formatDate(c.date)} · {formatCurrency(c.amount)}
                  {c.already_has_receipt ? " · already has a receipt" : ""}
                </p>
                <p className="text-xs text-fg-muted">{candidateProximity(c)}</p>
              </div>
              <Button
                type="button"
                size="sm"
                variant="outline"
                className="gap-1"
                disabled={isLinking}
                onClick={() =>
                  link.mutate(
                    { id: attachment.id, txId: c.tx_id },
                    { onSuccess: () => onLinked?.() }
                  )
                }
              >
                <Link2 className="h-3.5 w-3.5" />
                Link
              </Button>
            </li>
          );
        })}
      </ul>
    </div>
  );
}

/** A one-line merchant/date/total summary from a parsed receipt, when present. */
function readParseSummary(parseJson: AttachmentResponse["parse_json"]): string | null {
  if (!parseJson || typeof parseJson !== "object") return null;
  const record = parseJson as Record<string, unknown>;
  const merchant = typeof record.merchant === "string" ? record.merchant : null;
  const total = typeof record.total === "number" ? record.total : null;
  if (!merchant && total === null) return null;
  const parts: string[] = [];
  if (merchant) parts.push(merchant);
  if (total !== null) parts.push(formatCurrency(total));
  return parts.join(" · ");
}

interface AttachmentCaptureDialogProps {
  /** Controlled open state. Omit for the standalone trigger-button variant. */
  open?: boolean;
  onOpenChange?: (open: boolean) => void;
  /** When set, the upload links to this transaction immediately. */
  txId?: string;
  /** Attachment kind; defaults to "receipt" on the server. */
  kind?: string;
  /** Trigger node for the uncontrolled variant. */
  trigger?: React.ReactNode;
}

/**
 * Capture a receipt or document. On phones it offers three quiet rows — take a
 * photo, pick from the library, or browse files; on desktop it goes straight to
 * the file picker (L16). After upload it offers parsing and, for unlinked
 * receipts, ranked match candidates (Phase 4).
 */
export function AttachmentCaptureDialog({
  open,
  onOpenChange,
  txId,
  kind,
  trigger,
}: AttachmentCaptureDialogProps) {
  const isControlled = open !== undefined;
  const [internalOpen, setInternalOpen] = useState(false);
  const dialogOpen = isControlled ? open : internalOpen;

  const isMobile = useMediaQuery("(max-width: 767px)");
  const upload = useUploadAttachment();

  const [state, setState] = useState<CaptureState>("pick");
  const [uploaded, setUploaded] = useState<AttachmentResponse | null>(null);
  const [error, setError] = useState<string | null>(null);

  const cameraRef = useRef<HTMLInputElement>(null);
  const libraryRef = useRef<HTMLInputElement>(null);
  const fileRef = useRef<HTMLInputElement>(null);

  const reset = () => {
    setState("pick");
    setUploaded(null);
    setError(null);
    upload.reset();
  };

  const setOpen = (next: boolean) => {
    if (!next) reset();
    if (isControlled) onOpenChange?.(next);
    else setInternalOpen(next);
  };

  const handleFile = (e: React.ChangeEvent<HTMLInputElement>) => {
    const file = e.target.files?.[0];
    // Clear the input so re-selecting the same file still fires onChange.
    e.target.value = "";
    if (!file) return;
    setError(null);
    setState("uploading");
    upload.mutate(
      { file, ...(txId ? { txId } : {}), ...(kind ? { kind } : {}) },
      {
        onSuccess: (res) => {
          setUploaded(res);
          setState("uploaded");
        },
        onError: (err) => {
          setError(err instanceof Error ? err.message : "Upload failed.");
          setState("pick");
        },
      }
    );
  };

  const pickRow = (
    ref: React.RefObject<HTMLInputElement | null>,
    icon: React.ReactNode,
    label: string,
    hint: string
  ) => (
    <button
      type="button"
      onClick={() => ref.current?.click()}
      className="flex w-full items-center gap-3 rounded-lg border border-border px-3 py-2.5 text-left transition-colors hover:bg-accent"
    >
      <span className="text-fg-muted">{icon}</span>
      <span className="flex flex-col">
        <span className="text-sm font-medium">{label}</span>
        <span className="text-xs text-fg-muted">{hint}</span>
      </span>
    </button>
  );

  return (
    <Dialog open={dialogOpen} onOpenChange={setOpen}>
      {!isControlled && trigger && <DialogTrigger asChild>{trigger}</DialogTrigger>}
      <DialogContent className="sm:max-w-sm">
        <DialogHeader>
          <DialogTitle>Attach a receipt</DialogTitle>
          <DialogDescription>
            Add a photo or PDF. It stays on your server with the transaction.
          </DialogDescription>
        </DialogHeader>

        {/* Hidden inputs — one per entry point so the accept/capture hints differ. */}
        <input
          ref={cameraRef}
          type="file"
          accept="image/*"
          capture="environment"
          className="hidden"
          onChange={handleFile}
        />
        <input
          ref={libraryRef}
          type="file"
          accept="image/*,application/pdf"
          className="hidden"
          onChange={handleFile}
        />
        <input
          ref={fileRef}
          type="file"
          accept={IMAGE_AND_PDF}
          className="hidden"
          onChange={handleFile}
        />

        {state === "pick" &&
          (isMobile ? (
            <div className="space-y-2">
              {pickRow(cameraRef, <Camera className="h-5 w-5" />, "Take photo", "Use the camera")}
              {pickRow(
                libraryRef,
                <Images className="h-5 w-5" />,
                "Choose from library",
                "Pick an existing photo"
              )}
              {pickRow(fileRef, <Upload className="h-5 w-5" />, "Upload file", "Browse for a PDF")}
            </div>
          ) : (
            <div className="flex flex-col gap-3">
              <Button type="button" onClick={() => fileRef.current?.click()} className="gap-2">
                <Upload className="h-4 w-4" />
                Choose a file
              </Button>
              <p className="text-xs text-fg-muted">Images or PDF, up to 10 MB.</p>
            </div>
          ))}

        {error && <p className="text-sm text-destructive">{error}</p>}

        {state === "uploading" && (
          <div className="flex items-center justify-center gap-2 py-6 text-sm text-fg-muted">
            <Loader2 className="h-4 w-4 animate-spin" />
            Uploading…
          </div>
        )}

        {state === "uploaded" && uploaded && (
          <div className="space-y-4">
            <div className="flex items-center gap-2 rounded-lg border border-border bg-surface-muted/50 p-3 text-sm">
              <Check className="h-4 w-4 text-status-success" />
              <span className="min-w-0 break-words">
                Receipt added — {uploaded.original_filename}.
              </span>
            </div>

            <ReceiptReview attachment={uploaded} matching={!txId} onLinked={() => setOpen(false)} />

            <div className="flex justify-end gap-2">
              <Button type="button" variant="outline" onClick={reset}>
                Add another
              </Button>
              <Button type="button" onClick={() => setOpen(false)}>
                Done
              </Button>
            </div>
          </div>
        )}
      </DialogContent>
    </Dialog>
  );
}
