# Self-hosted email setup (Gmail IMAP)

This guide walks you through wiring up the self-hosted finance dashboard to a
Gmail inbox so the IMAP poller daemon can ingest bank alert emails and turn
them into transactions.

**For self-hosters with the project cloned and Docker installed.** No prior Gmail IMAP or email-forwarding experience required. By the end, your IMAP poller will fetch bank emails from a dedicated Gmail inbox, parse them, and display new transactions on the dashboard. Follow the steps in order — later steps assume earlier ones are complete.

**How it works at a glance.**

1. Your bank sends transaction alerts to your personal Gmail.
2. A Gmail filter on your personal account forwards those alerts to a
   dedicated finance-only Gmail account.
3. The `imap-poller` Docker service logs into that dedicated account over
   IMAP, fetches new bank emails, and runs them through the same parser
   pipeline as the AWS Lambda stack.
4. Parsed transactions land in `data/finance.db` and show up on the
   dashboard.

The supported banks for direct purchase / transaction alerts are RBC, CIBC,
MBNA, Simplii, and PC Financial. Interac e-Transfer notifications are handled
separately — any Canadian bank that uses the standard `payments.interac.ca`
sender will be parsed.

---

## 0. Set your timezone (non-Pacific users)

The app defaults to `America/Los_Angeles`. Before you start ingesting
transactions, change it from the dashboard:
**Settings → Timezone**. The selector lists every IANA zone your
browser knows about, and the **Detect from browser** button picks your local
one in a click. The setting is instance-wide and controls how transactions
are bucketed into days and months, and how "latest transaction age" is
computed.

If you'd rather configure it before launching the dashboard, edit the
`timezone` key in `data/config.json` directly:

```json
{ "timezone": "Europe/Berlin" }
```

A note on switching mid-stream: the sort key is local-time and is written once at ingest, so changing `timezone` does not rewrite history. New transactions bucket in the new zone; older rows keep their original prefix. For most users this is invisible. For users who move continents, midnight-adjacent transactions ingested before the switch may group on the wrong calendar day in the Journal until they age out.

---

## 1. Create a dedicated Gmail account

Sign up for a new Gmail account that will be used **only** by the
dashboard — for example, `yourname.finance@gmail.com`.

Why a dedicated account, instead of pointing the poller at your main inbox?

- **Isolation.** The poller marks messages as `\Seen` and stores a
  last-seen UID cursor. Running it against your personal inbox would mutate
  state you care about and race with the way you read mail.
- **Blast radius.** If the App Password is ever leaked, you can burn the
  whole account and forwarding rule without touching your primary email.
- **Easier revocation.** To disconnect the dashboard later, delete the App
  Password — or the whole Gmail account — with no risk of clobbering
  unrelated settings on your main account.

Pick a strong, unique password and store it in a password manager. You will
also create an App Password later (step 3), which is what the poller
actually uses. Signed in as the dedicated account, move on to step 2.

## 2. Enable 2-Step Verification on the dedicated account

Google will not let you create App Passwords until 2-Step Verification
(2SV) is enabled on the account.

1. While signed in to the **dedicated** account, go to
   [myaccount.google.com/security](https://myaccount.google.com/security).
2. Under **How you sign in to Google**, click **2-Step Verification**.
3. Follow Google's walkthrough — detailed instructions live at
   [support.google.com/accounts/answer/185839](https://support.google.com/accounts/answer/185839)
   (the canonical "Turn on 2-Step Verification" article).
   Google's walkthrough now recommends Google prompts on a signed-in phone
   or a passkey as the primary method; SMS/voice codes and authenticator
   apps are still supported fallbacks.
4. Finish the setup until the page reports
   "2-Step Verification is **On**".

Double-check you are configuring 2SV on the *dedicated* finance account,
not your personal Gmail.

## 3. Generate a Gmail app password

The **App passwords** option only appears *after* 2-Step Verification has
been enabled. If you don't see it, go back and finish step 2.

1. Visit [myaccount.google.com/apppasswords](https://myaccount.google.com/apppasswords)
   (or navigate to **Google Account → Security → 2-Step Verification → App
   passwords**).
2. Re-enter your password if prompted.
3. In the **App name** field, enter something recognizable like
   `finance-dashboard-imap`. This is a label for your own reference; Google
   does not use it for anything other than display.
4. Click **Create**. Google will display a 16-character password (the UI
   shows it as four groups of four with spaces — the spaces are cosmetic
   and may be omitted when pasting).
5. **Copy it now and store it in your password manager.** Google will not
   show it again.

Notes:

- The poller strips spaces from the App Password automatically, so pasting
  it with or without spaces both work.
- This App Password is what goes into `IMAP_PASSWORD` in step 6 — *not*
  your regular Google account password.

## 4. Confirm IMAP is enabled

For **personal Gmail accounts**, IMAP is always on as of January 2025 —
Google removed the Enable IMAP / Disable IMAP toggle, and the option no
longer appears under **Forwarding and POP/IMAP**. You can skip this step
if you signed up at `gmail.com`. The poller will connect to
`imap.gmail.com:993` over SSL without any further configuration.

For **Google Workspace accounts** (custom domains administered through
admin.google.com), IMAP access is still controlled by an admin. If your
dedicated account is on a Workspace domain, an admin needs to enable POP
and IMAP under **Apps → Google Workspace → Gmail → End User Access**.
Reference (Workspace admin docs): [support.google.com/a/answer/105694](https://support.google.com/a/answer/105694).
For end-user Gmail forwarding setup (separate from IMAP), see
[support.google.com/mail/answer/10957](https://support.google.com/mail/answer/10957).

## 5. Forward bank alerts from your personal Gmail

Switch accounts: sign in to your **personal** Gmail (the one that actually
receives bank alerts today).

### 5a. Add the forwarding address

1. Gear icon → **See all settings** → **Forwarding and POP/IMAP**.
2. Click **Add a forwarding address** and enter your dedicated account
   (e.g. `yourname.finance@gmail.com`).
3. Google sends a confirmation email to the dedicated account. Sign in
   there, open the confirmation, and click the verification link.
4. Back on the personal account, refresh the settings page and confirm the
   dedicated address is listed as verified.

Do **not** change the default ("Forward a copy … and keep Gmail's copy in
the inbox") globally — you only want to forward bank alerts, not all
email. Use a filter for that, below.

### 5b. Create a filter that matches bank senders

1. In Gmail, click the filters icon in the search bar (or use **Settings
   → Filters and Blocked Addresses → Create a new filter**).
2. In the **From** field, paste one of the sender expressions below
   depending on which banks you use. To cover multiple banks with a
   single filter, join them with ` OR `.
3. Click **Create filter**.
4. Check **Forward it to** and choose your dedicated address.
5. Optionally also check **Skip the Inbox (Archive it)** and/or **Apply
   the label** → `Forwarded/Finance` so the clutter stays out of your
   personal inbox.
6. Click **Create filter** to save.

Sender patterns, matching the senders the pipeline parses — by
sender-domain match, or body-text detection for Interac-routed alerts
(`src/finance/email_pipeline.py`):

| Bank         | Suggested Gmail `From:` filter                                     |
| ------------ | ------------------------------------------------------------------ |
| RBC          | `from:(@alerts.rbc.com)`                                           |
| CIBC         | `from:(@cibc.com)`                                                 |
| MBNA         | `from:(@mbna.ca)`                                                  |
| PC Financial | `from:(@pcfinancial.ca)`                                           |
| Simplii (e-transfers only) | `from:(@payments.interac.ca)`                        |
| Interac      | `from:(catch@payments.interac.ca OR @payments.interac.ca)`         |

**Simplii note.** The Simplii parser only handles Interac e-Transfer notifications, which arrive from `payments.interac.ca` rather than `simplii.com`. Filter on the Interac sender domain for Simplii. (Direct purchase alerts on `@simplii.com` are not currently supported by the parser.)

One catch-all filter covering every supported institution looks like:

```
from:(@alerts.rbc.com OR @cibc.com OR @mbna.ca OR @pcfinancial.ca OR @simplii.com OR @payments.interac.ca)
```

Interac e-Transfer notifications from RBC, Simplii, or any other Canadian
bank all come from `payments.interac.ca` — keep that line even if you
don't think you receive them today.

`@simplii.com` is in the filter on purpose, even though those direct alerts
aren't parsed yet: forwarded copies land in the **Needs review** queue instead
of being dropped, AI extraction (if enabled) can recover the transactions,
and the captured emails are exactly the samples a future Simplii parser
needs.

If you see bank alerts in your inbox from a slightly different domain
(e.g. a regional RBC address), add it to the filter's `from:` list — the
pipeline matches on substrings of the domain, so anything ending in one
of the domains above is picked up automatically.

### 5c. Sanity check

After saving the filter, send yourself a small real transaction, or wait
for the next bank alert. Within a minute or two, the email should appear
in the dedicated account's inbox. If it lands in **Spam**, open it and
click **Not spam** so future alerts skip the spam folder.

## 6. Configure `.env`

`.env` is a local file at the repo root that stores configuration as environment variables. It's gitignored — never commit it. The Docker Compose stack reads it automatically when you run `docker compose up`.

At the repo root you'll find `.env.example`. Copy it to `.env` (if you
haven't already) and fill in the IMAP block. The variable names below are
the exact ones read by `src/finance/imap_poller.py::main()` and passed
through by `docker-compose.yml` — don't rename them.

```dotenv
# IMAP Polling (for self-hosted email ingestion)
IMAP_SERVER=imap.gmail.com                          # Gmail's IMAP host; rarely needs changing
IMAP_PORT=993                                       # IMAP-over-SSL; default is correct for Gmail
IMAP_USER=<your.finance@gmail.com>                  # the DEDICATED account from step 1
IMAP_PASSWORD=<YOUR_16_CHARACTER_APP_PASSWORD>      # the APP PASSWORD from step 3 (NOT your Google password)
IMAP_FOLDER=INBOX                                   # which mailbox to poll; INBOX is correct for the filter above
IMAP_POLL_INTERVAL=60                               # seconds between polls; 60 is a reasonable default
```

Optional but recommended:

```dotenv
OPENAI_API_KEY=<sk-...>                             # enables AI category suggestions; without it, categories default to "Miscellaneous"
```

Defaults baked in: if you omit `IMAP_SERVER`, `IMAP_PORT`, `IMAP_FOLDER`,
or `IMAP_POLL_INTERVAL`, the poller falls back to `imap.gmail.com`, `993`,
`INBOX`, and `60` respectively. `IMAP_USER` and `IMAP_PASSWORD` are
required — the process exits immediately if either is missing.

**Never commit `.env`.** It's already in `.gitignore`; keep it that way.

## 7. Start the stack

From the repo root:

```bash
docker compose up -d
```

This brings up two services defined in `docker-compose.yml`:

- `finance` — the FastAPI dashboard on port 8000
  (open [http://localhost:8000](http://localhost:8000))
- `imap-poller` — the long-lived IMAP polling daemon

Both containers share the `finance_data` volume, so the poller writes
transactions directly into the same SQLite DB the dashboard reads.

To stop the stack:

```bash
docker compose down
```

## 8. Verify it's working

Stream the poller logs:

```bash
docker compose logs -f imap-poller
```

(You can also use `docker logs -f <container_name>` directly, where the
container name is usually `<project>_imap-poller_1` or
`<project>-imap-poller-1` — `docker ps` shows the exact name.)

On a healthy startup you should see, in order:

```
Starting IMAP poller: server=imap.gmail.com, user=yourname.finance@gmail.com, folder=INBOX, interval=60s
Connected to imap.gmail.com:993 as yourname.finance@gmail.com
```

After that, one of two things happens on each poll cycle:

- **Idle tick** — nothing is logged until new mail arrives. That's
  normal; the daemon only emits a line per fetched message.
- **New mail** — you'll see `Fetching uid=<N>` followed by
  `uid=<N>: new transaction stored as …` and, once per batch,
  `Processed <N> message(s)`.

The first real transaction usually appears on the dashboard within one to
two poll intervals (so ~1–2 minutes on the default 60-second interval)
after the bank email actually arrives in the dedicated account. Refresh
the dashboard in your browser to see it.

If you want to force a fast end-to-end test, send yourself a small
e-Transfer from one of your supported banks — the alert should flow
through forwarding → dedicated inbox → poller → dashboard within a
couple of minutes.

---

## Troubleshooting

**"Invalid credentials" / authentication failure on connect.**
Gmail rejects your regular account password for IMAP — you *must* use an
App Password. Re-check that `IMAP_PASSWORD` is the 16-character value
from step 3 and not the password you log in to Google with. If in doubt,
generate a new App Password and paste it in fresh. Spaces in the App
Password are fine; the poller strips them.

**Server rejects LOGIN with an "IMAP disabled" message.**
On personal Gmail this is rare — IMAP is always on since January 2025.
The likely cause is a Google Workspace account where an admin has
disabled IMAP for the org. Ask your admin to enable IMAP under
**Apps → Google Workspace → Gmail → End User Access**, then restart the
poller: `docker compose restart imap-poller`.

**Not receiving emails / the dashboard stays empty.**
Three common causes, in order of likelihood:

1. The bank alert landed in **Spam** on the dedicated account. Open the
   message and click *Not spam* so future alerts go to `INBOX`.
2. Your Gmail forwarding filter on the personal account doesn't match
   the sender. Check step 5b and confirm each bank you use is in the
   `from:` list. Don't forget `payments.interac.ca` for e-Transfers.
3. The forwarding address was added but never verified. Go back to
   **Forwarding and POP/IMAP** on the personal account and make sure
   the dedicated address shows as verified, not pending.

**"Connection refused" or timeout errors in the poller log.**
Something between the container and Gmail is blocking port 993.
Confirm:

- `IMAP_SERVER=imap.gmail.com` and `IMAP_PORT=993` (no typos, no
  `imaps://`, no trailing spaces).
- Your host firewall or corporate network allows outbound TCP 993.
- If you run behind a VPN, try disabling it briefly to isolate the
  problem.

The poller automatically retries with exponential backoff (5s → 10s →
… up to 5 minutes), so transient network blips self-heal — persistent
errors every cycle indicate a config or firewall issue.

**App Password option missing, even though 2-Step Verification is on.**
Some Google Workspace administrators disable App Passwords
organization-wide via Admin Console → Security policy. This is common on
work or school accounts and can only be re-enabled by the admin. The
simplest workaround is a dedicated personal `@gmail.com` account
(step 1). App Passwords are available on personal Gmail accounts with
2SV enabled, except for accounts enrolled in Advanced Protection or
whose 2SV is set up with security keys only.

---

## AI categorization (optional)

The dashboard can use OpenAI to auto-assign a category to each new
transaction. AI categorization is enabled by default when
`OPENAI_API_KEY` is set; toggle in Settings → Intelligence to disable it.
Manual category overrides and merchant aliases run **before** OpenAI, so
local rules always win — OpenAI is only consulted when no override matches.

### What gets sent to OpenAI

When a built-in parser recognizes the bank, it extracts the fields locally and
OpenAI sees only two things, for the category lookup:

- the transaction amount (e.g. `42.50`)
- the merchant name as it appears in the bank email (e.g. `STARBUCKS #1234`)

That is the whole payload. Your account number, card number, balance, email
address, and every other transaction stay on your machine.

### When the full email is sent

If an email can't be read by a built-in parser — an unrecognized sender, or a
known bank that changed its format — and email rescue is on, Tidings falls
back to OpenAI to recover it. The email's **subject and body** are sent so the
model can decide whether the message is a transaction and pull out the amount,
merchant, and type. Whatever the bank put in that email goes with it.

Email rescue is its own consent (`ai_extraction_enabled`), separate from
categorization — turn it off under Settings → Intelligence and unparsed emails
are held for review with no AI call, whatever the categorization switch says.
Like categorization, it comes on when `OPENAI_API_KEY` is set. The surest way
to keep everything local is to run without an OpenAI key at all: the pipeline
then never calls out, unparsed emails are simply held for review, and
recognized transactions fall back to the `Miscellaneous` category.

### How to turn it off

- **UI**: Settings → Intelligence — the AI categorization and email rescue
  toggles (live; takes effect on the next new transaction)
- **Config file**: set `"ai_categorization_enabled": false` and
  `"ai_extraction_enabled": false` in `data/config.json`
- **No API key**: if you never set `OPENAI_API_KEY`, both flags default
  off and neither feature ever runs

When disabled, transactions receive the `Miscellaneous` category. You
can re-categorize them by hand in the transaction list, or add a
Category Rule under Categorize → Rules so future transactions from the
same merchant get the right category automatically — all without any
data leaving your machine.

---

## Next step

Your inbox is wired. The last step is notifications: [pick a provider](https://docs.gettidings.com/notifications/) so you get alerted when transactions arrive.
