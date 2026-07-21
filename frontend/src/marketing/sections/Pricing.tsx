import { Icon } from "../Icon";

const REPO_URL = "https://github.com/tvhahn/tidings";

/** The real quickstart from README.md — do not edit without updating both. */
const QUICKSTART = `git clone https://github.com/tvhahn/tidings.git
cd tidings
docker compose up -d`;

export function GetStarted() {
  return (
    <section id="open-source">
      <div className="wrap">
        <div className="gs">
          <div>
            <div className="section-eyebrow">Open source</div>
            <h2 className="section-title">Free, on your hardware.</h2>
            <p className="section-sub">
              The repo is the only distribution. No subscription, no commercial tier. The most
              useful contribution is a parser for a new bank's alerts or statements; the
              add-a-parser guide and its Claude Code skill build one from your own emails in a
              single session.
            </p>
            <div className="gs-ctas">
              <a className="btn btn-primary" href={REPO_URL}>
                <Icon name="code-2" size={14} />
                <span>View on GitHub</span>
              </a>
              <a className="btn btn-outline" href="/demo">
                <span>Try the demo</span>
                <Icon name="arrow-right" size={14} />
              </a>
            </div>
            <div className="gs-meta">
              <span>
                <Icon name="check" /> Local-first by default
              </span>
              <span>
                <Icon name="check" /> Five bank parsers
              </span>
              <span>
                <Icon name="check" /> MIT license
              </span>
            </div>
          </div>
          <div className="gs-card">
            <h3 className="gs-card-title">Three commands to a running journal</h3>
            <pre className="gs-term">
              <code>{QUICKSTART}</code>
            </pre>
            <p className="gs-term-note">
              Opens at <code>localhost:8000</code>. Demo mode by default, seeded with sample data.
            </p>
            <p className="gs-term-note">
              The default path is an IMAP poller in Docker. An optional S3 + Lambda chain runs in
              your own AWS account.
            </p>
            <a className="feat-link" href="https://docs.gettidings.com/self-hosting/docker/">
              Read the self-hosting guide →
            </a>
            <div className="gs-foot">
              <a className="gs-foot-repo" href={REPO_URL}>
                <Icon name="code-2" size={14} />
                github.com/tvhahn/tidings
              </a>
              <span className="gs-foot-fact">Python · TypeScript</span>
            </div>
          </div>
        </div>
      </div>
    </section>
  );
}
