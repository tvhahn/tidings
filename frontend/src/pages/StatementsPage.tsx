import { useQueryClient } from "@tanstack/react-query";
import { CheckCircle2, ArrowLeft, Download, FileText, Lock } from "lucide-react";
import { useState } from "react";
import { DemoSelfHostedModal } from "@/components/DemoSelfHostedModal";
import { PageHeader } from "@/components/PageHeader";
import { StatementHistory } from "@/components/StatementHistory";
import { StatementReview } from "@/components/StatementReview";
import { StatementUpload } from "@/components/StatementUpload";
import { Button } from "@/components/ui/button";
import { Card, CardContent } from "@/components/ui/card";
import { Skeleton } from "@/components/ui/skeleton";
import { useDemoMode } from "@/hooks/useDemoMode";
import { useStatement, useReparseStatement } from "@/hooks/useStatement";
import { useUploadStatement, useImportStatement } from "@/hooks/useStatementImport";
import { useStatements, useDeleteStatement } from "@/hooks/useStatements";
import { getStatementDownloadUrl } from "@/lib/api";
import { SETUP_ANCHOR } from "@/lib/demoConstants";
import { queryKeys } from "@/lib/queryConfigs";
import { transformDetailToUploadFormat } from "@/lib/statementTransform";
import type { StatementUploadResponse, ImportAction, ImportResponse } from "@/types/api";

type PageState = "upload" | "processing" | "review" | "importing" | "complete";

function formatPeriodHint(
  start: string | null | undefined,
  end: string | null | undefined
): string {
  const fmt = (d: string) => {
    const date = new Date(d + "T00:00:00");
    return date.toLocaleDateString("en-US", { month: "short", year: "numeric" });
  };
  if (start && end) {
    const s = fmt(start),
      e = fmt(end);
    return s === e ? s : `${s} – ${e}`;
  }
  return start ? fmt(start) : end ? fmt(end) : "the statement period";
}

export function StatementsPage() {
  const demo = useDemoMode();
  if (demo) return <StatementsPageDemo />;
  return <StatementsPageContent />;
}

function StatementsPageDemo() {
  const statementsQuery = useStatements();
  const [gatedFeature, setGatedFeature] = useState<string | null>(null);
  const gated = (feature: string) => () => setGatedFeature(feature);
  return (
    <div className="space-y-6">
      <PageHeader
        title="Statements"
        subtitle="Bank statement PDFs — upload one to catch transactions that never arrived by email."
      />
      <Card className="border-dashed">
        <CardContent className="p-6 flex flex-col sm:flex-row sm:items-center gap-4">
          <div className="shrink-0 rounded-full bg-muted p-3">
            <Lock className="h-5 w-5 text-muted-foreground" />
          </div>
          <div className="flex-1 space-y-1">
            <h3 className="text-sm font-medium">PDF upload runs on your own machine</h3>
            <p className="text-sm text-muted-foreground">
              The hosted demo includes a real upload history below so you can see how the
              reconciliation works. Self-host to parse your own PDFs.
            </p>
          </div>
          <a
            href={SETUP_ANCHOR}
            target="_blank"
            rel="noreferrer"
            className="shrink-0 inline-flex items-center justify-center rounded-md text-sm font-medium
              ring-offset-background transition-colors focus-visible:outline-none focus-visible:ring-2
              focus-visible:ring-ring focus-visible:ring-offset-2 bg-primary text-primary-foreground
              hover:bg-primary/90 h-9 px-4"
          >
            Self-host this
          </a>
        </CardContent>
      </Card>
      {statementsQuery.data && statementsQuery.data.statements.length > 0 && (
        <StatementHistory
          statements={statementsQuery.data.statements}
          onSelect={gated("Statement review")}
          onReparse={gated("Re-parsing")}
          onDelete={gated("Deleting statements")}
          onDownload={gated("PDF download")}
        />
      )}
      <DemoSelfHostedModal
        open={gatedFeature != null}
        onOpenChange={(open) => {
          if (!open) setGatedFeature(null);
        }}
        featureName={gatedFeature ?? ""}
        description="Statement PDFs live on your own machine in a self-hosted install. The demo's upload history is sample data, so there are no files behind it."
      />
      {statementsQuery.data && statementsQuery.data.statements.length === 0 && (
        <Card>
          <CardContent className="p-8 flex flex-col items-center gap-3 text-center">
            <FileText className="h-8 w-8 text-muted-foreground" />
            <p className="text-sm text-muted-foreground">
              The hosted demo doesn't include sample statements right now.
            </p>
          </CardContent>
        </Card>
      )}
    </div>
  );
}

function StatementsPageContent() {
  const [state, setState] = useState<PageState>("upload");
  const [uploadData, setUploadData] = useState<StatementUploadResponse | null>(null);
  const [importResult, setImportResult] = useState<ImportResponse | null>(null);
  const [selectedFile, setSelectedFile] = useState<File | null>(null);
  const [selectedStatementId, setSelectedStatementId] = useState<string | null>(null);
  const [reparsingId, setReparsingId] = useState<string | null>(null);

  const queryClient = useQueryClient();
  const uploadMutation = useUploadStatement();
  const importMutation = useImportStatement();
  const statementsQuery = useStatements();
  const deleteMutation = useDeleteStatement();
  const reparseMutation = useReparseStatement();
  const statementDetail = useStatement(
    selectedStatementId && state === "review" ? selectedStatementId : null
  );

  const handleFileSelected = (file: File) => {
    setSelectedFile(file);
    setState("processing");
    uploadMutation.mutate(file, {
      onSuccess: (data) => {
        setUploadData(data);
        setSelectedStatementId(data.statement_id);
        setState("review");
        queryClient.invalidateQueries({ queryKey: queryKeys.statements() });
      },
      onError: () => {
        setState("upload");
      },
    });
  };

  // When resuming from history, we need to transform the detail data.
  // Defined before handleImport so it can be used there.
  const reviewData: StatementUploadResponse | null = (() => {
    if (uploadData) return uploadData;
    if (statementDetail.data && selectedStatementId) {
      return transformDetailToUploadFormat(statementDetail.data);
    }
    return null;
  })();

  const handleImport = (actions: ImportAction[]) => {
    if (!reviewData || (!selectedFile && !selectedStatementId)) return;

    setState("importing");
    importMutation.mutate(
      {
        actions,
        metadata: reviewData.metadata,
        transactions: reviewData.transactions,
        filename: selectedFile?.name ?? reviewData.metadata.institution + ".pdf",
        statement_id: selectedStatementId ?? null,
      },
      {
        onSuccess: (result) => {
          setImportResult(result);
          setState("complete");
          queryClient.invalidateQueries({ queryKey: queryKeys.statements() });
          queryClient.invalidateQueries({ queryKey: queryKeys.overrideSuggestions() });
        },
        onError: () => {
          setState("review");
        },
      }
    );
  };

  const handleReset = () => {
    setState("upload");
    setUploadData(null);
    setImportResult(null);
    setSelectedFile(null);
    setSelectedStatementId(null);
  };

  const handleHistorySelect = (id: string) => {
    setSelectedStatementId(id);
    // We'll load data from useStatement hook
    setState("review");
  };

  const handleHistoryReparse = (id: string) => {
    setReparsingId(id);
    reparseMutation.mutate(id, {
      onSuccess: (data) => {
        setReparsingId(null);
        setSelectedStatementId(id);
        setUploadData(transformDetailToUploadFormat(data));
        setState("review");
      },
      onError: () => {
        setReparsingId(null);
      },
    });
  };

  const handleHistoryDelete = (id: string) => {
    deleteMutation.mutate(id);
  };

  const handleBack = () => {
    setState("upload");
    setUploadData(null);
    setSelectedStatementId(null);
    setSelectedFile(null);
  };

  return (
    <div className="space-y-6">
      <PageHeader
        title="Statements"
        subtitle="Bank statement PDFs — upload one to catch transactions that never arrived by email."
      />

      {state === "upload" && (
        <>
          <StatementUpload
            isPending={uploadMutation.isPending}
            onFileSelected={handleFileSelected}
          />
          {statementsQuery.data && (
            <StatementHistory
              statements={statementsQuery.data.statements}
              onSelect={handleHistorySelect}
              onReparse={handleHistoryReparse}
              onDelete={handleHistoryDelete}
              isReparsing={reparseMutation.isPending}
              reparsingId={reparsingId}
            />
          )}
        </>
      )}

      {state === "processing" && (
        <Card className="border-border/50">
          <CardContent className="p-8">
            <div className="flex flex-col items-center gap-4">
              <div className="flex items-center gap-2">
                <Skeleton className="h-4 w-4 rounded-full" />
                <Skeleton className="h-4 w-4 rounded-full" />
                <Skeleton className="h-4 w-4 rounded-full" />
              </div>
              <p className="text-sm text-muted-foreground">
                Parsing statement and reconciling against existing transactions...
              </p>
            </div>
          </CardContent>
        </Card>
      )}

      {state === "review" && (
        <>
          <div className="flex items-center gap-2">
            <Button variant="ghost" size="sm" onClick={handleBack}>
              <ArrowLeft className="h-4 w-4 mr-1" />
              Back
            </Button>
            {selectedStatementId && (
              <Button
                variant="ghost"
                size="sm"
                onClick={() => window.open(getStatementDownloadUrl(selectedStatementId), "_blank")}
              >
                <Download className="h-4 w-4 mr-1" />
                Download PDF
              </Button>
            )}
          </div>
          {statementDetail.isLoading && !uploadData && (
            <Card className="border-border/50">
              <CardContent className="p-8">
                <div className="flex flex-col items-center gap-4">
                  <div className="flex items-center gap-2">
                    <Skeleton className="h-4 w-4 rounded-full" />
                    <Skeleton className="h-4 w-4 rounded-full" />
                    <Skeleton className="h-4 w-4 rounded-full" />
                  </div>
                  <p className="text-sm text-muted-foreground">Loading statement...</p>
                </div>
              </CardContent>
            </Card>
          )}
          {reviewData?.metadata.parsed_with_ai && (
            <div className="rounded-lg border border-border/50 p-3 text-sm text-muted-foreground">
              This statement was read by your AI provider — Tidings has no built-in parser for{" "}
              {reviewData.metadata.institution}. Every amount was verified against the PDF text, but
              check dates and descriptions before importing.
            </div>
          )}
          {reviewData && (
            <StatementReview
              data={reviewData}
              onImport={handleImport}
              isImporting={false}
              statementId={selectedStatementId}
            />
          )}
        </>
      )}

      {state === "importing" && (
        <Card className="border-border/50">
          <CardContent className="p-8">
            <div className="flex flex-col items-center gap-4">
              <div className="flex items-center gap-2">
                <Skeleton className="h-4 w-4 rounded-full" />
                <Skeleton className="h-4 w-4 rounded-full" />
                <Skeleton className="h-4 w-4 rounded-full" />
              </div>
              <p className="text-sm text-muted-foreground">Importing transactions to DynamoDB...</p>
            </div>
          </CardContent>
        </Card>
      )}

      {state === "complete" && importResult && (
        <Card className="border-border/50">
          <CardContent className="p-8">
            <div className="flex flex-col items-center gap-4">
              <CheckCircle2 className="h-10 w-10 text-status-success" />
              <div className="text-center">
                <p className="font-serif text-[20px] font-semibold text-fg">Import complete</p>
                <div className="mt-2 flex items-center gap-4 text-sm text-muted-foreground">
                  {importResult.imported > 0 && <span>{importResult.imported} imported</span>}
                  {importResult.enriched > 0 && <span>{importResult.enriched} enriched</span>}
                  <span>{importResult.skipped} skipped</span>
                  {importResult.duplicates > 0 && <span>{importResult.duplicates} duplicates</span>}
                </div>
                {reviewData?.metadata && (
                  <p className="mt-2 text-xs text-muted-foreground">
                    Transactions cover{" "}
                    {formatPeriodHint(
                      reviewData.metadata.period_start,
                      reviewData.metadata.period_end
                    )}
                    {" — "}navigate to that month on the Transactions page to see them.
                  </p>
                )}
              </div>
              <Button variant="outline" onClick={handleReset}>
                Back to Statements
              </Button>
            </div>
          </CardContent>
        </Card>
      )}
    </div>
  );
}
