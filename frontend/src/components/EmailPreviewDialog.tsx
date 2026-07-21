import { Loader2 } from "lucide-react";
import {
  Dialog,
  DialogContent,
  DialogHeader,
  DialogTitle,
  DialogDescription,
} from "@/components/ui/dialog";
import { useTransactionDetail } from "@/hooks/useTransactionDetail";
import type { Transaction } from "@/types/api";

interface EmailPreviewDialogProps {
  transaction: Pick<Transaction, "forwarded_to" | "date_file_name"> | null;
  open: boolean;
  onOpenChange: (open: boolean) => void;
}

export function EmailPreviewDialog({ transaction, open, onOpenChange }: EmailPreviewDialogProps) {
  const { data, isLoading, isError } = useTransactionDetail(
    transaction?.forwarded_to ?? "",
    transaction?.date_file_name ?? "",
    open && !!transaction
  );

  return (
    <Dialog open={open} onOpenChange={onOpenChange}>
      <DialogContent className="max-h-[85vh] max-w-2xl lg:max-w-4xl overflow-y-auto">
        <DialogHeader>
          <DialogTitle className="text-base break-words">
            {data?.subject || "Email Preview"}
          </DialogTitle>
          {data && (data.from_name || data.from_email) ? (
            <DialogDescription asChild>
              <div className="space-y-0.5 text-xs">
                <div>
                  <span className="font-medium text-foreground">From:</span>{" "}
                  {data.from_name ? `${data.from_name} ` : ""}
                  {data.from_email && (
                    <span className="text-muted-foreground">&lt;{data.from_email}&gt;</span>
                  )}
                </div>
                {(data.to_name || data.to_email) && (
                  <div>
                    <span className="font-medium text-foreground">To:</span>{" "}
                    {data.to_name ? `${data.to_name} ` : ""}
                    {data.to_email && (
                      <span className="text-muted-foreground">&lt;{data.to_email}&gt;</span>
                    )}
                  </div>
                )}
              </div>
            </DialogDescription>
          ) : (
            <DialogDescription className="sr-only">
              Source email for the selected transaction
            </DialogDescription>
          )}
        </DialogHeader>

        {isLoading && (
          <div className="flex items-center justify-center py-12">
            <Loader2 className="h-6 w-6 animate-spin text-muted-foreground" />
          </div>
        )}

        {isError && (
          <p className="py-8 text-center text-sm text-muted-foreground">
            Failed to load email content.
          </p>
        )}

        {data && !isLoading && (
          <div className="overflow-hidden min-w-0 rounded-md border bg-muted/30 p-4">
            {data.body ? (
              <pre className="min-w-0 whitespace-pre-wrap break-all font-sans text-sm leading-relaxed">
                {data.body}
              </pre>
            ) : (
              <p className="text-center text-sm text-muted-foreground">No email body available.</p>
            )}
          </div>
        )}
      </DialogContent>
    </Dialog>
  );
}
