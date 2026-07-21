# Notifications setup

The app sends push/SMS notifications for every new transaction in real time (and, on the AWS Lambda path, for the monthly summary job). Pick **one** provider and set its env vars in `.env`. The recommended default for self-hosters is [ntfy.sh](https://ntfy.sh) — free, no account needed, and works on iOS and Android.

If no provider is configured, the app falls back to a log-only mode and writes notifications to stdout — handy for local testing before wiring up a real provider.

## Provider comparison

| Provider | Cost | Best for |
|----------|------|----------|
| **Ntfy** (default) | Free | Self-hosters; everyone who doesn't specifically need SMS |
| **Twilio** | ~$5–10/mo | You want SMS delivery and don't use AWS |
| **AWS SNS** | ~$0.012/SMS US (base $0.0077 + carrier fee ~$0.0042) + 10DLC fees | You already deploy on AWS |
| Log-only | Free | Local testing; no provider configured |

---

## Ntfy (recommended)

Ntfy is a free push notification service. It's anonymous — no signup, no account. Messages are delivered to any device subscribed to your *topic*.

### Security: pick a hard-to-guess topic

Your topic name **is** the auth. Anyone who knows it can read your notifications, and anyone can publish to it. Do **not** use something guessable like `finance` or `my-transactions`. Use a random slug:

```text
finance-dashboard-x8k2m9p4
```

A shell one-liner to generate one:

```bash
echo "finance-dashboard-$(openssl rand -hex 6)"
```

### Steps

1. Install the ntfy mobile app ([iOS](https://apps.apple.com/us/app/ntfy/id1625396347) / [Android](https://play.google.com/store/apps/details?id=io.heckel.ntfy)) or use the [web app](https://ntfy.sh/app).
2. Subscribe to your chosen topic — e.g. `finance-dashboard-x8k2m9p4`.
3. Set the URL in `.env`:

   ```bash
   NOTIFICATION_URL=https://ntfy.sh/finance-dashboard-x8k2m9p4
   ```

4. Test-send from your terminal:

   ```bash
   curl -d "hello from ntfy" https://ntfy.sh/finance-dashboard-x8k2m9p4
   ```

   If the push arrives on your phone, the connection is working.

### Self-hosting

If you want full control (no reliance on ntfy.sh), you can run your own ntfy server in a container. Point `NOTIFICATION_URL` at your instance instead. See [docs.ntfy.sh/install](https://docs.ntfy.sh/install/).

---

## Twilio (SMS)

Twilio is a paid SMS provider. Pick this if you specifically want text messages rather than push notifications.

### Steps

1. Sign up at [twilio.com](https://www.twilio.com/), verify your phone, and buy a phone number (minimum ~$1.15/mo for a US local number).
2. From the Twilio console, grab:
   - **Account SID**
   - **Auth Token**
   - The **From** number you just purchased
3. Add to `.env` (exactly these env-var names — the service reads them directly):

   ```bash
   NOTIFICATION_PROVIDER=twilio
   TWILIO_ACCOUNT_SID=ACxxxxxxxxxxxxxxxxxxxxxxxxxxxxxxxx
   TWILIO_AUTH_TOKEN=your-auth-token
   TWILIO_FROM_NUMBER=+15551234567
   TWILIO_TO_NUMBER=+15557654321
   ```

   > **Note:** Twilio is **not** auto-detected from its env vars — you must set `NOTIFICATION_PROVIDER=twilio` explicitly. (Only `SNS_TOPIC_ARN` and `NOTIFICATION_URL` auto-detect.)

   > **Security note:** Auth Token works for self-hosting, but Twilio recommends [API Keys](https://www.twilio.com/docs/iam/api-keys) (or OAuth 2.0) for production — they can be scoped and revoked individually. The current Tidings notifier uses Auth Token; that's fine for personal self-hosting but rotate regularly.

4. Test-send:

   ```bash
   uv run python -c "from src.finance.notification_service import send_raw; send_raw('Test', 'hello from twilio')"
   ```

   You should get an SMS within a few seconds.

### 10DLC (US recipients)

US carriers require **10-digit long-code** registration for application-to-person (A2P) SMS. Twilio will prompt you through brand + campaign registration when you add the number. This takes a few business days for approval.

- **Canadian numbers sending only to Canadian numbers** may not need 10DLC. As of March 2025, Canadian carriers require Canadian A2P SMS registration for newly purchased numbers. Confirm current Twilio guidance for your region.
- **If you skip 10DLC for US traffic**, messages may silently fail to US recipients (no bounce, no error — they just don't arrive). See *Troubleshooting* below.

### Cost

Roughly $0.0083 per SMS segment plus US carrier surcharges (~$0.004) — about $0.012 per outbound segment in practice. For typical personal use, budget $5–10/month: the SMS volume itself is cents, but the US 10DLC campaign monthly fee (~$1.50–10/mo depending on campaign type) dominates the total.

---

## AWS SNS (advanced)

> **Most users should pick Ntfy.** Only use SNS if you're already deploying the Lambda email parser on AWS and want notifications to go through the same account.

### Steps

1. Create an SNS topic in your preferred AWS region (e.g. `us-west-2`).
2. Subscribe your phone number to it as an SMS subscription.
3. **For US numbers:** you'll hit 10DLC requirements, same as Twilio. Register a brand + campaign through the AWS End User Messaging SMS console — AWS now manages SMS origination IDs and 10DLC registration there rather than in the SNS console. See [Mobile text messaging with Amazon SNS](https://docs.aws.amazon.com/sns/latest/dg/sns-mobile-phone-number-as-subscriber.html) for the broader overview.
4. Set in `.env`:

   ```bash
   SNS_TOPIC_ARN=arn:aws:sns:us-west-2:YOUR_ACCOUNT_ID:your-topic-name
   AWS_REGION=us-west-2
   ```

   Setting `SNS_TOPIC_ARN` alone is enough — the provider auto-detects from it. `AWS_REGION` defaults to `us-west-2` if unset.

5. AWS CLI credentials must be available to the running process (or container). Use an IAM role if running on EC2/ECS/Lambda, or mount `~/.aws/credentials` into the container for local self-hosted use.

### Cost

Roughly $0.012 per SMS to US destinations (base $0.0077 + carrier fee ~$0.0042) plus 10DLC registration fees. Canadian SMS is slightly cheaper. No monthly number fee — pay per message.

---

## Log-only fallback

If none of `SNS_TOPIC_ARN`, `NOTIFICATION_URL`, or an explicit `NOTIFICATION_PROVIDER` are set, the app logs notifications to stdout:

```text
NOTIFY [Transaction]: Transaction | Company: TIM HORTONS | Amount: $4.85 | ...
```

Useful for verifying the parser and categorization pipeline before configuring a real provider. **Nothing is sent to your phone in this mode.**

---

## Provider auto-selection

The service picks a provider at startup in this order:

1. **`NOTIFICATION_PROVIDER`** — if set explicitly to `ntfy`, `twilio`, `sns`, or `log`, that wins.
2. **`SNS_TOPIC_ARN`** — if set, use SNS.
3. **`NOTIFICATION_URL`** — if set, use ntfy.
4. **Log-only.**

> **Twilio is only selected via the explicit `NOTIFICATION_PROVIDER=twilio` setting.** Its env vars (`TWILIO_ACCOUNT_SID`, etc.) are not auto-detected.

To force a specific provider regardless of what else is in the environment:

```bash
NOTIFICATION_PROVIDER=ntfy   # or twilio | sns | log
```

An unrecognized value logs a warning and falls back to log-only.

---

## Troubleshooting

**"I'm not getting notifications."**
The log-only fallback engages silently whenever required env vars are missing. Check your `.env`:

- Ntfy: is `NOTIFICATION_URL` set?
- SNS: is `SNS_TOPIC_ARN` set?
- Twilio: is `NOTIFICATION_PROVIDER=twilio` set (not just the `TWILIO_*` creds)?

Then tail the daemon log and look for a `NOTIFY [Transaction]: ...` line — if you see one, you're in log-only mode.

**"SNS 10DLC blocked."**
Register a brand and campaign in the AWS SNS console. Until approved, SMS to unregistered US numbers will be dropped.

**"Twilio error 30034."**
10DLC registration is incomplete or rejected — finish brand and campaign signup in the Twilio console. (Error 30032 is the related Toll-Free Verification error if you're using a toll-free number instead.)

**"Ntfy says it delivered but no push on my phone."**
Your phone's battery optimizer or notification settings are blocking delivery.

- Android: enable **Instant delivery** in the ntfy app settings (uses a foreground service for prompt delivery), then whitelist ntfy in Settings → Apps → ntfy → Battery → Unrestricted. Without instant delivery, FCM doze mode can delay pushes by minutes or hours.
- iOS: ensure notifications are enabled for the ntfy app under Settings → Notifications. APNs delivers regardless of Background App Refresh; if pushes still don't arrive, check Focus modes / Do Not Disturb.

**"Unknown NOTIFICATION_PROVIDER=... — falling back to log-only."**
Typo in `NOTIFICATION_PROVIDER`. Valid values: `ntfy`, `twilio`, `sns`, `log`.

---

## Next step

Provider configured? Return to [Docker setup](https://docs.gettidings.com/self-hosting/docker/) or [AWS deployment](https://docs.gettidings.com/self-hosting/aws/) to wire it in.
