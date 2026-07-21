import { Paperclip } from "lucide-react";
import { useState } from "react";
import { AttachmentCaptureDialog } from "@/components/AttachmentCaptureDialog";
import { AttachmentViewDialog } from "@/components/AttachmentViewDialog";
import { Tooltip, TooltipTrigger, TooltipContent } from "@/components/ui/tooltip";
import { useTransactionAttachments } from "@/hooks/useTransactionAttachments";
import { txIdFromComposite } from "@/lib/api";
import { cn } from "@/lib/utils";
import type { Transaction } from "@/types/api";

/**
 * Paperclip attach/view affordance for one row. Rendered inside a hover/kebab
 * action cluster — never a bulk per-row sweep. A colored paperclip signals the
 * row already has receipts; the dialogs portal out so they survive the row
 * losing hover.
 *
 * Shared by the Transactions table (`size="sm"`), the Transactions mobile card
 * (`size="md"`), and the Journal row cluster. `onActivate` fires inside the
 * button's onClick before a dialog opens — the card passes `setMenuOpen(false)`
 * so the kebab closes when a dialog opens.
 *
 * The cluster mounts mid-gesture (first row hover), and that reveal commit must
 * stay CHEAP: mounting the query subscription and two Radix dialogs at reveal
 * slipped past a click's mousedown and swallowed "Edit category" clicks. So at
 * reveal we render only the plain button; the query and dialogs mount on first
 * paperclip engagement (pointerenter/focus/click). The indicator appears a beat
 * later — acceptable.
 */
export function RowAttachmentAction({
  txn,
  size = "sm",
  onActivate,
}: {
  txn: Transaction;
  size?: "sm" | "md";
  onActivate?: () => void;
}) {
  const txId = txIdFromComposite(txn.forwarded_to, txn.date_file_name);
  const [engaged, setEngaged] = useState(false);
  const [captureOpen, setCaptureOpen] = useState(false);
  const [viewOpen, setViewOpen] = useState(false);
  const { data } = useTransactionAttachments(txId, engaged);
  const attachments = data?.attachments ?? [];
  const hasAttachments = attachments.length > 0;
  const engage = () => setEngaged(true);
  return (
    <>
      <Tooltip>
        <TooltipTrigger asChild>
          <button
            aria-label={hasAttachments ? "View receipts" : "Attach a receipt"}
            onPointerEnter={engage}
            onFocus={engage}
            onClick={() => {
              engage();
              onActivate?.();
              // Before the (engagement-gated) query resolves, fall back to the
              // capture dialog — attaching is always valid; the view path is
              // reachable once the indicator is loaded.
              if (hasAttachments) setViewOpen(true);
              else setCaptureOpen(true);
            }}
            className={cn(
              "rounded transition-colors hover:bg-muted",
              size === "sm" ? "p-0.5" : "p-1",
              hasAttachments
                ? "text-foreground"
                : size === "sm"
                  ? "text-muted-foreground/50 hover:text-foreground"
                  : "text-muted-foreground hover:text-foreground"
            )}
          >
            <Paperclip className="h-4 w-4" />
          </button>
        </TooltipTrigger>
        <TooltipContent>
          {hasAttachments
            ? `${attachments.length} receipt${attachments.length !== 1 ? "s" : ""} attached`
            : "Attach a receipt"}
        </TooltipContent>
      </Tooltip>
      {engaged && (
        <>
          <AttachmentCaptureDialog open={captureOpen} onOpenChange={setCaptureOpen} txId={txId} />
          <AttachmentViewDialog
            attachments={attachments}
            open={viewOpen}
            onOpenChange={setViewOpen}
            onAttachAnother={() => {
              setViewOpen(false);
              setCaptureOpen(true);
            }}
          />
        </>
      )}
    </>
  );
}
