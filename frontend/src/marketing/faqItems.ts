export interface FaqItem {
  q: string;
  a: string;
}

const ISSUES_URL = "https://github.com/tvhahn/tidings/issues";

export const FAQ_ITEMS: FaqItem[] = [
  {
    q: "Which banks work with Tidings?",
    a: "Any bank or card issuer that emails structured transaction alerts can be supported through a parser. Five Canadian institutions ship today: RBC, CIBC, MBNA, Simplii, and PC Financial. Alerts from any other bank are captured for review rather than dropped; the next answer covers what happens from there.",
  },
  {
    q: "What if my bank isn't supported?",
    a: `Alerts from an unrecognized bank land in the Needs review queue, where you can retry them, enter them by hand, or set them aside. Turn on "Rescue unreadable emails with AI" in Settings and most are recovered automatically: the email body goes to your configured AI provider, and the extracted transaction is checked word-for-word against the original before it's saved. Prefer a permanent fix? Open an issue at ${ISSUES_URL} with three or four sample alerts, personal details stripped. Not every institution will be tractable.`,
  },
  {
    q: "Does Tidings need my banking password?",
    a: "No. Tidings never touches your bank account. You forward transaction emails; the app parses them. That's the whole loop.",
  },
  {
    q: "Is there a mobile app?",
    a: "Not today. The web app is responsive and works well on a phone browser. The phone notification sent on each transaction (ntfy push by default; SMS via Twilio or SNS) is the closest thing to a mobile experience right now.",
  },
  {
    q: "Can I export my data?",
    a: "Yes: a backup zip with transactions.csv plus your category, override, and budget config as JSON. Your data is yours; nothing is held hostage by a subscription.",
  },
  {
    q: "How much does it cost to self-host?",
    a: "Nothing. The default IMAP poller path runs on a Raspberry Pi, a NAS, or any always-on machine. There is no cloud cost, and it is the path most users should pick. An AWS Lambda path is also available for users comfortable with cloud infrastructure; it runs in your own AWS account and the free tier covers most personal volumes (a few hundred transactions a month). Either way, no subscription.",
  },
  {
    q: "How is Tidings different from Firefly III or Actual Budget?",
    a: "Mostly by where the data comes from. Firefly III is a full double-entry finance manager; Actual Budget is a local-first envelope budgeting app. Both are built around bank sync, file imports, or entering transactions yourself. Tidings reads the alert emails your bank already sends — no bank credentials, no aggregator, no manual entry — and turns them into a daily journal. Pick those projects for accounting or strict budgeting; pick Tidings for a spending record that maintains itself.",
  },
];
