import { NavLink, Outlet, useLocation, useNavigate } from "react-router-dom";
import { PageHeader } from "@/components/PageHeader";
import { useCoverage } from "@/hooks/useCoverage";
import { isDemoMode } from "@/hooks/useDemoMode";
import { cn } from "@/lib/utils";

type ScopeGroup = {
  id: string;
  label: string;
  scope: "device" | "instance" | "account";
  items: { to: string; label: string }[];
};

const GROUPS: ScopeGroup[] = [
  {
    id: "personal",
    label: "Personal",
    scope: "device",
    items: [
      { to: "/settings/display", label: "Display" },
      { to: "/settings/navigation", label: "Navigation" },
    ],
  },
  {
    id: "workspace",
    label: "Workspace",
    scope: "instance",
    items: [
      { to: "/settings/timezone", label: "Timezone" },
      { to: "/settings/features", label: "Features" },
      { to: "/settings/intelligence", label: "Intelligence" },
    ],
  },
  {
    id: "account",
    label: "Account",
    scope: "account",
    items: [
      { to: "/settings/password", label: "Password" },
      { to: "/settings/sessions", label: "Sessions" },
      { to: "/settings/activity", label: "Activity" },
      { to: "/settings/system", label: "System" },
    ],
  },
  {
    id: "backup",
    label: "Backup",
    scope: "instance",
    items: [{ to: "/settings/backup", label: "Backup" }],
  },
];

// Account-shaped pages have no body in demo mode — drop their nav entries
// too so the rail never leads to a blank pane.
const DEMO_HIDDEN_ITEMS = new Set(["/settings/password", "/settings/sessions"]);

const VISIBLE_GROUPS: ScopeGroup[] = isDemoMode()
  ? GROUPS.map((group) => ({
      ...group,
      items: group.items.filter((item) => !DEMO_HIDDEN_ITEMS.has(item.to)),
    })).filter((group) => group.items.length > 0)
  : GROUPS;

function MobileSettingsNav() {
  const navigate = useNavigate();
  const { pathname } = useLocation();
  return (
    <label className="block md:hidden">
      <span className="sr-only">Settings section</span>
      <select
        aria-label="Settings section"
        value={pathname}
        onChange={(e) => navigate(e.target.value)}
        className="h-9 w-full rounded-md border border-border bg-background px-3 text-sm shadow-sm focus-visible:outline-none focus-visible:ring-1 focus-visible:ring-ring"
      >
        {VISIBLE_GROUPS.map((group) => (
          <optgroup key={group.id} label={group.label}>
            {group.items.map((item) => (
              <option key={item.to} value={item.to}>
                {item.label}
              </option>
            ))}
          </optgroup>
        ))}
      </select>
    </label>
  );
}

function DesktopSettingsRail() {
  const { data: coverage } = useCoverage();
  // Quiet excludes dormant — a dormant institution has decayed out of the count
  // (same rule the /health quiet_institutions signal uses).
  const quietCount = coverage?.institutions.filter((i) => i.status === "quiet").length ?? 0;

  return (
    <nav aria-label="Settings sections" className="hidden md:block md:w-56 md:shrink-0">
      <ul className="space-y-6">
        {VISIBLE_GROUPS.map((group) => (
          <li key={group.id}>
            <p className="mb-2 px-2 text-[11px] font-semibold uppercase tracking-[0.08em] text-fg-muted">
              {group.label}
            </p>
            <ul className="space-y-0.5">
              {group.items.map((item) => (
                <li key={item.to}>
                  <NavLink
                    to={item.to}
                    className={({ isActive }) =>
                      cn(
                        "flex items-center rounded-md px-2 py-1.5 text-sm transition-colors",
                        isActive
                          ? "bg-accent font-medium text-foreground"
                          : "text-fg-secondary hover:bg-accent/60 hover:text-foreground"
                      )
                    }
                  >
                    {item.label}
                    {item.to === "/settings/system" && quietCount > 0 && (
                      <span className="ml-auto flex h-5 min-w-[1.25rem] items-center justify-center rounded-full bg-brand/10 px-1.5 text-[11px] font-medium text-brand">
                        {quietCount}
                      </span>
                    )}
                  </NavLink>
                </li>
              ))}
            </ul>
          </li>
        ))}
      </ul>
    </nav>
  );
}

export function SettingsLayout() {
  return (
    <div className="space-y-6">
      <PageHeader title="Settings" subtitle="Preferences and account controls." />

      <MobileSettingsNav />

      <div className="flex flex-col gap-8 md:flex-row md:gap-10">
        <DesktopSettingsRail />

        <div className="min-w-0 flex-1">
          <Outlet />
        </div>
      </div>
    </div>
  );
}
