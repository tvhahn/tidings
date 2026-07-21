import { ParentSize } from "@visx/responsive";
import { Sankey } from "@visx/sankey";
import type { SankeyLink, SankeyNode } from "@visx/sankey";
import { useState } from "react";
import { Card, CardContent, CardHeader, CardTitle } from "@/components/ui/card";
import { useChartTone } from "@/hooks/useChartTone";
import { useMediaQuery } from "@/hooks/useMediaQuery";
import type { CashFlowGraph, CashFlowNode } from "@/lib/cashFlow";
import { getGroupColor, type CategoryGroup, type ChartTone } from "@/lib/categoryGroups";
import { formatCurrency, formatMonthLabelLong } from "@/lib/format";

interface SankeyCashFlowProps {
  graph: CashFlowGraph;
  groups: CategoryGroup[];
  month?: string;
}

type NodeDatum = CashFlowNode;
type LinkDatum = { source: string; target: string; value: number };

const HEIGHT = 520;
const NODE_WIDTH = 14;
const NODE_PADDING = 14;

function colorForNode(node: CashFlowNode, groups: CategoryGroup[], tone: ChartTone): string {
  switch (node.kind) {
    case "source":
      return tone.isDark ? "oklch(0.74 0.07 155)" : "oklch(0.58 0.07 150)";
    case "hub":
      return tone.isDark ? "var(--paper-400)" : "var(--paper-500)";
    case "savings":
      return tone.isDark ? "oklch(0.74 0.06 220)" : "oklch(0.58 0.06 220)";
    case "drawdown":
      return tone.isDark ? "oklch(0.70 0.07 25)" : "oklch(0.58 0.07 25)";
    case "group":
      return getGroupColor(node.label, groups, tone);
  }
}

interface HoveredLink {
  sourceLabel: string;
  targetLabel: string;
  value: number;
  x: number;
  y: number;
}

function MobileBreakdown({ graph }: { graph: CashFlowGraph }) {
  const sources = graph.nodes.filter((n) => n.kind === "source");
  const groups = graph.nodes.filter((n) => n.kind === "group");
  const savings = graph.nodes.find((n) => n.kind === "savings");
  const drawdown = graph.nodes.find((n) => n.kind === "drawdown");

  return (
    <div className="space-y-4 text-sm">
      <p className="text-muted-foreground">
        Cash-flow chart is best on a wider screen. Here's the breakdown:
      </p>
      <section>
        <h3 className="mb-1 font-medium">Income · {formatCurrency(graph.totalIncome)}</h3>
        <ul className="space-y-1 text-muted-foreground">
          {sources.map((s) => (
            <li key={s.id} className="flex justify-between">
              <span className="truncate pr-2">{s.label}</span>
              <span className="tabular-nums">{formatCurrency(s.amount)}</span>
            </li>
          ))}
          {sources.length === 0 && <li>No income recorded.</li>}
        </ul>
      </section>
      <section>
        <h3 className="mb-1 font-medium">Spending · {formatCurrency(graph.totalSpending)}</h3>
        <ul className="space-y-1 text-muted-foreground">
          {groups.map((g) => (
            <li key={g.id} className="flex justify-between">
              <span>{g.label}</span>
              <span className="tabular-nums">{formatCurrency(g.amount)}</span>
            </li>
          ))}
          {groups.length === 0 && <li>No spending recorded.</li>}
        </ul>
      </section>
      {savings && (
        <p className="text-sm">
          <span className="font-medium">Kept · </span>
          <span className="tabular-nums">{formatCurrency(savings.amount)}</span>
        </p>
      )}
      {drawdown && (
        <p className="text-sm">
          <span className="font-medium">From savings · </span>
          <span className="tabular-nums">{formatCurrency(drawdown.amount)}</span>
        </p>
      )}
    </div>
  );
}

function StripFigure({ label, value }: { label: string; value: string }) {
  return (
    <div className="px-2 py-2.5 text-center sm:px-4 sm:py-3">
      <div className="whitespace-nowrap text-[11.5px] text-fg-muted">{label}</div>
      <div className="mt-1 text-[17px] font-semibold leading-tight tabular-nums text-fg sm:text-[20px]">
        {value}
      </div>
    </div>
  );
}

export function SankeyCashFlow({ graph, groups, month }: SankeyCashFlowProps) {
  const tone = useChartTone();
  const isWide = useMediaQuery("(min-width: 768px)");
  const [hovered, setHovered] = useState<HoveredLink | null>(null);

  const root = {
    nodes: graph.nodes.map((n) => ({ ...n })),
    links: graph.links.map((l) => ({ ...l })),
  };

  const nodeColors = new Map<string, string>();
  for (const n of graph.nodes) nodeColors.set(n.id, colorForNode(n, groups, tone));

  const isEmpty = graph.totalIncome === 0 && graph.totalSpending === 0;
  // Category groups sum to spending, so shares read against the spending total.
  const pctBase = graph.totalSpending;

  return (
    <Card className="border-border/50">
      <CardHeader className="pb-2">
        <CardTitle className="text-base font-medium">Cash flow</CardTitle>
      </CardHeader>
      <CardContent>
        {!isEmpty && (
          <div className="mb-4 grid grid-cols-3 divide-x divide-border rounded-[12px] border border-border">
            <StripFigure label="Income" value={formatCurrency(graph.totalIncome)} />
            <StripFigure label="Spent" value={formatCurrency(graph.totalSpending)} />
            {graph.net < 0 ? (
              <StripFigure label="From savings" value={formatCurrency(-graph.net)} />
            ) : (
              <StripFigure label="Kept" value={formatCurrency(Math.max(graph.net, 0))} />
            )}
          </div>
        )}
        {isEmpty ? (
          <div className="flex h-[260px] items-center justify-center text-sm text-muted-foreground">
            No cash flow recorded for this month.
          </div>
        ) : !isWide ? (
          <MobileBreakdown graph={graph} />
        ) : (
          <div className="relative">
            <ParentSize debounceTime={50}>
              {({ width }) => {
                if (width <= 0) return null;
                return (
                  <svg width={width} height={HEIGHT}>
                    <Sankey<NodeDatum, LinkDatum>
                      root={root}
                      size={[width, HEIGHT]}
                      nodeWidth={NODE_WIDTH}
                      nodePadding={NODE_PADDING}
                      nodeId={(n) => (n as unknown as CashFlowNode).id}
                    >
                      {({ graph: laidOut, createPath }) => (
                        <>
                          <g>
                            {laidOut.links.map((link, i) => {
                              const src = link.source as SankeyNode<NodeDatum, LinkDatum>;
                              const tgt = link.target as SankeyNode<NodeDatum, LinkDatum>;
                              const color = nodeColors.get(src.id) ?? "var(--muted-foreground)";
                              const path =
                                createPath(link as SankeyLink<NodeDatum, LinkDatum>) ?? "";
                              const strokeWidth = Math.max(1, link.width ?? 1);
                              const isActive =
                                hovered?.sourceLabel === src.label &&
                                hovered?.targetLabel === tgt.label;
                              return (
                                <path
                                  key={i}
                                  d={path}
                                  fill="none"
                                  stroke={color}
                                  strokeOpacity={isActive ? 0.65 : 0.3}
                                  strokeWidth={strokeWidth}
                                  onMouseEnter={(event) =>
                                    setHovered({
                                      sourceLabel: src.label,
                                      targetLabel: tgt.label,
                                      value: link.value,
                                      x: event.nativeEvent.offsetX,
                                      y: event.nativeEvent.offsetY,
                                    })
                                  }
                                  onMouseLeave={() => setHovered(null)}
                                />
                              );
                            })}
                          </g>
                          <g>
                            {laidOut.nodes.map((node) => {
                              const x0 = node.x0 ?? 0;
                              const x1 = node.x1 ?? 0;
                              const y0 = node.y0 ?? 0;
                              const y1 = node.y1 ?? 0;
                              const color = nodeColors.get(node.id) ?? "var(--foreground)";
                              const isLeftCol = x0 < width / 2;
                              const labelX = isLeftCol ? x1 + 6 : x0 - 6;
                              const labelAnchor = isLeftCol ? "start" : "end";
                              const showInsidePct =
                                node.kind === "group" && y1 - y0 > 14 && pctBase > 0;
                              return (
                                <g key={node.id}>
                                  <rect
                                    x={x0}
                                    y={y0}
                                    width={x1 - x0}
                                    height={Math.max(0, y1 - y0)}
                                    fill={color}
                                    rx={2}
                                  />
                                  <text
                                    x={labelX}
                                    y={(y0 + y1) / 2}
                                    textAnchor={labelAnchor}
                                    dominantBaseline="middle"
                                    fontSize={12}
                                    fill="var(--foreground)"
                                  >
                                    {node.label}
                                    <tspan dx={6} fill="var(--muted-foreground)">
                                      {formatCurrency(node.amount)}
                                    </tspan>
                                  </text>
                                  {showInsidePct && (
                                    <text
                                      x={x1 + 6}
                                      y={(y0 + y1) / 2 + 14}
                                      fontSize={11}
                                      fill="var(--muted-foreground)"
                                    >
                                      {((node.amount / pctBase) * 100).toFixed(1)}%
                                    </text>
                                  )}
                                </g>
                              );
                            })}
                          </g>
                        </>
                      )}
                    </Sankey>
                  </svg>
                );
              }}
            </ParentSize>
            {hovered && (
              <div
                className="pointer-events-none absolute z-10 rounded-md border bg-card px-3 py-1.5 text-xs shadow-md"
                style={{ left: hovered.x + 12, top: hovered.y + 12 }}
              >
                <div className="font-medium">
                  {hovered.sourceLabel} → {hovered.targetLabel}
                </div>
                <div className="text-muted-foreground tabular-nums">
                  {formatCurrency(hovered.value)}
                  {pctBase > 0 && (
                    <span className="ml-1.5">
                      ({((hovered.value / pctBase) * 100).toFixed(1)}%)
                    </span>
                  )}
                </div>
              </div>
            )}
          </div>
        )}
        {!isEmpty && month && (
          <p className="mt-3 text-center text-[12.5px] text-fg-muted">
            Where {formatMonthLabelLong(month)}&apos;s money went
          </p>
        )}
      </CardContent>
    </Card>
  );
}
