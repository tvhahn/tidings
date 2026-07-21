import { ArrowLeft } from "lucide-react";
import { Link } from "react-router-dom";
import { PageHeader } from "@/components/PageHeader";
import { TrashSection } from "@/components/settings/TrashSection";

export function TransactionsTrashPage() {
  return (
    <div className="space-y-6">
      <PageHeader
        title="Trash"
        subtitle="Soft-deleted transactions, grouped by month. Items here are excluded from every report but can be restored. Use the trash-can icon to delete permanently."
        eyebrow={
          <Link
            to="/transactions"
            className="inline-flex items-center gap-1 text-fg-muted transition-colors hover:text-foreground"
          >
            <ArrowLeft className="h-3 w-3" />
            Transactions
          </Link>
        }
      />
      <TrashSection />
    </div>
  );
}
