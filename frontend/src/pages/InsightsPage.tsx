import { useQueryClient } from "@tanstack/react-query";
import { Brain, ChevronLeft, ChevronRight, RotateCw } from "lucide-react";
import { useEffect, useRef, useState } from "react";
import Markdown from "react-markdown";
import remarkGfm from "remark-gfm";
import { AnomaliesCard } from "@/components/insights/AnomaliesCard";
import { MomentumCard } from "@/components/insights/MomentumCard";
import { InsightsSparkline } from "@/components/InsightsSparkline";
import { MonthPicker } from "@/components/MonthPicker";
import { PageHeader } from "@/components/PageHeader";
import { Button } from "@/components/ui/button";
import { useDemoMode } from "@/hooks/useDemoMode";
import { useInsightsContext } from "@/hooks/useInsightsContext";
import { useInsightsStatus, useGenerateInsights } from "@/hooks/useInsightsGeneration";
import { useMonthParam } from "@/hooks/useMonthParam";
import { useSavedInsights, useSavedInsight } from "@/hooks/useSavedInsights";
import { queryKeys } from "@/lib/queryConfigs";

export function InsightsPage() {
  const [month, setMonth] = useMonthParam();
  const demo = useDemoMode();
  const queryClient = useQueryClient();

  // Saved insights from disk (React Query — survives navigation). The list is
  // newest-first, so index 0 is the most recent briefing for the month.
  const { data: savedList, isLoading: listLoading } = useSavedInsights(month);
  const savedBriefings = savedList ?? [];

  // Which saved briefing is on screen. Defaults to the newest. We track the id
  // (not the index) so the selection survives a list refetch even if ordering
  // shifts; when the tracked id is gone — or unset — we fall back to the newest.
  const [selectedId, setSelectedId] = useState<string | null>(null);
  const selectedIndex = selectedId ? savedBriefings.findIndex((b) => b.id === selectedId) : -1;
  const viewIndex = selectedIndex >= 0 ? selectedIndex : 0;
  const viewedBriefing = savedBriefings[viewIndex] ?? null;
  const viewedId = viewedBriefing?.id ?? null;
  const viewedGeneratedAt = viewedBriefing?.generated_at ?? null;
  const { data: savedInsight, isLoading: insightLoading } = useSavedInsight(viewedId, month);

  // Pager across the month's briefings. Position counts from the newest, so the
  // newest reads "1 of N". "Previous" walks to an older briefing (further down
  // the newest-first list); "Next" walks back toward the newest.
  const briefingCount = savedBriefings.length;
  const showPager = briefingCount > 1;
  const atNewest = viewIndex <= 0;
  const atOldest = viewIndex >= briefingCount - 1;
  const viewOlder = () => {
    const older = savedBriefings[viewIndex + 1];
    if (older) setSelectedId(older.id);
  };
  const viewNewer = () => {
    const newer = savedBriefings[viewIndex - 1];
    if (newer) setSelectedId(newer.id);
  };

  // Reset to the newest briefing whenever the month changes.
  useEffect(() => {
    setSelectedId(null);
  }, [month]);

  // Structured deltas + anomalies — always-on, doesn't wait for a briefing.
  const { data: insightsContext } = useInsightsContext(month);

  // Background generation status (polling)
  const { data: genStatus } = useInsightsStatus();
  const generateMutation = useGenerateInsights();

  const isGenerating = genStatus?.status === "running" && genStatus?.month === month;
  const genError =
    genStatus?.status === "error" && genStatus?.month === month ? genStatus.error : null;

  // When generation finishes (running → idle), refresh saved insights list
  const prevStatusRef = useRef(genStatus?.status);
  useEffect(() => {
    const prev = prevStatusRef.current;
    const curr = genStatus?.status;
    prevStatusRef.current = curr;
    if (prev === "running" && curr === "idle") {
      queryClient.invalidateQueries({ queryKey: queryKeys.insightsList(month) });
      // Surface the briefing that just finished — it lands at the top of the list.
      setSelectedId(null);
    }
  }, [genStatus?.status, month, queryClient]);

  const isLoadingSaved = listLoading || (!!viewedId && insightLoading);
  const displayContent = savedInsight?.content || "";
  const hasContent = displayContent.length > 0;
  // Figure-check result, when the loaded briefing carries a validation sidecar.
  // Silence is the success state — the line only appears when something did not
  // trace back to the underlying data.
  const unmatchedFigures = savedInsight?.validation?.summary.unmatched ?? 0;
  const showIdle = !isGenerating && !hasContent && !isLoadingSaved && !genError;

  const handleGenerate = () => {
    generateMutation.mutate(month);
  };

  return (
    <div className="space-y-4">
      <PageHeader
        title="Insights"
        actions={
          <>
            <MonthPicker month={month} onChange={setMonth} />
            {hasContent && !isGenerating && !demo && (
              <Button variant="ghost" size="sm" onClick={handleGenerate}>
                <RotateCw className="mr-1.5 h-3.5 w-3.5" />
                Regenerate
              </Button>
            )}
          </>
        }
      />

      {/* Calm daily-spend sparkline header card. */}
      <InsightsSparkline month={month} />

      {/* Structured month-over-month + quiet-anomaly cards. Visible whenever
          the context fetch succeeds, regardless of briefing presence. */}
      {insightsContext && (
        <div className="grid gap-4 sm:grid-cols-2">
          <MomentumCard deltas={insightsContext.category_deltas} month={month} />
          <AnomaliesCard anomalies={insightsContext.anomalies} month={month} />
        </div>
      )}

      {/* Loading saved insights */}
      {isLoadingSaved && !isGenerating && (
        <div className="rounded-[14px] border border-border bg-card px-5 py-6">
          <div className="flex items-center gap-3 text-fg-muted">
            <span className="flex gap-1" aria-hidden>
              <span className="h-2 w-2 rounded-full bg-current animate-bounce [animation-delay:-0.3s]" />
              <span className="h-2 w-2 rounded-full bg-current animate-bounce [animation-delay:-0.15s]" />
              <span className="h-2 w-2 rounded-full bg-current animate-bounce" />
            </span>
            <span className="text-sm">Loading saved briefing</span>
          </div>
        </div>
      )}

      {/* Idle state — no saved insights, no generation */}
      {showIdle && (
        <div className="rounded-[14px] border border-border bg-card px-5 py-10">
          <div className="flex flex-col items-center gap-4">
            <Brain className="h-10 w-10 text-fg-muted" aria-hidden />
            <div className="text-center">
              <p className="font-serif text-[20px] font-semibold text-fg">Spending intelligence</p>
              <p className="mt-2 max-w-md text-[13px] leading-relaxed text-fg-muted">
                Generate a briefing that reviews this month's spending against your budgets and
                surfaces patterns you might miss.
              </p>
            </div>
            {!demo && (
              <Button onClick={handleGenerate} className="mt-1">
                Generate briefing
              </Button>
            )}
            {demo && (
              <p className="mt-1 max-w-md text-center text-[12px] text-fg-muted">
                Briefings are pre-generated in the hosted demo — pick a past month above to read
                one. Run the app locally to generate your own.
              </p>
            )}
            <div className="mt-4 w-full max-w-md border-t border-border pt-4">
              <p className="mb-2 text-center text-[10.5px] font-medium uppercase tracking-[0.06em] text-fg-muted">
                A briefing typically covers
              </p>
              <ul className="grid grid-cols-2 gap-x-4 gap-y-1 text-[12px] text-fg-muted">
                <li>· The month in brief</li>
                <li>· What changed</li>
                <li>· Where the month went</li>
                <li>· Worth attention</li>
                <li>· Your notes</li>
                <li>· Looking ahead</li>
              </ul>
            </div>
          </div>
        </div>
      )}

      {/* Generating state */}
      {isGenerating && (
        <div className="rounded-[14px] border border-border bg-card px-5 py-6">
          <div className="flex items-center gap-3 text-fg-muted">
            <span className="flex gap-1" aria-hidden>
              <span className="h-2 w-2 rounded-full bg-current animate-bounce [animation-delay:-0.3s]" />
              <span className="h-2 w-2 rounded-full bg-current animate-bounce [animation-delay:-0.15s]" />
              <span className="h-2 w-2 rounded-full bg-current animate-bounce" />
            </span>
            <span className="text-sm">Generating briefing — usually about 30 seconds</span>
          </div>
        </div>
      )}

      {/* Saved content display */}
      {hasContent && !isGenerating && (
        <div className="rounded-[14px] border border-border bg-card px-5 py-6 sm:px-6">
          {(viewedGeneratedAt || showPager || unmatchedFigures > 0) && (
            <div className="mb-4 space-y-1">
              {(viewedGeneratedAt || showPager) && (
                <div className="flex flex-wrap items-center gap-x-3 gap-y-1">
                  {viewedGeneratedAt && (
                    <p className="text-[10.5px] font-medium uppercase tracking-[0.06em] text-fg-muted">
                      Generated{" "}
                      {new Date(viewedGeneratedAt).toLocaleDateString("en-US", {
                        month: "short",
                        day: "numeric",
                        year: "numeric",
                        hour: "numeric",
                        minute: "2-digit",
                      })}
                    </p>
                  )}
                  {showPager && (
                    <div className="flex items-center gap-0.5">
                      <Button
                        variant="ghost"
                        size="icon"
                        className="h-6 w-6"
                        onClick={viewOlder}
                        disabled={atOldest}
                        aria-label="Previous briefing"
                      >
                        <ChevronLeft className="h-3.5 w-3.5" />
                      </Button>
                      <span className="text-[10.5px] font-medium uppercase tracking-[0.06em] text-fg-muted">
                        {viewIndex + 1} of {briefingCount}
                      </span>
                      <Button
                        variant="ghost"
                        size="icon"
                        className="h-6 w-6"
                        onClick={viewNewer}
                        disabled={atNewest}
                        aria-label="Next briefing"
                      >
                        <ChevronRight className="h-3.5 w-3.5" />
                      </Button>
                    </div>
                  )}
                </div>
              )}
              {unmatchedFigures > 0 && (
                <p className="text-[12px] leading-relaxed text-fg-muted">
                  {unmatchedFigures === 1
                    ? "1 figure in this briefing doesn't match the underlying data."
                    : `${unmatchedFigures} figures in this briefing don't match the underlying data.`}
                </p>
              )}
            </div>
          )}
          <div className="prose prose-sm dark:prose-invert max-w-none prose-headings:font-serif prose-headings:tracking-[-0.01em] prose-p:text-[14px] prose-p:leading-[1.55]">
            <Markdown remarkPlugins={[remarkGfm]}>{displayContent}</Markdown>
          </div>
        </div>
      )}

      {/* Error state — calm, observant */}
      {genError && !isGenerating && (
        <div className="rounded-[14px] border border-status-danger-calm/30 bg-status-danger-calm/[0.025] px-5 py-5">
          <p className="text-[10.5px] font-medium uppercase tracking-[0.06em] text-fg-muted">
            Notice
          </p>
          <p className="mt-1.5 text-[13px] text-status-danger-calm-text">{genError}</p>
          <Button variant="ghost" size="sm" className="mt-3" onClick={handleGenerate}>
            Try again
          </Button>
        </div>
      )}

      {/* 409 conflict from mutation */}
      {generateMutation.error &&
        (generateMutation.error as Error & { status?: number }).status === 409 && (
          <div className="rounded-[14px] border border-border bg-card px-5 py-4">
            <p className="text-[10.5px] font-medium uppercase tracking-[0.06em] text-fg-muted">
              Notice
            </p>
            <p className="mt-1 text-[13px] text-fg">
              A briefing is already in progress for this month.
            </p>
          </div>
        )}
    </div>
  );
}
