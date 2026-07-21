import shotJournalDark from "../assets/screenshot-journal-dark.webp";
import shotJournal from "../assets/screenshot-journal.webp";
import { BrowserShot } from "../BrowserShot";
import { Icon } from "../Icon";

const REPO_URL = "https://github.com/tvhahn/tidings";

export function Hero() {
  return (
    <section className="hero">
      <div className="wrap hero-grid">
        <div className="hero-copy">
          <span className="eyebrow">
            <span className="dot" />
            Self-hosted · open source
          </span>
          <h1 className="h1">
            Your spending, <em>delivered.</em>
          </h1>
          <p className="lead">
            A private finance journal from the transaction emails you already receive. Forward them,
            and Tidings turns them into a calm daily record.
          </p>
          <div className="hero-ctas">
            <a className="btn btn-primary" href="/demo">
              <span>Try the demo</span>
              <Icon name="arrow-right" size={14} />
            </a>
            <a className="btn btn-outline" href={REPO_URL}>
              <Icon name="code-2" size={14} />
              <span>View on GitHub</span>
            </a>
            <span className="hero-ctas-note">Free · MIT licensed · runs on your hardware</span>
          </div>
          <div className="hero-meta">
            <span>
              <Icon name="mail" />
              Works with banks that email transaction alerts
            </span>
            <span>
              <Icon name="lock" />
              No bank credentials, no aggregator
            </span>
            <span>
              <Icon name="landmark" />
              Five banks parsed natively, AI rescues the rest
            </span>
          </div>
        </div>
        <div className="hero-visual">
          <BrowserShot
            className="hero-shot"
            src={shotJournal}
            srcDark={shotJournalDark}
            alt="The Tidings journal — a month of transactions grouped by day, with category pills and a budget summary"
            label="tidings.local · journal"
            width={1440}
            height={900}
            loading="eager"
          />
        </div>
      </div>
    </section>
  );
}
