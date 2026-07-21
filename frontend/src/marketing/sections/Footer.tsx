import { Sun, Moon, Monitor } from "lucide-react";
import { useTheme } from "../../stores/theme";

const REPO_URL = "https://github.com/tvhahn/tidings";

const themeOptions = [
  { value: "light" as const, label: "Light", Icon: Sun },
  { value: "system" as const, label: "System", Icon: Monitor },
  { value: "dark" as const, label: "Dark", Icon: Moon },
];

function ThemePicker() {
  const mode = useTheme((s) => s.mode);
  const setMode = useTheme((s) => s.setMode);
  return (
    <div role="group" aria-label="Theme" className="foot-theme">
      {themeOptions.map(({ value, label, Icon }) => (
        <button
          key={value}
          type="button"
          onClick={() => setMode(value)}
          aria-pressed={mode === value}
          aria-label={label}
          className={mode === value ? "is-active" : ""}
        >
          <Icon size={13} aria-hidden="true" />
          <span>{label}</span>
        </button>
      ))}
    </div>
  );
}

export function Footer() {
  return (
    <footer>
      <div className="wrap">
        <div className="foot-grid">
          <div>
            <div className="nav-brand foot-brand">
              <img src="/favicon.svg" alt="" />
              <span>Tidings</span>
            </div>
            <p className="foot-about">
              A private finance journal from the transaction emails you already receive.
              Self-hosted, open source, calm by default.
            </p>
          </div>
          <div className="foot-col">
            <h4>Product</h4>
            <ul>
              <li>
                <a href="/demo/">Journal</a>
              </li>
              <li>
                <a href="/demo/budgets">Budgets</a>
              </li>
              <li>
                <a href="/demo/insights">Insights</a>
              </li>
              <li>
                <a href="/demo/transactions">Transactions</a>
              </li>
              <li>
                <a href={`${REPO_URL}/releases`}>Changelog</a>
              </li>
            </ul>
          </div>
          <div className="foot-col">
            <h4>Learn</h4>
            <ul>
              <li>
                <a href="https://docs.gettidings.com/">Docs</a>
              </li>
              <li>
                <a href={`${REPO_URL}/blob/main/docs/ARCHITECTURE.md`}>Architecture</a>
              </li>
              <li>
                <a href="https://docs.gettidings.com/self-hosting/docker/">Self-hosting guide</a>
              </li>
              <li>
                <a href={`${REPO_URL}#bank-support`}>Bank setup</a>
              </li>
              <li>
                <a href={`${REPO_URL}/blob/main/docs/guides/agent-access.md`}>Agent access</a>
              </li>
            </ul>
          </div>
          <div className="foot-col">
            <h4>Open</h4>
            <ul>
              <li>
                <a href={REPO_URL}>GitHub</a>
              </li>
              <li>
                <a href={`${REPO_URL}/blob/main/LICENSE`}>License</a>
              </li>
              <li>
                <a href={`${REPO_URL}/security`}>Security</a>
              </li>
              <li>
                <a href={`${REPO_URL}/issues`}>Contact</a>
              </li>
            </ul>
          </div>
          <div className="foot-signoff">
            <div className="foot-signoff-t">
              Your spending, <em>delivered.</em>
            </div>
            <div className="foot-signoff-b">No Plaid. No bank credentials. No manual entry.</div>
          </div>
        </div>
        <div className="foot-bottom">
          <span>© 2026 Tidings. An open-source project.</span>
          <span className="foot-bottom-meta">Built quietly</span>
          <ThemePicker />
        </div>
      </div>
    </footer>
  );
}
