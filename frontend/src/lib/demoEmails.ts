import type { Transaction } from "@/types/api";
import { formatCurrency, MONTH_LONG } from "./format";

/**
 * Synthetic source emails for the static demo (spec 2026-06-11, D6).
 *
 * Every template is derived deterministically from the transaction row, keyed
 * on institution × transaction type, so the emails survive any future data
 * regeneration and work for fixture, overlay-edited, and manually added rows.
 * Skeletons follow the structures attested in
 * docs/specs/_archive/2026-06-11-demo-realism-improvements/email-template-research.md;
 * names, card numbers, and reference numbers are persona constants — nothing
 * is copied from the parser test fixtures.
 *
 * Fidelity caveats (see the research doc): real Tangerine alerts are vaguer
 * than this, and Simplii sends no per-transaction purchase emails at all —
 * both templates are intentionally richer so the dialog shows the row's data.
 */

export interface DemoEmail {
  subject: string | null;
  body: string | null;
  from_name: string | null;
  from_email: string | null;
  to_name: string | null;
  to_email: string | null;
}

// Persona card constants — synthetic last-4 digits, one per institution in
// Mira's bank stack (persona.md). Not taken from any test fixture.
const CARD_LAST4: Record<string, string> = {
  RBC: "7126",
  CIBC: "3308",
  Simplii: "9054",
  Tangerine: "6611",
};

const BANK_DISPLAY: Record<string, string> = {
  RBC: "RBC Royal Bank",
  CIBC: "CIBC",
  Simplii: "Simplii Financial",
  Tangerine: "Tangerine",
};

/** "October 22, 2024" — the spelled-out style bank notifications use. */
function longDate(tx: Transaction): string {
  // Row date is "MM/DD/YYYY HH:MM TZ"; date_file_name starts "YYYY.MM.DD_".
  const fromDate = /^(\d{2})\/(\d{2})\/(\d{4})/.exec(tx.date ?? "");
  const fromFile = /^(\d{4})\.(\d{2})\.(\d{2})/.exec(tx.date_file_name);
  let y: number, m: number, d: number;
  if (fromDate) {
    m = Number(fromDate[1]);
    d = Number(fromDate[2]);
    y = Number(fromDate[3]);
  } else if (fromFile) {
    y = Number(fromFile[1]);
    m = Number(fromFile[2]);
    d = Number(fromFile[3]);
  } else {
    return "an unknown date";
  }
  return `${MONTH_LONG[m - 1] ?? "January"} ${d}, ${y}`;
}

/**
 * Deterministic Interac-style reference number (12 mixed-case alphanumerics)
 * derived from the row's date_file_name via FNV-1a, so the same row always
 * shows the same reference.
 */
function referenceNumber(seedText: string): string {
  const alphabet = "ABCDEFGHJKLMNPQRSTUVWXYZabcdefghjkmnpqrstuvwxyz123456789";
  let hash = 0x811c9dc5;
  const out: string[] = [];
  for (let round = 0; out.length < 12; round++) {
    const text = `${seedText}#${round}`;
    for (let i = 0; i < text.length; i++) {
      hash ^= text.charCodeAt(i);
      hash = Math.imul(hash, 0x01000193);
    }
    out.push(alphabet[(hash >>> 0) % alphabet.length] ?? "0");
  }
  return out.join("");
}

function firstName(tx: Transaction): string {
  return (tx.name ?? "Mira Lin Chen").split(" ")[0] ?? "Mira";
}

function fullNameUpper(tx: Transaction): string {
  return (tx.name ?? "Mira Lin Chen").toUpperCase();
}

interface RowFacts {
  merchant: string;
  amount: string;
  date: string;
  last4: string;
  bank: string;
}

function facts(tx: Transaction): RowFacts {
  const institution = tx.institution ?? "";
  return {
    merchant: tx.company ?? "an unrecognized merchant",
    amount: formatCurrency(tx.amount),
    date: longDate(tx),
    last4: CARD_LAST4[institution] ?? "0000",
    bank: BANK_DISPLAY[institution] ?? institution,
  };
}

// ---------------------------------------------------------------------------
// Footers (structure per email-template-research.md)
// ---------------------------------------------------------------------------

const RBC_FOOTER = `Privacy & Security | Legal

RBC Royal Bank | Royal Bank of Canada
RBC WaterPark Place, 88 Queens Quay West, 12th Floor, Toronto, ON, M5J 0B8, Canada
www.rbcroyalbank.com

(R)/TM Trademark(s) of Royal Bank of Canada. RBC and Royal Bank are registered trademarks of Royal Bank of Canada.

Please do not reply to this email, as it was sent from an unmonitored account.

You are receiving this email as part of your Alerts subscription that you have requested. To make changes to your subscription, simply log on to RBC Royal Bank Online Banking.`;

const CIBC_FOOTER = `Sincerely,
CIBC

CIBC is committed to protecting your privacy and personal information. We will not include your personal details in messages outside of Online or Mobile Banking because email is not a secure method of communication.

Do not respond to this email.`;

const SIMPLII_FOOTER = `Simplii Financial is a division of CIBC. We will never ask you to confirm personal or account details by email.

Please do not reply to this email.`;

const TANGERINE_FOOTER = `This Orange Alert was sent to you by Tangerine. To change which alerts you receive, log in to your account and go to Alert Settings.

Tangerine, 3389 Steeles Ave E, Toronto, ON, M2H 0A1`;

function interacFooter(onBehalfOf: string): string {
  return `Please do not reply to this email.

This email was sent to you by Interac Corp., the owner of the INTERAC e-Transfer® service, on behalf of ${onBehalfOf}.
Interac Corp.
P.O. Box 45, Toronto, Ontario M5J 2J1
www.interac.ca

® Trade-mark of Interac Corp. Used under license.`;
}

// ---------------------------------------------------------------------------
// Per-institution senders
// ---------------------------------------------------------------------------

const FROM: Record<string, { name: string; email: string }> = {
  RBC: { name: "RBC Royal Bank", email: "alerts@rbc.com" },
  CIBC: { name: "CIBC", email: "alerts@cibc.com" },
  Simplii: { name: "Simplii Financial", email: "alerts@simplii.com" },
  Tangerine: { name: "Tangerine", email: "donotreply@email.tangerine.ca" },
};

const INTERAC_FROM = { name: "Interac e-Transfer", email: "notify@payments.interac.ca" };

// ---------------------------------------------------------------------------
// Templates
// ---------------------------------------------------------------------------

function rbcPurchase(tx: Transaction, f: RowFacts): DemoEmail {
  return {
    subject: "A purchase was made on your RBC credit card",
    body: `Hello,

As requested, we're letting you know that a purchase of ${f.amount} was made on your RBC Royal Bank credit card account ************${f.last4} on ${f.date} towards ${f.merchant}.

If you don't recognize this transaction, please call us at 1-800-769-2512 (available 24/7) and we'll be happy to help.

Account:

************${f.last4}

Purchase Amount:

${f.amount}

Transaction Date:

${f.date}

Transaction Description:

${f.merchant}

Thank you!

${RBC_FOOTER}`,
    ...sender("RBC", tx),
  };
}

function rbcAccountActivity(
  tx: Transaction,
  f: RowFacts,
  kind: "deposit" | "withdrawal"
): DemoEmail {
  const verb = kind === "deposit" ? "credited to" : "debited from";
  const label = kind === "deposit" ? "Deposit Amount" : "Withdrawal Amount";
  return {
    subject: `A ${kind} was made on your RBC account`,
    body: `Hello,

A ${kind} of ${f.amount} was ${verb} your bank account. The full details of this transaction are below:

Account:

Personal Banking

${label}:

${f.amount}

Transaction Date:

${f.date}

Transaction Description:

${f.merchant}

Thank you!

${RBC_FOOTER}`,
    ...sender("RBC", tx),
  };
}

function cibcPreauth(tx: Transaction, f: RowFacts): DemoEmail {
  return {
    subject: "CIBC Alert: pre-authorized payment processed",
    body: `Dear ${firstName(tx)},

We wanted to let you know that your CIBC Advantage Debit Card ending in ${f.last4} has processed a preauthorized payment of ${f.amount} to ${f.merchant} on ${f.date}.

You can sign on to your CIBC Online or Mobile Banking to view more details about this transaction.

${CIBC_FOOTER}`,
    ...sender("CIBC", tx),
  };
}

function cibcPurchase(tx: Transaction, f: RowFacts): DemoEmail {
  return {
    subject: "CIBC Alert: debit card purchase",
    body: `Dear ${firstName(tx)},

We wanted to let you know that your CIBC Advantage Debit Card ending in ${f.last4} was used for a purchase of ${f.amount} at ${f.merchant} on ${f.date}.

You can sign on to your CIBC Online or Mobile Banking to view more details about this transaction.

${CIBC_FOOTER}`,
    ...sender("CIBC", tx),
  };
}

function cibcAccountActivity(
  tx: Transaction,
  f: RowFacts,
  kind: "deposit" | "withdrawal"
): DemoEmail {
  const line =
    kind === "deposit"
      ? `a deposit of ${f.amount} from ${f.merchant} was credited to your CIBC account ending in ${f.last4}`
      : `a withdrawal of ${f.amount} to ${f.merchant} was debited from your CIBC account ending in ${f.last4}`;
  return {
    subject:
      kind === "deposit"
        ? "CIBC Alert: deposit received"
        : "CIBC Alert: withdrawal from your account",
    body: `Dear ${firstName(tx)},

We wanted to let you know that ${line} on ${f.date}.

You can sign on to your CIBC Online or Mobile Banking to view more details about this transaction.

${CIBC_FOOTER}`,
    ...sender("CIBC", tx),
  };
}

function simpliiPurchase(tx: Transaction, f: RowFacts): DemoEmail {
  return {
    subject: "Simplii Financial: transaction alert",
    body: `Hi ${firstName(tx)},

This is a transaction alert for your Simplii Financial Cash Back Visa card ending in ${f.last4}.

A purchase of ${f.amount} was made at ${f.merchant} on ${f.date}.

If you don't recognize this transaction, sign on to online banking or call us at 1-888-723-8881.

${SIMPLII_FOOTER}`,
    ...sender("Simplii", tx),
  };
}

function tangerinePurchase(tx: Transaction, f: RowFacts): DemoEmail {
  return {
    subject: "Orange Alert: transaction approved",
    body: `Hi ${firstName(tx)},

A transaction was approved on your Tangerine Money-Back Credit Card ending in ${f.last4}.

Amount: ${f.amount}
Merchant: ${f.merchant}
Date: ${f.date}

If you don't recognize this transaction, give us a call at 1-888-826-4374.

${TANGERINE_FOOTER}`,
    ...sender("Tangerine", tx),
  };
}

function interacIncoming(tx: Transaction, f: RowFacts): DemoEmail {
  return {
    subject: `INTERAC e-Transfer: a money transfer from ${f.merchant} has been automatically deposited`,
    body: `Hi ${fullNameUpper(tx)},

${f.merchant} has sent you a money transfer for the amount of ${f.amount} (CAD) and the money has been automatically deposited into your bank account at ${f.bank}.

Reference Number: ${referenceNumber(tx.date_file_name)}

${interacFooter(f.merchant)}`,
    from_name: INTERAC_FROM.name,
    from_email: INTERAC_FROM.email,
    to_name: tx.name ?? "Mira Lin Chen",
    to_email: tx.forwarded_to,
  };
}

function interacOutgoing(tx: Transaction, f: RowFacts): DemoEmail {
  const message = tx.comment ? `Message: ${tx.comment}\n\n` : "";
  return {
    subject: `INTERAC e-Transfer: ${f.merchant} accepted your money transfer`,
    body: `Hi ${fullNameUpper(tx)},

The ${f.amount} (CAD) you sent to ${f.merchant} has been successfully deposited.

Details of the Transfer:

${message}Reference Number: ${referenceNumber(tx.date_file_name)}

${interacFooter(f.bank || "your financial institution")}`,
    from_name: INTERAC_FROM.name,
    from_email: INTERAC_FROM.email,
    to_name: tx.name ?? "Mira Lin Chen",
    to_email: tx.forwarded_to,
  };
}

/**
 * Manually added rows have no bank email behind them — in the real app the
 * preview would be empty. The demo shows an honest stand-in instead so the
 * dialog never dead-ends.
 */
function manualEntry(tx: Transaction, f: RowFacts): DemoEmail {
  return {
    subject: `Manual entry: ${f.merchant}`,
    body: `This transaction was added by hand, so there's no bank email behind it.

Amount: ${f.amount}
Merchant: ${f.merchant}
Date: ${f.date}

Rows that arrive by forwarded email open their original bank notification here.`,
    from_name: "Tidings demo",
    from_email: null,
    to_name: tx.name ?? "Mira Lin Chen",
    to_email: tx.forwarded_to,
  };
}

function sender(
  institution: string,
  tx: Transaction
): Pick<DemoEmail, "from_name" | "from_email" | "to_name" | "to_email"> {
  const from = FROM[institution];
  return {
    from_name: from?.name ?? null,
    from_email: from?.email ?? null,
    to_name: tx.name ?? "Mira Lin Chen",
    to_email: tx.forwarded_to,
  };
}

// ---------------------------------------------------------------------------
// Router
// ---------------------------------------------------------------------------

export function buildDemoEmail(tx: Transaction): DemoEmail {
  const f = facts(tx);
  const institution = tx.institution ?? "";
  const type = (tx.transaction_type ?? "").toLowerCase();

  if (type === "e-transfer") {
    // Income rows are transfers Mira received; everything else is one she sent.
    const isIncoming = (tx.category ?? "").toLowerCase() === "income";
    return isIncoming ? interacIncoming(tx, f) : interacOutgoing(tx, f);
  }

  switch (institution) {
    case "RBC":
      if (type === "deposit" || type === "withdrawal") {
        return rbcAccountActivity(tx, f, type);
      }
      return rbcPurchase(tx, f);
    case "CIBC":
      if (type === "preauth") return cibcPreauth(tx, f);
      if (type === "deposit" || type === "withdrawal") {
        return cibcAccountActivity(tx, f, type);
      }
      return cibcPurchase(tx, f);
    case "Simplii":
      return simpliiPurchase(tx, f);
    case "Tangerine":
      return tangerinePurchase(tx, f);
    default:
      return manualEntry(tx, f);
  }
}
