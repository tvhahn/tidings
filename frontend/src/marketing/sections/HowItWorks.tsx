import { Icon } from "../Icon";

const steps = [
  {
    n: "01",
    title: "Forward your alerts",
    body: "Your bank already emails you when you spend. Point those alerts at an inbox you keep, and you're done with this step forever.",
  },
  {
    n: "02",
    title: "Tidings reads them",
    body: "The merchant, the amount, the date — lifted from each alert and filed. Nothing about the email body crosses a boundary you didn't draw.",
  },
  {
    n: "03",
    title: "A journal emerges",
    body: "Days, budgets, notices. The same data your bank has, finally in a form you'd want to read.",
  },
];

const alerts = [
  { kind: "Transaction alert", bank: "RBC", merchant: "Loblaws Queen West", amount: "$84.17" },
  {
    kind: "Card purchase",
    bank: "CIBC",
    merchant: "Tim Hortons King & Strachan",
    amount: "$7.63",
  },
  { kind: "Deposit notice", bank: "Simplii", merchant: "Payroll deposit", amount: "$2,184.55" },
];

/** The two spending alerts above, landed as journal rows. */
const journalRows = [
  { merchant: "Loblaws Queen West", cat: "Groceries", amount: "$84.17" },
  { merchant: "Tim Hortons King & Strachan", cat: "Restaurant Dining", amount: "$7.63" },
];

export function HowItWorks() {
  return (
    <section id="how">
      <div className="wrap">
        <div className="section-eyebrow">How it works</div>
        <h2 className="section-title">Your bank already sends the data.</h2>
        <p className="section-sub">
          Three steps, then the journal writes itself. No account linking. No aggregator. The emails
          go where you say.
        </p>

        {/* Visual restatement of the steps below — hidden from the a11y tree. */}
        <div className="flow" aria-hidden="true">
          <div className="flow-emails">
            {alerts.map((a) => (
              <div key={a.kind} className="flow-email">
                <div className="flow-email-head">
                  <span>{a.kind}</span>
                  <span>{a.bank}</span>
                </div>
                <div className="flow-email-body">
                  <span className="flow-email-merchant">{a.merchant}</span>
                  <span className="flow-email-amt">{a.amount}</span>
                </div>
              </div>
            ))}
          </div>
          <svg className="flow-link flow-link-in" viewBox="0 0 100 100" preserveAspectRatio="none">
            <path d="M 0 16.7 C 58 16.7, 42 50, 100 50" />
            <path d="M 0 50 L 100 50" />
            <path d="M 0 83.3 C 58 83.3, 42 50, 100 50" />
          </svg>
          <div className="flow-down" />
          <div className="flow-mail">
            <span className="flow-mail-node">
              <Icon name="mail" size={22} />
            </span>
            <div className="flow-mail-label">
              Forward to
              <code>yourname.finance@gmail.com</code>
            </div>
          </div>
          <svg className="flow-link flow-link-out" viewBox="0 0 100 100" preserveAspectRatio="none">
            <path d="M 0 50 L 100 50" />
          </svg>
          <div className="flow-down" />
          <div className="flow-journal">
            <div className="flow-journal-head">
              <span>Tue, March 17</span>
              <span className="flow-journal-total">$91.80</span>
            </div>
            {journalRows.map((r) => (
              <div key={r.merchant} className="flow-journal-row">
                <span className="flow-journal-merchant">{r.merchant}</span>
                <span className="flow-journal-cat">{r.cat}</span>
                <span className="flow-journal-amt">{r.amount}</span>
              </div>
            ))}
          </div>
        </div>

        <div className="howit">
          {steps.map((s) => (
            <div key={s.n} className="howit-item">
              <div className="howit-num">{s.n}</div>
              <h3 className="howit-title">{s.title}</h3>
              <p className="howit-body">{s.body}</p>
            </div>
          ))}
        </div>

        <p className="howit-foot">
          <Icon name="lock" size={13} />
          Runs on your hardware. Nothing goes to a model unless you add a key.
        </p>
      </div>
    </section>
  );
}
