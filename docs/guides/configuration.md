# Configuration reference — `data/config.json`

Every runtime setting lives in one file: `data/config.json`. The app creates
it on first boot with auto-detected defaults and rewrites it whenever you
change a setting in the dashboard (Settings) or via the API (`PUT
/api/v1/config`). You can also edit it by hand while the app is stopped.

The schema is defined by `AppConfig` in
[`src/finance/app_config.py`](../../src/finance/app_config.py) — if this table
and the code ever disagree, the code wins (and a docs fix is welcome).

Release stability: pre-1.0, keys may be renamed or removed between minor
versions. [`releases.md`](releases.md) asks every release to call out config
changes in the changelog.

## Keys

| Key | Type | Default | What it does |
|-----|------|---------|--------------|
| `storage` | `"sqlite"` \| `"dynamodb"` | `"sqlite"` | Storage backend. SQLite uses `data/finance.db`. DynamoDB is an explicit opt-in for the AWS path and is never auto-selected — set it here if you run the Lambda stack. Region comes from the `AWS_REGION` env var (falls back to `us-west-2`). |
| `demo_mode` | bool | `true` on first run | Serves the seeded demo database (`data/demo.db`) instead of your real data, and blocks uploads/imports. The dashboard shows a demo banner. Flip to `false` when you wire up real email ingestion. |
| `user_id` | string | `"default"` | Partition owner for budget/override records. Single-user app — leave it alone unless you know why you're changing it. |
| `timezone` | IANA zone name | `"America/Los_Angeles"` | Drives day/month bucketing, "latest transaction" age math, and the daily-summary schedule. Set it to your zone (e.g. `"Europe/Berlin"`); invalid names fall back to Pacific with a logged warning. |
| `ai_categorization_enabled` | bool | auto: `true` iff `OPENAI_API_KEY` is set | Master switch for AI transaction categorization. Off, every new transaction lands as miscellaneous for manual categorization. |
| `ai_extraction_enabled` | bool | auto: `true` iff `OPENAI_API_KEY` is set | Consent to rescue unreadable emails with AI: when no parser can read an email, its full body is sent to the configured AI provider for a validated extraction. Distinct from `ai_categorization_enabled` — either can be on without the other. Off, unreadable emails are captured to Needs review without any AI call (no email body reaches the AI, not even the relevance classifier). Absent from an existing config, it preserves the prior consent: it inherits a persisted `ai_categorization_enabled` (which gated extraction before the two were split), falling back to the key check only when neither AI key was ever persisted. |
| `ai_statement_parsing_enabled` | bool | `false` | Consent to parse statement PDFs with AI: when no built-in bank parser can read an uploaded statement, its extracted text is sent to the provider in `document_parsing_provider` and the reply is validated — every amount must appear verbatim in the PDF text — before anything is saved. Never auto-enables (a statement is the most sensitive document the app touches), so it is always an explicit opt-in from Settings → Intelligence. |
| `ai_receipt_parsing_enabled` | bool | `false` | Consent to parse receipt attachments with AI: sends a receipt photo or PDF to the provider in `document_parsing_provider`, only when you ask (the parse action in the attach dialog). The reply is validated fail-closed and amounts are checked against your transactions before anything is linked. Never auto-enables — always an explicit opt-in from Settings → Intelligence. |
| `s3_backup_enabled` | bool | `false` | Master switch for mirroring receipt/document attachments (`data/raw/attachments/`) and statement PDFs (`data/raw/statements/`) to a user-owned S3 bucket. Sync runs only when this is on, `s3_backup_bucket` is set, and AWS credentials resolve from the standard boto3 chain. Never auto-enables — always an explicit opt-in from Settings → Backup. See [`s3-backup.md`](s3-backup.md). |
| `s3_backup_bucket` | string \| null | `null` | The user-owned bucket the S3 backup mirrors to. `null` means no bucket configured (sync stays idle). The bucket is reached in the region from `AWS_REGION`/`AWS_DEFAULT_REGION` (falls back to `us-west-2`). Set and cleared from Settings → Backup. |
| `s3_backup_prefix` | string \| null | `null` | Optional key prefix inside `s3_backup_bucket`. `null` (or empty) writes to the bucket root; a value like `"tidings"` nests the backup under `tidings/attachments/…`, `tidings/statements/…`, and `tidings/manifest.json`. The backup only ever touches keys under those three names. |
| `tax_tracking_enabled` | bool | `true` | Whether tax receipt tracking is active. When on, the Tax receipts workspace tab, its `/tax` route, and the per-row "Flag as tax item" control on the Transactions and Journal pages are all available. Turning it off (Settings → Features) hides all three; existing tax flags are preserved and reappear if re-enabled. Defaults on so upgrading users keep their tax flags. |
| `daily_summary_provider` | `"openai"` \| `"claude_cli"` \| `"codex"` \| `"gemini_cli"` \| `"disabled"` | `"disabled"` | Which AI provider writes journal daily summaries. The CLI providers shell out to a locally installed, authenticated CLI; `openai` uses the API key. |
| `insights_provider` | same enum | `"disabled"` | Which AI provider writes monthly insights briefings. |
| `categorization_provider` | `"openai"` \| `"codex"` \| `"disabled"` | auto: `"openai"` iff `OPENAI_API_KEY` is set | Which provider runs AI categorization and email rescue (still gated by the two consents above). Codex is never auto-selected — it needs an explicit pick plus a ChatGPT login. |
| `document_parsing_provider` | same enum as `daily_summary_provider` | `"disabled"` | Which provider parses statement PDFs and receipt attachments (still gated by the two parsing consents above). |
| `daily_summary_model`, `insights_model`, `categorization_model`, `document_parsing_model` | string \| null | `null` | Per-feature model override. `null` means the provider's default: `gpt-5.4-nano` on the `openai` path, the CLI's own default otherwise (`sonnet` for Claude Code). Any model your provider serves is accepted — e.g. `gpt-5.6-sol` / `gpt-5.6-terra` / `gpt-5.6-luna`. |
| `daily_summary_reasoning_effort`, `insights_reasoning_effort`, `categorization_reasoning_effort`, `document_parsing_reasoning_effort` | `"none"` \| `"minimal"` \| `"low"` \| `"medium"` \| `"high"` \| `"xhigh"` \| `"max"` \| null | `null` | Per-feature reasoning-effort override; `null` uses the provider default (no flag sent). Support varies by provider (OpenAI API none–xhigh, Codex low–xhigh, Claude Code low–max); an unsupported combination surfaces as a provider error. Gemini ignores model and effort overrides. |
| `insights_user_memo` | string \| null (≤ 2000 chars) | `null` | Standing free-text context injected into every AI briefing — household facts, known annual bills, savings goals, anything the briefing should already know. Edit it in Settings → Intelligence. `null` (or empty) means no memo. Values over 2000 characters are rejected with a 422. |
| `enable_daily_summaries` | bool | `true` | Whether the in-process scheduler generates journal daily summaries at all (only takes effect when `daily_summary_provider` is not `"disabled"`). |
| `daily_summary_schedule_time` | `"HH:MM"` (24h) | `"19:00"` | When the daily summary runs, evaluated in `timezone`. Invalid values fall back to the default with a logged warning. |
| `agent_tokens` | list | `[]` | Bearer-token records for agent/API access — sha256 hashes only, never raw tokens. Manage via `make agent-token` / `make agent-token-show` / `make agent-token-revoke`; don't hand-edit. See [`agent-access.md`](agent-access.md). |
| `app_password_hash` | string \| null | absent | Argon2id hash of the dashboard password. Absent means TOFU mode: the API allows unauthenticated access and the dashboard nags you to set a password. Set it from Settings → Password. To reset a forgotten password, stop the app and remove this key from `data/config.json` — the dashboard returns to TOFU mode. |
| `session_version` | int | `0` | Bumped by "sign out everywhere" — invalidates every existing session cookie without rotating the secret. |
| `session_signing_secret` | 64-char hex | auto-generated on first use | HMAC key for session cookies. Treat it like a password; rotate only if it leaks (rotation signs everyone out). |
| `auth_bypass_for_dev` | bool | `false` | Dev-only escape hatch: skips cookie auth on `/api/v1/*` even when a password is set (bearer enforcement still applies). Never enable on an instance that binds beyond localhost — anyone on the network gets full read/write access. |

## What does *not* live here

- **Secrets and infrastructure env vars** — `OPENAI_API_KEY`, `IMAP_*`,
  notification provider settings (`NOTIFICATION_URL`, `NOTIFICATION_PROVIDER`,
  `TWILIO_*`, `SNS_TOPIC_ARN`),
  `AWS_REGION`, `SERVE_FRONTEND`, `CORS_ALLOWED_ORIGINS` — come from the
  environment / `.env`. [`.env.example`](../../.env.example) is the complete,
  commented list.
- **Budgets, category overrides, merchant aliases** — stored in the database,
  managed in the dashboard.
- **User mappings** (`ForwardedTo` → `UserId`) — live in
  `data/config/user_mappings.csv`. They load once into an in-memory cache with
  no TTL (unlike the 5-minute config caches), so edits to the CSV only take
  effect after a server restart.

## First-run behavior

When `data/config.json` is absent, the app writes one with `storage:
"sqlite"` and `demo_mode: true` — even when AWS credentials are present on
the machine. `ai_categorization_enabled`, `ai_extraction_enabled`, and
`categorization_provider` all auto-detect from `OPENAI_API_KEY`. After that
first write, the file is authoritative: auto-detection never overrides a
persisted value.

## Upgrading from the single-provider key

Configs written before per-feature routing carry one `summary_provider` key.
On the first boot after upgrading it is migrated automatically: daily
summaries, insights, and document parsing inherit its value;
`categorization_provider` becomes `"codex"` when the legacy value was codex,
otherwise the API-key auto-detect above. The legacy key is then removed from
the file. Keys already present are never overwritten by the migration.
