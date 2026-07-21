import { lazy, Suspense, useEffect } from "react";
import { Routes, Route, Navigate, useLocation } from "react-router-dom";
import { AppErrorBoundary } from "@/components/AppErrorBoundary";
import { AuthBoundary } from "@/components/AuthBoundary";
import { CategorizationBanner } from "@/components/CategorizationBanner";
import { DemoErrorBoundary } from "@/components/DemoErrorBoundary";
import { DemoFlashBanner } from "@/components/DemoFlashBanner";
import { DemoTour } from "@/components/DemoTour";
import { Layout } from "@/components/Layout";
import { SetupBanner } from "@/components/SetupBanner";
import { Skeleton } from "@/components/ui/skeleton";
import { TooltipProvider } from "@/components/ui/tooltip";
import { useDemoMode } from "@/hooks/useDemoMode";
import { useTaxTrackingEnabled } from "@/hooks/useTaxTrackingEnabled";
import { setDemoFlash } from "@/lib/demoFlash";
import { JournalPage } from "@/pages/JournalPage";

// JournalPage is the default route and first thing the user sees — keep it
// eagerly imported. The rest are split out so Recharts (SummaryPage) and the
// heavier pages don't bloat the initial bundle.
const TransactionsPage = lazy(() =>
  import("@/pages/TransactionsPage").then((m) => ({ default: m.TransactionsPage }))
);
const TransactionsTrashPage = lazy(() =>
  import("@/pages/TransactionsTrashPage").then((m) => ({ default: m.TransactionsTrashPage }))
);
const SummaryPage = lazy(() =>
  import("@/pages/SummaryPage").then((m) => ({ default: m.SummaryPage }))
);
const BudgetPage = lazy(() =>
  import("@/pages/BudgetPage").then((m) => ({ default: m.BudgetPage }))
);
const BudgetEditPage = lazy(() =>
  import("@/pages/BudgetEditPage").then((m) => ({ default: m.BudgetEditPage }))
);
const InsightsPage = lazy(() =>
  import("@/pages/InsightsPage").then((m) => ({ default: m.InsightsPage }))
);
const MerchantsPage = lazy(() =>
  import("@/pages/MerchantsPage").then((m) => ({ default: m.MerchantsPage }))
);
const StatementsPage = lazy(() =>
  import("@/pages/StatementsPage").then((m) => ({ default: m.StatementsPage }))
);
const CategorizePage = lazy(() =>
  import("@/pages/CategorizePage").then((m) => ({ default: m.CategorizePage }))
);
const NeedsReviewPage = lazy(() =>
  import("@/pages/NeedsReviewPage").then((m) => ({ default: m.NeedsReviewPage }))
);
const SettingsLayout = lazy(() =>
  import("@/pages/settings/SettingsLayout").then((m) => ({ default: m.SettingsLayout }))
);
const SettingsPages = {
  Display: lazy(() => import("@/pages/settings/pages").then((m) => ({ default: m.DisplayPage }))),
  Navigation: lazy(() =>
    import("@/pages/settings/pages").then((m) => ({ default: m.NavigationPage }))
  ),
  Timezone: lazy(() => import("@/pages/settings/pages").then((m) => ({ default: m.TimezonePage }))),
  Features: lazy(() => import("@/pages/settings/pages").then((m) => ({ default: m.FeaturesPage }))),
  Intelligence: lazy(() =>
    import("@/pages/settings/pages").then((m) => ({ default: m.IntelligencePage }))
  ),
  Password: lazy(() => import("@/pages/settings/pages").then((m) => ({ default: m.PasswordPage }))),
  Sessions: lazy(() => import("@/pages/settings/pages").then((m) => ({ default: m.SessionsPage }))),
  Activity: lazy(() => import("@/pages/settings/pages").then((m) => ({ default: m.ActivityPage }))),
  System: lazy(() => import("@/pages/settings/pages").then((m) => ({ default: m.SystemPage }))),
  Backup: lazy(() => import("@/pages/settings/pages").then((m) => ({ default: m.BackupPage }))),
};
const IncomeStatementPage = lazy(() =>
  import("@/pages/IncomeStatementPage").then((m) => ({ default: m.IncomeStatementPage }))
);
const TaxPage = lazy(() => import("@/pages/TaxPage").then((m) => ({ default: m.TaxPage })));

function PageFallback() {
  return (
    <div className="space-y-4">
      <Skeleton className="h-8 w-48" />
      <Skeleton className="h-64 w-full rounded-xl" />
      <Skeleton className="h-32 w-full rounded-xl" />
    </div>
  );
}

function DemoCatchAll() {
  const location = useLocation();
  useEffect(() => {
    setDemoFlash(
      `That link (${location.pathname}) requires live data. Here's the Journal view instead.`
    );
  }, [location.pathname]);
  return <Navigate to="/" replace />;
}

// Tax tracking is an instance-level opt-out (Settings → Features). When it's
// off the `/tax` workspace is unreachable via nav; guard the route too so a
// direct URL or a stale bookmark lands on the Journal instead of a dead page.
function TaxRoute() {
  const taxEnabled = useTaxTrackingEnabled();
  if (!taxEnabled) return <Navigate to="/" replace />;
  return <TaxPage />;
}

function AppRoutes() {
  return (
    <Suspense fallback={<PageFallback />}>
      <Routes>
        <Route path="/" element={<JournalPage />} />
        <Route path="/transactions" element={<TransactionsPage />} />
        <Route path="/transactions/trash" element={<TransactionsTrashPage />} />
        <Route path="/summary" element={<SummaryPage />} />
        <Route path="/budgets" element={<BudgetPage />} />
        <Route path="/budgets/edit" element={<BudgetEditPage />} />
        <Route path="/insights" element={<InsightsPage />} />
        <Route path="/merchants" element={<MerchantsPage />} />
        <Route path="/income-statement" element={<IncomeStatementPage />} />
        <Route path="/statements" element={<StatementsPage />} />
        <Route path="/tax" element={<TaxRoute />} />
        <Route path="/categorize" element={<CategorizePage />} />
        <Route path="/needs-review" element={<NeedsReviewPage />} />
        <Route path="/settings" element={<SettingsLayout />}>
          <Route index element={<Navigate to="/settings/display" replace />} />
          <Route path="display" element={<SettingsPages.Display />} />
          <Route path="navigation" element={<SettingsPages.Navigation />} />
          <Route path="timezone" element={<SettingsPages.Timezone />} />
          <Route path="features" element={<SettingsPages.Features />} />
          <Route path="intelligence" element={<SettingsPages.Intelligence />} />
          <Route path="password" element={<SettingsPages.Password />} />
          <Route path="sessions" element={<SettingsPages.Sessions />} />
          <Route path="activity" element={<SettingsPages.Activity />} />
          <Route path="system" element={<SettingsPages.System />} />
          <Route path="backup" element={<SettingsPages.Backup />} />
        </Route>
        <Route path="*" element={<DemoCatchAll />} />
      </Routes>
    </Suspense>
  );
}

function App() {
  const demo = useDemoMode();
  return (
    <TooltipProvider delayDuration={400}>
      <AuthBoundary>
        {({ tofu }) => (
          <>
            {tofu ? <SetupBanner /> : null}
            {!demo ? <CategorizationBanner /> : null}
            <Layout>
              {demo ? (
                <DemoErrorBoundary>
                  <DemoFlashBanner />
                  <AppRoutes />
                </DemoErrorBoundary>
              ) : (
                <AppErrorBoundary>
                  <AppRoutes />
                </AppErrorBoundary>
              )}
            </Layout>
            {demo && <DemoTour />}
          </>
        )}
      </AuthBoundary>
    </TooltipProvider>
  );
}

export default App;
