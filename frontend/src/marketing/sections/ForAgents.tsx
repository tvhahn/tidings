import { Icon } from "../Icon";

const AGENT_GUIDE_URL = "https://github.com/tvhahn/tidings/blob/main/docs/guides/agent-access.md";

/** The two read curls from the hosted demo API — mirror docs/guides/agent-access.md. */
const SUMMARY_CURL = "curl 'https://gettidings.com/demo/api/v1/summary?month=2026-03'";
const OPENAPI_CURL = "curl 'https://gettidings.com/demo/api/openapi.json'";

/** The real live response of the summary endpoint, truncated — values verbatim. */
const SUMMARY_JSON = `{
  "current": {
    "year_month": "2026-03",
    "total_spending": 4923.98,
    "spending_count": 54,
    "deposit_total": 5221.44,
    "by_category": {
      "rent": { "amount": 2150, "count": 1 },
      "internet": { "amount": 80, "count": 1 },`;

export function ForAgents() {
  return (
    <section id="agents">
      <div className="wrap">
        <div className="gs flip">
          <div>
            <div className="section-eyebrow">For agents</div>
            <h2 className="section-title">Agents can try it before you install.</h2>
            <p className="section-sub">
              Every Tidings surface is a versioned JSON API. The demo journal is served read-only at
              a public endpoint, so an agent can explore eleven months of a fictional household
              before you commit to anything.
            </p>
            <div className="gs-meta">
              <span>
                <Icon name="check" /> Same routes as self-hosted
              </span>
              <span>
                <Icon name="check" /> OpenAPI schema included
              </span>
              <span>
                <Icon name="check" /> No signup, no token
              </span>
            </div>
            <a className="feat-link" href={AGENT_GUIDE_URL}>
              Read the agent access guide →
            </a>
          </div>
          <div className="gs-card">
            <h3 className="gs-card-title">Two requests, no key</h3>
            <pre className="gs-term">
              <code>
                <span className="gs-term-prompt">{"$ "}</span>
                <span className="gs-term-cmd">{SUMMARY_CURL}</span>
                {"\n"}
                <span className="gs-term-out">{SUMMARY_JSON}</span>
                {"\n"}
                <span className="gs-term-ellipsis">{"      … 18 more categories"}</span>
                {"\n"}
                <span className="gs-term-prompt">{"$ "}</span>
                <span className="gs-term-cmd">{OPENAPI_CURL}</span>
              </code>
            </pre>
            <p className="gs-term-note">
              Real output, fictional household. Self-hosted installs get the same routes with
              bearer-token auth.
            </p>
          </div>
        </div>
      </div>
    </section>
  );
}
