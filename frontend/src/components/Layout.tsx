import { MoreHorizontal, Search } from "lucide-react";
import { useMemo, useState, type ReactNode } from "react";
import { useNavigate, useLocation } from "react-router-dom";
import { DemoBanner } from "@/components/DemoBanner";
import { Omnibar, openOmnibar } from "@/components/Omnibar";
import { SidebarPanel } from "@/components/SidebarPanel";
import { Separator } from "@/components/ui/separator";
import { Sheet, SheetContent, SheetDescription, SheetTitle } from "@/components/ui/sheet";
import { Wordmark } from "@/components/Wordmark";
import { type NavTab } from "@/config/navTabs";
import { useAttentionQueue } from "@/hooks/useAttentionQueue";
import { useDemoMode } from "@/hooks/useDemoMode";
import { useFreshnessProbe } from "@/hooks/useFreshnessProbe";
import { useMonthParam } from "@/hooks/useMonthParam";
import { useNavItems } from "@/hooks/useNavItems";
import { useOverrideSuggestions } from "@/hooks/useOverrideSuggestions";

interface LayoutProps {
  children: ReactNode;
}

export function Layout({ children }: LayoutProps) {
  const navigate = useNavigate();
  const location = useLocation();
  const [moreOpen, setMoreOpen] = useState(false);
  const [month] = useMonthParam();
  // In the static demo the DemoBanner is always shown. Under the default
  // page-scroll model that banner sits above the `h-screen` sticky sidebar and
  // pushes its bottom (the 6-month sparkline's month labels) below the fold. In
  // demo mode we switch to a fixed app-shell: the banner is pinned and the
  // sidebar + main scroll inside the remaining space, so the sidebar height is
  // exactly `viewport − banner` with no clipping (and no magic number). The
  // live app keeps its original page-scroll layout untouched.
  const staticDemo = useDemoMode();
  useFreshnessProbe();
  const { data } = useAttentionQueue(month);
  const attentionCount = data?.count ?? 0;
  const { data: suggestionsData } = useOverrideSuggestions();
  const suggestionCount = suggestionsData?.count ?? 0;

  const navItems = useNavItems();

  const mainNavItems = useMemo(() => navItems.filter((t) => t.section === "main"), [navItems]);
  const workspaceNavItems = useMemo(
    () => navItems.filter((t) => t.section === "workspace"),
    [navItems]
  );
  const primaryNavItems = useMemo(() => mainNavItems.slice(0, 4), [mainNavItems]);
  const overflowMainItems = useMemo(() => mainNavItems.slice(4), [mainNavItems]);
  const overflowNavItems = useMemo(
    () => [...overflowMainItems, ...workspaceNavItems],
    [overflowMainItems, workspaceNavItems]
  );

  const isActive = (href: string) =>
    href === "/" ? location.pathname === "/" : location.pathname.startsWith(href);

  const renderSidebarItem = (item: NavTab) => {
    const active = item.active && isActive(item.href);
    return (
      <button
        key={item.label}
        disabled={!item.active}
        data-tour={item.label === "Insights" ? "insights-nav" : undefined}
        onClick={() => {
          if (!item.active) return;
          if (active && item.href === "/") {
            navigate("/?reset");
          } else {
            navigate(item.href);
          }
        }}
        className={`flex w-full items-center gap-3 rounded-lg px-3 py-2 text-sm transition-colors ${
          active
            ? "bg-accent text-accent-foreground font-medium"
            : item.active
              ? "text-muted-foreground hover:bg-accent/50 hover:text-accent-foreground"
              : "text-muted-foreground cursor-not-allowed"
        }`}
      >
        <item.icon className="h-4 w-4" />
        {item.label}
        {item.label === "Transactions" && attentionCount > 0 && (
          <span className="ml-auto flex h-5 min-w-[1.25rem] items-center justify-center rounded-full bg-brand px-1.5 text-[11px] font-medium text-brand-foreground">
            {attentionCount}
          </span>
        )}
        {item.label === "Categorize" && suggestionCount > 0 && (
          <span className="ml-auto flex h-5 min-w-[1.25rem] items-center justify-center rounded-full bg-brand/10 px-1.5 text-[11px] font-medium text-brand">
            {suggestionCount}
          </span>
        )}
        {!item.active && <span className="ml-auto text-xs text-muted-foreground">Soon</span>}
      </button>
    );
  };

  const renderMoreSheetItem = (item: NavTab) => {
    const active = item.active && isActive(item.href);
    return (
      <button
        key={item.label}
        onClick={() => {
          navigate(item.href);
          setMoreOpen(false);
        }}
        className={`flex items-center gap-3 rounded-lg px-3 py-2.5 text-sm transition-colors ${
          active
            ? "bg-accent text-accent-foreground font-medium"
            : "text-muted-foreground hover:bg-accent/50 hover:text-accent-foreground"
        }`}
      >
        <item.icon className="h-4 w-4" />
        {item.label}
        {item.label === "Categorize" && suggestionCount > 0 && (
          <span className="ml-auto flex h-5 min-w-[1.25rem] items-center justify-center rounded-full bg-brand/10 px-1.5 text-[11px] font-medium text-brand">
            {suggestionCount}
          </span>
        )}
      </button>
    );
  };

  return (
    <div
      className={staticDemo ? "flex h-dvh flex-col overflow-hidden" : "flex min-h-screen flex-col"}
    >
      <DemoBanner />
      <div className={staticDemo ? "flex flex-1 min-h-0" : "flex flex-1"}>
        {/* Desktop sidebar */}
        <aside
          className={
            staticDemo
              ? "hidden md:flex w-[240px] shrink-0 flex-col border-r border-border/50 bg-card h-full overflow-y-auto"
              : "hidden md:flex w-[240px] shrink-0 flex-col border-r border-border/50 bg-card sticky top-0 self-start h-screen overflow-y-auto"
          }
        >
          <div className="flex items-center p-6">
            {/* Plain anchor (not <Link>) so the click escapes the SPA's
              `/demo` basename and lands on the marketing root. */}
            <a
              href="/"
              className="inline-flex items-center rounded-md outline-none focus-visible:ring-2 focus-visible:ring-ring"
              aria-label="Tidings — back to home"
            >
              <Wordmark />
            </a>
          </div>
          <Separator className="bg-border/50" />
          <nav className="p-2">
            {/* Faux search input — the omnibar's single sidebar entry point.
              The border + background distinguish it from the borderless nav
              items below; the Transactions range view is reachable via the
              omnibar's "Advanced search" action. */}
            <button
              type="button"
              aria-label="Search"
              onClick={openOmnibar}
              className="mb-2 flex w-full items-center gap-3 rounded-md border border-border/60 bg-background px-3 py-2 text-sm text-muted-foreground transition-colors hover:border-border hover:text-foreground"
            >
              <Search className="h-4 w-4" />
              Search…
              <kbd className="ml-auto rounded border border-border/60 px-1.5 py-0.5 text-[10px] font-medium text-muted-foreground/70">
                ⌘K
              </kbd>
            </button>
            {mainNavItems.map((item) => renderSidebarItem(item))}
            {workspaceNavItems.length > 0 && (
              <div
                role="presentation"
                className="mt-3 mb-1 px-3 pt-2 pb-1 text-[10px] font-semibold uppercase tracking-wider text-muted-foreground/70"
              >
                Workspace
              </div>
            )}
            {workspaceNavItems.map((item) => renderSidebarItem(item))}
          </nav>
          {/* Persistent content panel — spend total + 6-month sparkline. The
            sparkline is the visual terminus of the sidebar. The two cards
            inside SidebarPanel carry the visual separation; no divider needed. */}
          <div className="mt-auto">
            <SidebarPanel month={month} />
          </div>
        </aside>

        {/* Main content */}
        <main className="flex-1 overflow-auto">
          <div className="mx-auto max-w-6xl p-4 pb-20 md:p-6">{children}</div>
        </main>

        {/* Mobile bottom tab bar — 4 primary + More */}
        <nav className="fixed bottom-0 left-0 right-0 z-50 flex border-t bg-card md:hidden">
          {primaryNavItems.map((item) => {
            const active = item.active && isActive(item.href);
            return (
              <button
                key={item.label}
                disabled={!item.active}
                onClick={() => {
                  if (!item.active) return;
                  if (active && item.href === "/") {
                    navigate("/?reset");
                  } else {
                    navigate(item.href);
                  }
                }}
                aria-label={item.label}
                className={`flex flex-1 flex-col items-center justify-center gap-0.5 py-2 ${
                  active ? "text-foreground" : "text-muted-foreground"
                }`}
              >
                <div className="relative">
                  <item.icon className="h-5 w-5" />
                  {item.label === "Transactions" && attentionCount > 0 && (
                    <span className="absolute -right-2 -top-1 flex h-4 w-4 items-center justify-center rounded-full bg-brand text-[10px] text-brand-foreground font-medium">
                      {attentionCount}
                    </span>
                  )}
                </div>
                <span className="text-[11px] leading-none">{item.label}</span>
              </button>
            );
          })}
          <button
            aria-label="More"
            onClick={() => setMoreOpen(true)}
            className={`flex flex-1 flex-col items-center justify-center gap-0.5 py-2 ${
              overflowNavItems.some((item) => isActive(item.href))
                ? "text-foreground"
                : "text-muted-foreground"
            }`}
          >
            <div className="relative">
              <MoreHorizontal className="h-5 w-5" />
              {suggestionCount > 0 && (
                <span className="absolute -right-2 -top-1 flex h-4 w-4 items-center justify-center rounded-full bg-brand/10 text-[10px] font-medium text-brand">
                  {suggestionCount}
                </span>
              )}
            </div>
            <span className="text-[11px] leading-none">More</span>
          </button>
        </nav>

        {/* Mobile "More" sheet */}
        <Sheet open={moreOpen} onOpenChange={setMoreOpen}>
          <SheetContent>
            <SheetTitle className="sr-only">More</SheetTitle>
            <SheetDescription className="sr-only">More pages and workspace tools</SheetDescription>
            <nav className="flex flex-col gap-1">
              <button
                type="button"
                aria-label="Search"
                onClick={() => {
                  setMoreOpen(false);
                  openOmnibar();
                }}
                className="mb-2 flex items-center gap-3 rounded-md border border-border/60 bg-background px-3 py-2.5 text-sm text-muted-foreground transition-colors hover:border-border hover:text-foreground"
              >
                <Search className="h-4 w-4" />
                Search…
              </button>
              {overflowMainItems.map((item) => renderMoreSheetItem(item))}
              {workspaceNavItems.length > 0 && (
                <div className="mt-3 mb-1 px-3 pt-2 pb-1 text-[10px] font-semibold uppercase tracking-wider text-muted-foreground/70">
                  Workspace
                </div>
              )}
              {workspaceNavItems.map((item) => renderMoreSheetItem(item))}
            </nav>
          </SheetContent>
        </Sheet>
      </div>
      <Omnibar />
    </div>
  );
}
