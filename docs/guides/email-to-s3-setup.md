# Email-to-S3 setup (advanced)

Route bank alert emails into the S3 bucket the AWS Lambda watches, using SES, a verified domain, and a receipt rule.

:::note[Prerequisites]
SES inbound only works on a domain you control. You will need to add MX and DKIM records to its DNS — that means owning a domain at a registrar, not just an email address.

If you do not own a domain, the [Docker + IMAP path](https://docs.gettidings.com/self-hosting/docker/) does the same job without DNS. Most users start there.
:::

**For AWS users who own a registered domain and want bank alerts to arrive via email at that domain.** By the end, you'll have an S3 bucket receiving inbound emails from your bank, ready for the [Lambda parser](aws-deployment.md) to process.

The AWS path needs your bank alert emails to land in an S3 bucket before any of the parser scripts can run. The Lambda function is triggered by S3 object-created events, so if nothing is writing to the bucket, nothing parses. The IMAP path on Docker does not have this prerequisite — it polls Gmail (or any IMAP mailbox) directly and skips S3 entirely.

This page covers the AWS path specifically — the configuration steps between deploying the Lambda and transactions showing up in the dashboard. If you do not already use AWS, or want the shortest path to a working setup, the [Docker self-hosting guide](https://docs.gettidings.com/self-hosting/docker/) and the [Email setup guide](self-hosted-email-setup.md) cover the IMAP path end to end.

## The shape of the pipeline

Before stepping through the configuration, it helps to hold the full path in mind:

<!-- docs-site:figure:email-to-s3-path -->

```text
bank → Gmail (or direct) → forwarder → SES inbound → S3 → Lambda → DynamoDB → dashboard
```

The work on this page covers everything from **forwarder** through **S3**. The Lambda, DynamoDB table, and dashboard are deployed separately by the scripts in `docker/email_parsing/` and the rest of the repo. SES is the only piece that needs a verified domain and DNS records — everything to the right of S3 is plain AWS resources.

The reason this is more involved than IMAP polling is that SES inbound is a "real" mail server: it has to convince other mail servers (Gmail, your bank) that it owns a domain, has a published MX record, and accepts mail at known addresses. That is the cost of running on AWS infrastructure rather than logging into a mailbox you already own.

## What you need before you start

### Hard requirements

- **A registered domain you control DNS for.** Any registrar works — Route 53 is convenient if you already use AWS, but the rest of this guide assumes you can add MX and CNAME records wherever your domain currently lives.
- **An AWS account** where you can create S3 buckets, configure SES rule sets, and attach IAM policies. This is the same account you will deploy the Lambda into.

### Recommended choices

- **An SES inbound region.** SES inbound is region-restricted, but the supported list has grown over time — the AWS console shows the live list when you open the SES email-receiving page, and the canonical reference is the [Email Receiving endpoints table](https://docs.aws.amazon.com/general/latest/gr/ses.html#ses_inbound_endpoints) in the AWS General Reference. `us-east-1`, `us-west-2`, and `eu-west-1` are the long-standing safe defaults if you have no other constraint. Whichever region you pick, the S3 bucket and the Lambda function must live in the same region. Cross-region routing is not supported for SES inbound rules.

## 1. Create the S3 bucket

In the AWS S3 console, create a new bucket:

- **Name:** something distinctive, since bucket names are globally unique. `tidings-inbound-<your-initials>` works as a naming pattern.
- **Region:** the same region you picked for SES inbound.
- **Block public access:** keep all four block settings on. SES writes to the bucket via a service principal, not via public access.
- **Default encryption:** SSE-S3 is enough. SSE-KMS works too but adds an extra IAM grant on the SES side — skip it unless you have a policy reason to use KMS.
- **Versioning:** off, unless you want to keep historical copies of inbound mail. The parser is idempotent, so versioning mostly costs storage.

You do not need to pre-create any prefixes. SES will write objects directly to the bucket root (or to a prefix you specify in the receipt rule, see step 5).

## 2. Verify your domain in SES

Open the SES console in your chosen region and go to **Verified identities** → **Create identity** → **Domain**. AWS's [Easy DKIM walkthrough](https://docs.aws.amazon.com/ses/latest/dg/send-email-authentication-dkim-easy.html) covers the same steps with screenshots.

- Enter the apex domain you control (`yourdomain.com`), even if you plan to receive mail at a subdomain like `mail.yourdomain.com`.
- Turn on **Easy DKIM** with RSA 2048-bit keys. SES will give you three CNAME records to add to your DNS.

Add the three CNAME records SES provides at your DNS host. They look like:

```text
<token1>._domainkey.yourdomain.com   CNAME   <token1>.dkim.amazonses.com
<token2>._domainkey.yourdomain.com   CNAME   <token2>.dkim.amazonses.com
<token3>._domainkey.yourdomain.com   CNAME   <token3>.dkim.amazonses.com
```

(In a small number of newer regions — for example `eu-south-1`, `eu-central-2`, `me-central-1` — SES generates a region-specific target like `<token>.dkim.<region>.amazonses.com`. Use whatever values the SES console gives you.)

Verification usually completes in under 30 minutes. Most DNS hosts propagate within a few minutes, and SES re-checks on a short interval. The identity status moves from **Pending** to **Verified** when DKIM is confirmed.

### A note on SPF and DMARC

To receive mail, SES needs two things in your DNS: the domain **verified** (the DKIM CNAME records from step 2, which prove you own it) and an **MX record** (step 3). It does not need SPF or DMARC. Those records protect against spoofed mail being **sent from** your domain — an outbound concern, not an inbound one. Once the identity is verified, SES checks DKIM on incoming mail automatically, with no extra DNS work.

If you already publish SPF or DMARC at your apex domain because you also send mail from it, those records do not interfere with SES inbound. They live at the apex; the MX record for SES lives at the subdomain. Different scopes.

## 3. Add an MX record for SES inbound

Pick the address you want bank alerts to arrive at. The recommended pattern is a dedicated subdomain — `mail.yourdomain.com` or `inbound.yourdomain.com` — so SES inbound does not interfere with whatever already handles mail at the apex. AWS's reference for this step is [Publishing an MX record for Amazon SES email receiving](https://docs.aws.amazon.com/ses/latest/dg/receiving-email-mx-record.html).

Add an MX record at the chosen subdomain pointing to the SES inbound endpoint for your region:

```text
mail.yourdomain.com.   MX   10   inbound-smtp.us-east-1.amazonaws.com.
```

The endpoint hostname follows the pattern `inbound-smtp.<region>.amazonaws.com`. Common values:

| Region | Inbound endpoint |
|---|---|
| `us-east-1` | `inbound-smtp.us-east-1.amazonaws.com` |
| `us-west-2` | `inbound-smtp.us-west-2.amazonaws.com` |
| `eu-west-1` | `inbound-smtp.eu-west-1.amazonaws.com` |

Priority `10` is conventional — it does not matter what number you pick as long as no other MX record at the same name has a lower number. If you ever add a backup MX, give it a higher number.

DNS propagation for MX records is typically a few minutes, occasionally up to an hour. You can confirm with `dig MX mail.yourdomain.com` once it lands. The expected output:

```text
;; ANSWER SECTION:
mail.yourdomain.com.   300   IN   MX   10 inbound-smtp.us-east-1.amazonaws.com.
```

A note on subdomain choice: SES inbound only matches the recipient domain, not the apex. If you put the MX at `mail.yourdomain.com`, mail to `you@yourdomain.com` will not reach SES — it will go wherever the apex MX points (often nowhere). Pick a subdomain you do not already use for anything else.

## 4. Grant SES write access to the bucket

SES needs explicit permission to write to your bucket. The bucket policy below allows the `ses.amazonaws.com` service principal to `PutObject`, scoped to your AWS account *and* the specific receipt rule so only that rule's SES delivery can drop mail in. This mirrors the example AWS publishes in [Giving permissions to Amazon SES for email receiving](https://docs.aws.amazon.com/ses/latest/dg/receiving-email-permissions.html#receiving-email-permissions-s3).

You will fill in four values: `YOUR-BUCKET-NAME`, `YOUR-ACCOUNT-ID`, `YOUR-REGION` (the SES inbound region from step 2), and `YOUR-RULE-SET-NAME` / `YOUR-RULE-NAME` (the names you will create in step 5).

:::note
Steps 4 and 5 depend on each other. Either complete step 5 first to get the rule-set and rule names, or apply this bucket policy with placeholders now (which blocks SES until the names are filled in — the safer order).
:::

```json
{
  "Version": "2012-10-17",
  "Statement": [
    {
      "Sid": "AllowSESPuts",
      "Effect": "Allow",
      "Principal": {
        "Service": "ses.amazonaws.com"
      },
      "Action": "s3:PutObject",
      "Resource": "arn:aws:s3:::YOUR-BUCKET-NAME/*",
      "Condition": {
        "StringEquals": {
          "AWS:SourceAccount": "YOUR-ACCOUNT-ID",
          "AWS:SourceArn": "arn:aws:ses:YOUR-REGION:YOUR-ACCOUNT-ID:receipt-rule-set/YOUR-RULE-SET-NAME:receipt-rule/YOUR-RULE-NAME"
        }
      }
    }
  ]
}
```

Apply it under **S3 console → your bucket → Permissions → Bucket policy**. The `AWS:SourceAccount` and `AWS:SourceArn` conditions are the key piece — together they implement the "confused deputy" pattern AWS recommends for cross-service access, restricting writes to a specific receipt rule in your account. (Older AWS examples used `aws:Referer` for this; AWS has since moved every SES inbound walkthrough over to `SourceAccount` + `SourceArn`, which is more precise and the current recommendation.)

If you encrypted the bucket with KMS instead of SSE-S3, also grant `kms:GenerateDataKey` on the bucket's KMS key to the same service principal with the same condition keys. Most setups skip this by sticking with SSE-S3.

## 5. Create a receipt rule set

In the SES console, go to **Email Receiving** → **Create rule set**. Name it something clear like `tidings-inbound`. SES only honors **one active rule set at a time**, so if you already have one, you will be adding rules to the active set rather than activating a new one. AWS's [Creating receipt rules console walkthrough](https://docs.aws.amazon.com/ses/latest/dg/receiving-email-receipt-rules-console-walkthrough.html) covers this same flow with current screenshots.

Activate the rule set, then add a rule inside it:

- **Recipient condition:** the address you want to receive bank alerts at. `alerts@mail.yourdomain.com` is a reasonable choice. You can list multiple recipients on the same rule.
- **Action:** **Deliver to S3 bucket** (per AWS's current [Deliver to S3 bucket action](https://docs.aws.amazon.com/ses/latest/dg/receiving-email-action-s3.html)).
  - **S3 bucket:** the bucket from step 1.
  - **Object key prefix:** optional. Leaving it blank writes to the bucket root, which is what the Lambda script expects out of the box. If you set a prefix, update the Lambda S3 trigger filter accordingly.
  - **KMS key:** none, unless you set up KMS in step 4.
  - **SNS topic:** leave blank. The Lambda is wired to S3 object-created events directly, not to SNS.

Save the rule and confirm the rule set is **Active**. SES marks the active set with a green badge in the console.

A small gotcha: SES will not let you save a rule that writes to a bucket whose policy does not yet grant SES `PutObject`. If you skipped step 4 or got the policy wrong, the rule save fails with a permissions error rather than saving and then silently dropping mail. That is a feature — fix the bucket policy and try again.

## 6. Forward bank alerts to your SES address

You now have an SES address that drops mail in S3. The remaining piece is getting bank alert emails to that address.

- **Direct configuration.** Some banks let you change the alert destination address freely in their notifications settings. If yours does, point it straight at `alerts@mail.yourdomain.com` and skip Gmail entirely.
- **Gmail forwarding filter.** Most Canadian banks restrict the alert address to one already on file or refuse to send to addresses on unfamiliar domains. The workaround is a Gmail filter:
  1. In Gmail settings, add `alerts@mail.yourdomain.com` as a forwarding address. Gmail sends a verification message to the SES address. The message includes both a confirmation link and a numeric code; the link will not be clickable (SES is not a mail client), so retrieve the email from S3, copy the numeric code, and paste it back into Gmail.
  2. Create a filter that matches each bank's `From:` addresses (RBC `@alerts.rbc.com`, CIBC `@cibc.com`, MBNA `@mbna.ca`, PC Financial `@pcfinancial.ca`, Interac `@payments.interac.ca` — Simplii alerts arrive via the Interac sender domain, not `@simplii.com`) and applies the action **Forward to alerts@mail.yourdomain.com**. The [Email setup guide](self-hosted-email-setup.md) has the full sender reference if you need it.
  3. Optionally add **Skip the inbox** so Gmail keeps the original but does not clutter your view.

The Gmail filter approach is what most users end up with, since direct bank configuration is rarely permitted.

## 7. Confirm the loop works

End-to-end test, in order:

1. Send a test email from any mailbox to `alerts@mail.yourdomain.com`. Use a short plain-text body.
2. Open the S3 bucket in the console. Within a few seconds, an object with a long random key should appear. The body is the raw RFC 5322 message including headers.
3. Forward (or wait for) a real bank alert email to the same address. Confirm a second object lands.
4. Trigger the Lambda manually:

   ```bash
   cd docker/email_parsing/
   ./6_invoke_func.sh
   ```

   The script invokes the function with a synthetic S3 event. Check CloudWatch Logs for the function — you should see parser output and a DynamoDB write.
5. Open the dashboard. The transaction from your test bank email should be in the journal.

## If the loop does not work

If steps 2 and 3 work but step 4 produces nothing, the S3 event notification on the bucket is probably not wired to the Lambda. That wiring lives in `4_establish_lambda_func.sh` and is separate from the bucket policy in step 4 of this guide. To inspect it, open **S3 console → your bucket → Properties → Event notifications** and confirm there is one entry that triggers the Lambda on **All object create events**. If the entry is missing, re-run the deploy script — it is idempotent and will repair the wiring.

The Lambda execution role also needs `s3:GetObject` on the bucket so the function can read each message body when triggered. The deploy scripts attach this policy automatically. If you wrote your own deploy or modified the script, confirm the role has that permission, or every invocation will fail with `AccessDenied` in CloudWatch.

If the Lambda runs but the dashboard is empty, the parser ran but found no transaction. CloudWatch logs the bank it tried to match. Common cases:

- The bank is not in `src/finance/parsers/` yet. Five Canadian banks ship today (RBC, CIBC, MBNA, Simplii, PC Financial). Other institutions are added by contribution.
- The email is from the bank but is a marketing message, not a transaction alert. The parser logs `not a transaction email` and exits.
- The forwarder rewrote the `From:` header, so the parser sees Gmail's address rather than the bank's. The repo has logic to handle Gmail's `X-Forwarded-For` header, but custom forwarders may behave differently. Inspect the raw S3 object to see what headers actually arrived.

## What comes next

When this page is finished, you should be able to:

- Receive a test email at `alerts@mail.yourdomain.com` and see an object appear in the S3 bucket within a few seconds.
- See SES list the domain identity as **Verified** and the rule set as **Active**.
- Run `dig MX mail.yourdomain.com` from any machine and get back the SES inbound endpoint for your region.
- Forward (or wait for) a real bank alert and see a transaction land in the dashboard within the Lambda's typical invocation latency (a few seconds plus OpenAI categorization time).

Once these steps are complete, email-to-S3 is ready. The next step is to deploy the Lambda function that processes those emails. Continue to [AWS deployment](aws-deployment.md).

## Why this is more complex than IMAP

The AWS path scales to zero, runs on managed infrastructure, and costs pennies per month at typical email volumes — but the inbound path requires a domain you control, SES verification, an MX record, a bucket policy, and a receipt rule set. None of that is technically hard, but it is six moving parts that have to line up before any transaction reaches the parser.

The IMAP path on Docker needs a Gmail account and a forwarding filter. There is no domain, no DNS, no SES, no bucket policy. For most users, that is the right starting point — see the [Docker guide](https://docs.gettidings.com/self-hosting/docker/) and [Email setup](self-hosted-email-setup.md). Move to AWS once the parser is doing useful work and you want to stop running a host.

## Troubleshooting

- **SES verification stuck on Pending.** Re-check the three DKIM CNAME records at your DNS host. Most failures here are a copy-paste error in the token names or a DNS host that silently appended your apex domain to the record (some hosts double up, producing `<token>._domainkey.yourdomain.com.yourdomain.com`). Use `dig CNAME <token>._domainkey.yourdomain.com` to confirm what is actually published.
- **Test email never appears in S3.** Confirm the rule set is **Active**, not only created. Confirm the recipient condition exactly matches the address you sent to (case-insensitive on the local part, but typos count). Confirm the bucket policy is attached and the `AWS:SourceAccount` matches your account ID and the `AWS:SourceArn` matches your active rule set + rule name. SES will silently drop mail if the bucket write fails — most often because one of those two values has a typo or the rule has been renamed since the policy was applied.
- **MX lookup fails.** Run `dig MX mail.yourdomain.com` from a machine outside your DNS host's caching layer. If it returns nothing, the record was not saved or has not propagated. If it returns the wrong endpoint, you typed the region wrong.
- **Object lands in S3 but Lambda does not run.** The S3 → Lambda event notification is a separate piece of glue, configured by `4_establish_lambda_func.sh`. Re-run that script, or open **S3 console → bucket → Properties → Event notifications** and confirm the function is wired to **All object create events**.
- **Lambda runs but no transaction shows up.** The function ran but did not parse the email. Check CloudWatch Logs for the function; the parser logs the `From:` address it tried to match. If the bank is not in `src/finance/parsers/`, the email is dropped on purpose — parsers are added by contribution.
- **Mail bounces back at Gmail with "address not found."** The MX record either has not propagated, points to the wrong region's endpoint, or sits at the apex when SES is configured for a subdomain. Run `dig MX <the-exact-domain-you-sent-to>` and confirm the answer matches the SES inbound endpoint for your region.
- **Mail arrives in S3 but the object is huge and the parser logs a memory error.** Some banks include base64-encoded PDF attachments on alert emails. The Lambda's default memory of 128 MB is enough for typical alerts but not for multi-MB attachments. Bump memory to 512 MB on the Lambda function configuration if this is a recurring issue. The parser ignores attachments by design — the body text is what carries the transaction.

## After setup: operations (optional)

The next two sections cover ongoing operational concerns — bucket retention and monthly cost — rather than setup steps. They're optional reading; skip ahead to [AWS deployment](aws-deployment.md) if you want to keep momentum.

### Bucket lifecycle and retention

Once mail is flowing, the S3 bucket grows by the size of every email SES drops in. At typical alert volumes — a handful per day — the bucket grows by a few MB per month. Over years, that adds up to noticeable but inexpensive storage.

Two reasonable retention strategies:

- **Keep everything.** Storage is cheap. The raw S3 objects are useful for replaying parser changes against historical data — if a parser bug is fixed, you can re-invoke the Lambda over old objects and rebuild the corrected transaction history.
- **Expire after 90 days.** Add an S3 Lifecycle rule that deletes objects 90 days after creation. The Lambda has already extracted the transaction into DynamoDB by then; the raw email is no longer load-bearing. This keeps the bucket bounded.

Pick based on how much you trust the parsers. If you are still tuning a new bank parser, keep everything. If the setup has been stable for a while, the 90-day expiry suffices.

### Costs at typical volumes

SES inbound charges $0.10 per 1,000 emails received, plus $0.09 per 1,000 incoming 256 KB mail chunks, plus standard S3 storage. For typical bank alerts (well under 256 KB each) the chunk fee rounds to zero. For a single user with two or three banks, that is well under $0.10 per month — the round-up to a billable cent is the dominant cost. The Lambda function tier covers the parser invocations free at this volume. The DynamoDB on-demand table costs a few cents per month at most. Most of the AWS bill, if there is one, is the existing S3 minimums on the account.
