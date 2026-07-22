import { Fragment } from "react";
import { Icon } from "../Icon";

const REPO_URL = "https://github.com/tvhahn/tidings";

const points = [
  {
    icon: "lock",
    t: "No aggregators",
    b: "Tidings never sees a credential. It only reads the transaction emails you forward.",
  },
  {
    icon: "server",
    t: "Your infrastructure",
    b: "Docker on your laptop, an IMAP poller on a Raspberry Pi, or a Lambda chain in your own AWS account. The data path is yours either way.",
  },
  {
    icon: "sparkles",
    t: "Optional AI",
    b: "Categorization and briefings can use OpenAI or Claude — with no keys configured, nothing ever leaves for a model. Whatever a model extracts is checked word-for-word against the original email.",
  },
  {
    icon: "code-2",
    t: "Open & auditable",
    b: "Every line of code is in the open repo. Fork it, audit it, trust it.",
  },
];

const pathNodes: Array<{ n?: string; title: string; sub: string; mono?: boolean }> = [
  { title: "Your bank", sub: "Transaction alert emails" },
  { n: "1", title: "Email forwarder", sub: "yourname.finance@gmail.com", mono: true },
  { n: "2", title: "Ingestion", sub: "IMAP poller, default · or Lambda in your own AWS" },
  { n: "3", title: "Parser", sub: "Merchant, amount, date" },
  { n: "4", title: "Tidings journal", sub: "Days, budgets, notices" },
];

export function PrivacyBand() {
  return (
    <section id="privacy">
      <div className="wrap arch">
        <div>
          <div className="section-eyebrow">Private by construction</div>
          <h2 className="section-title">Nothing to send. Nothing to&nbsp;leak.</h2>
          <p className="section-sub">
            No promise to protect your data. A design where nobody else holds it.
          </p>
          <div className="arch-points">
            {points.map((p) => (
              <div key={p.t} className="arch-point">
                <span className="arch-point-icon">
                  <Icon name={p.icon} size={15} />
                </span>
                <div>
                  <div className="arch-point-t">{p.t}</div>
                  <div className="arch-point-b">{p.b}</div>
                </div>
              </div>
            ))}
          </div>
          <a className="btn btn-outline" href={`${REPO_URL}/blob/main/docs/ARCHITECTURE.md`}>
            <Icon name="book-open" size={14} /> <span>Read the architecture</span>
          </a>
        </div>
        <div className="arch-card">
          <h3 className="arch-card-title">Your data. Your path.</h3>
          <div className="arch-path">
            {pathNodes.map((node, i) => (
              <Fragment key={node.title}>
                {i > 0 && <span className="arch-dash" />}
                <div className="arch-node">
                  {node.n ? (
                    <span className="arch-node-num">{node.n}</span>
                  ) : (
                    <span className="arch-node-icon">
                      <Icon name="landmark" size={15} />
                    </span>
                  )}
                  <div>
                    <div className="arch-node-t">{node.title}</div>
                    <div className={node.mono ? "arch-node-b arch-node-mono" : "arch-node-b"}>
                      {node.sub}
                    </div>
                  </div>
                </div>
              </Fragment>
            ))}
          </div>
          <p className="arch-caption">
            <Icon name="lock" size={13} />
            Every hop runs on hardware you control.
          </p>
        </div>
      </div>
    </section>
  );
}
