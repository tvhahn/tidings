import shotBudgetsDark from "../assets/screenshot-budgets-dark.webp";
import shotBudgets from "../assets/screenshot-budgets.webp";
import shotInsightsDark from "../assets/screenshot-insights-dark.webp";
import shotInsights from "../assets/screenshot-insights.webp";
import shotJournalDark from "../assets/screenshot-journal-dark.webp";
import shotJournal from "../assets/screenshot-journal.webp";
import { BrowserShot } from "../BrowserShot";
import { Icon } from "../Icon";

export function Features() {
  return (
    <section id="features" className="features">
      <div className="wrap">
        <div className="feat">
          <div>
            <div className="section-eyebrow">The daily journal</div>
            <h2 className="feat-title">A ledger that reads like a diary.</h2>
            <p className="feat-body">
              Transactions grouped by day. Amounts right-aligned in tabular numerals. Quiet
              annotations when a category nears its monthly budget, when a merchant repeats, or when
              a day runs past its usual pace. No alarms. No red panels. Just clarity.
            </p>
            <ul className="feat-list">
              <li>
                <Icon name="check" /> Daily grouping with on-pace, under, over states
              </li>
              <li>
                <Icon name="check" /> Category pills that stay soft and quiet
              </li>
              <li>
                <Icon name="check" /> Repeat-merchant counts and budget-pace annotations
              </li>
            </ul>
            <a className="feat-link" href="/demo/">
              Explore the demo →
            </a>
          </div>
          <BrowserShot
            src={shotJournal}
            srcDark={shotJournalDark}
            alt="The Tidings journal — a month of transactions grouped by day, with category pills and a budget summary"
            label="tidings.local · journal"
            width={1440}
            height={900}
          />
        </div>

        <div className="feat flip">
          <div>
            <div className="section-eyebrow">Category budgets</div>
            <h2 className="feat-title">Soft targets, never hard limits.</h2>
            <p className="feat-body">
              Set an annual target per category and watch the pace, not the panic. Under pace, a
              category stays quiet. Past it, the row warms to rust. It will never shout.
            </p>
            <ul className="feat-list">
              <li>
                <Icon name="check" /> Annual targets, broken into a monthly pace
              </li>
              <li>
                <Icon name="check" /> Suggested targets, drawn from your last twelve months
              </li>
              <li>
                <Icon name="check" /> A month-end projection from your typical spending
              </li>
            </ul>
            <a className="feat-link" href="/demo/budgets">
              See budgets in the demo →
            </a>
          </div>
          <BrowserShot
            src={shotBudgets}
            srcDark={shotBudgetsDark}
            alt="Category budgets — a ledger of per-category pace, YTD spent, monthly and annual budget, and variance, with over-pace rows warmed to rust"
            label="tidings.local · budgets"
            width={1440}
            height={900}
          />
        </div>

        <div className="feat">
          <div>
            <div className="section-eyebrow">Monthly insights</div>
            <h2 className="feat-title">Patterns, not prescriptions.</h2>
            <p className="feat-body">
              A briefing reads your spending in prose: month-over-month context, the categories that
              moved, the anomalies. It never tells you what to do.
            </p>
            <ul className="feat-list">
              <li>
                <Icon name="check" /> A monthly narrative briefing, generated on demand
              </li>
              <li>
                <Icon name="check" /> Month-over-month context across categories
              </li>
              <li>
                <Icon name="check" /> Plain prose, not toasts or red dots
              </li>
            </ul>
            <a className="feat-link" href="/demo/insights">
              Read a sample briefing →
            </a>
          </div>
          <BrowserShot
            src={shotInsights}
            srcDark={shotInsightsDark}
            alt="Insights — a monthly briefing in prose, with the categories that moved and notable changes"
            label="tidings.local · insights"
            width={1440}
            height={900}
          />
        </div>
      </div>
    </section>
  );
}
