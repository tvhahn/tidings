import type { CategoryGroup } from "@/lib/categoryGroups";
import { groupCategory } from "@/lib/categoryGroups";
import type { MonthSummary } from "@/types/api";

export type CashFlowNodeKind = "source" | "hub" | "group" | "savings" | "drawdown";

export interface CashFlowNode {
  id: string;
  label: string;
  kind: CashFlowNodeKind;
  amount: number;
}

export interface CashFlowLink {
  source: string;
  target: string;
  value: number;
}

export interface CashFlowGraph {
  nodes: CashFlowNode[];
  links: CashFlowLink[];
  totalIncome: number;
  totalSpending: number;
  net: number;
}

const HUB_ID = "__hub__";
const SAVINGS_ID = "__savings__";
const DRAWDOWN_ID = "__drawdown__";
const SOURCE_PREFIX = "src::";
const GROUP_PREFIX = "grp::";

/** Round a dollar amount to whole cents. */
function roundCents(x: number): number {
  return Math.round(x * 100) / 100;
}

/**
 * Round each raw split value to the cent, then force the collection to sum
 * exactly to `target` (also to the cent) by folding the residual onto the
 * first — largest, since callers pass descending-sorted sources — entry.
 */
function allocate(rawValues: number[], target: number): number[] {
  const rounded = rawValues.map(roundCents);
  const sum = roundCents(rounded.reduce((acc, v) => acc + v, 0));
  const residual = roundCents(target - sum);
  const first = rounded[0];
  if (first !== undefined && residual !== 0) {
    rounded[0] = roundCents(first + residual);
  }
  return rounded;
}

export function buildCashFlowGraph(current: MonthSummary, groups: CategoryGroup[]): CashFlowGraph {
  const sources = Object.entries(current.deposits_by_company ?? {})
    .map(([name, info]) => ({ name, amount: info.amount }))
    .filter((s) => s.amount > 0)
    .sort((a, b) => b.amount - a.amount);

  const groupTotals = new Map<string, number>();
  for (const [category, info] of Object.entries(current.by_category ?? {})) {
    if (info.amount <= 0) continue;
    const groupName = groupCategory(category, groups);
    groupTotals.set(groupName, (groupTotals.get(groupName) ?? 0) + info.amount);
  }
  const groupEntries = Array.from(groupTotals.entries())
    .map(([name, amount]) => ({ name, amount }))
    .sort((a, b) => b.amount - a.amount);

  const income = current.deposit_total;
  const spending = current.total_spending;
  const kept = Math.max(income - spending, 0);
  const deficit = Math.max(spending - income, 0);
  const net = income - spending;

  const nodes: CashFlowNode[] = [];
  const links: CashFlowLink[] = [];

  // Per-company income sources on the left.
  for (const s of sources) {
    nodes.push({
      id: SOURCE_PREFIX + s.name,
      label: s.name,
      kind: "source",
      amount: s.amount,
    });
  }

  // Split each source proportionally between Spending and Kept. The spending
  // links are capped so the hub receives exactly min(income, spending); the
  // remainder of income flows to Kept.
  if (income > 0 && sources.length > 0) {
    const spendFraction = Math.min(spending / income, 1);
    const keptFraction = kept / income;
    const spendValues = allocate(
      sources.map((s) => s.amount * spendFraction),
      Math.min(income, spending)
    );
    const keptValues = allocate(
      sources.map((s) => s.amount * keptFraction),
      kept
    );
    sources.forEach((s, i) => {
      const value = spendValues[i];
      if (value !== undefined && value > 0) {
        links.push({ source: SOURCE_PREFIX + s.name, target: HUB_ID, value });
      }
    });
    sources.forEach((s, i) => {
      const value = keptValues[i];
      if (value !== undefined && value > 0) {
        links.push({ source: SOURCE_PREFIX + s.name, target: SAVINGS_ID, value });
      }
    });
  }

  // A deficit is covered by drawing down savings, which feeds the hub.
  if (deficit > 0) {
    nodes.push({
      id: DRAWDOWN_ID,
      label: "From savings",
      kind: "drawdown",
      amount: deficit,
    });
    links.push({ source: DRAWDOWN_ID, target: HUB_ID, value: deficit });
  }

  // The spending hub and its category groups.
  if (spending > 0) {
    nodes.push({ id: HUB_ID, label: "Spending", kind: "hub", amount: spending });
    for (const g of groupEntries) {
      nodes.push({
        id: GROUP_PREFIX + g.name,
        label: g.name,
        kind: "group",
        amount: g.amount,
      });
      links.push({ source: HUB_ID, target: GROUP_PREFIX + g.name, value: g.amount });
    }
  }

  // Money that stayed put.
  if (kept > 0) {
    nodes.push({ id: SAVINGS_ID, label: "Kept", kind: "savings", amount: kept });
  }

  return { nodes, links, totalIncome: income, totalSpending: spending, net };
}
