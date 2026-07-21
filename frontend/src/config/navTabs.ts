import {
  BookOpen,
  Receipt,
  BarChart3,
  Wallet,
  Brain,
  FileCheck,
  FileText,
  Inbox,
  Settings,
  Store,
  Tags,
  TrendingUp,
  type LucideIcon,
} from "lucide-react";

export type NavSection = "main" | "workspace";

export type NavTab = {
  label: string;
  icon: LucideIcon;
  href: string;
  active: boolean;
  section: NavSection;
};

export const SETTINGS_HREF = "/settings";
export const TAX_HREF = "/tax";

export const NAV_TABS: NavTab[] = [
  { label: "Journal", icon: BookOpen, href: "/", active: true, section: "main" },
  { label: "Transactions", icon: Receipt, href: "/transactions", active: true, section: "main" },
  { label: "Summary", icon: BarChart3, href: "/summary", active: true, section: "main" },
  { label: "Budgets", icon: Wallet, href: "/budgets", active: true, section: "main" },
  { label: "Insights", icon: Brain, href: "/insights", active: true, section: "main" },
  { label: "Merchants", icon: Store, href: "/merchants", active: true, section: "main" },
  { label: "Income", icon: TrendingUp, href: "/income-statement", active: true, section: "main" },
  { label: "Statements", icon: FileText, href: "/statements", active: true, section: "workspace" },
  {
    label: "Tax receipts",
    icon: FileCheck,
    href: TAX_HREF,
    active: true,
    section: "workspace",
  },
  { label: "Categorize", icon: Tags, href: "/categorize", active: true, section: "workspace" },
  {
    label: "Needs review",
    icon: Inbox,
    href: "/needs-review",
    active: true,
    section: "workspace",
  },
  { label: "Settings", icon: Settings, href: SETTINGS_HREF, active: true, section: "workspace" },
];

export const CUSTOMIZABLE_TABS: NavTab[] = NAV_TABS.filter((t) => t.href !== SETTINGS_HREF);

export const DEFAULT_ORDER: string[] = CUSTOMIZABLE_TABS.map((t) => t.href);

export function sectionOf(href: string): NavSection {
  return NAV_TABS.find((t) => t.href === href)?.section ?? "main";
}

export function sortBySection(hrefs: string[]): string[] {
  const main: string[] = [];
  const workspace: string[] = [];
  for (const h of hrefs) {
    if (sectionOf(h) === "workspace") workspace.push(h);
    else main.push(h);
  }
  return [...main, ...workspace];
}
