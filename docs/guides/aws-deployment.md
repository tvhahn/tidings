# AWS deployment guide

**For AWS users with a registered domain who want to scale beyond the local Docker self-host path.** By the end, you'll have a Lambda function triggered by S3 events processing emails into DynamoDB, plus a monthly-summary Lambda triggered on schedule by EventBridge.

> **Prerequisite — a registered domain.** This path requires a domain you control DNS for. SES inbound depends on MX and DKIM records on that domain; without one, nothing in this guide works. If you do not already own a domain, the IMAP/Docker path ([Email setup](https://docs.gettidings.com/self-hosting/email/)) does the same job without DNS.

## Prerequisites

Before running the deployment scripts:

1. **Two IAM roles in the AWS console.** Create `email-parser-iam` (used by the email-parser function, per `4_establish_lambda_func.sh`) and `lambda-s3-trigger-role` (used by the monthly-summary and coverage-check functions, per scripts 7 and 9). The deployment scripts assume both already exist. Both need `AWSLambdaBasicExecutionRole` for CloudWatch Logs, plus the grants in [Execution-role permissions](#execution-role-permissions) below.
2. **Email-to-S3 routing.** Complete [Email-to-S3 setup](email-to-s3-setup.md) so your S3 bucket already receives bank emails — a separate setup step covering domain verification, SES inbound, MX record, and the S3 receipt rule. Lambda is downstream of that pipeline; without inbound emails landing in S3, the function has nothing to trigger on.

### Execution-role permissions

What the handlers actually call, table by table. Scope each resource to your own account
and region; nothing here needs a wildcard resource.

**`email-parser-iam` (email-parser):**

| Action | Resource | Why |
|--------|----------|-----|
| `ssm:GetParameter` | `/email-parser/openai-api-key` | `src/finance/secrets.py` reads the key with `WithDecryption=True`. Add `kms:Decrypt` on the key too if the parameter is a SecureString under a customer-managed KMS key |
| `s3:GetObject` | the inbound email bucket | `get_s3_file()` fetches the `.eml` the event names |
| `dynamodb:Query`, `dynamodb:PutItem`, `dynamodb:UpdateItem` | `Transactions` | the dedup query over the partition, the row write, and the `TransactionContext` update after enrichment |
| `dynamodb:GetItem` | `CategoryConfig` | category vocabulary, overrides, merchant aliases, and ignore rules each read one item |
| `dynamodb:GetItem` | `BudgetConfig` | budget targets and groups for the enrichment fields |
| `dynamodb:DescribeTable`, `dynamodb:CreateTable`, `dynamodb:PutItem`, `dynamodb:Query`, `dynamodb:UpdateItem` | `ParseFailures` | the Needs-review quarantine store; it is the one table the handler creates on demand (`_ensure_table()` probes, then creates on `ResourceNotFoundException`) |
| `sns:Publish` | the topic in `SNS_TOPIC_ARN` | transaction notifications |
| `sqs:SendMessage` | `email-parser-dlq` | the on-failure destination `4_establish_lambda_func.sh` attaches |

**`lambda-s3-trigger-role` (monthly-summary, coverage-check):**

| Action | Resource | Why |
|--------|----------|-----|
| `dynamodb:Query` | `Transactions` | both handlers aggregate over the mapped partitions |
| `dynamodb:DescribeTable`, `dynamodb:Query` | `ParseFailures` | coverage-check only, for the quiet-institution check (plus `dynamodb:CreateTable` if that table does not exist yet) |
| `sns:Publish` | the topic in `SNS_TOPIC_ARN` | the monthly summary SMS and the coverage notices |

Several of these fail **silently** when the grant is missing, so a permissions gap shows
up as wrong data rather than as an error:

- The category vocabulary, overrides, merchant aliases, and ignore rules all fail open to
  their bundled seeds on any exception, `AccessDenied` included — categorization keeps
  running, against the shipped defaults instead of your customizations.
- Notification dispatch is fail-open too: an `sns:Publish` denial is logged and swallowed,
  and the transaction is still written.

`Transactions`, `CategoryConfig`, and `BudgetConfig` are created by neither a script nor a
handler — create them before the first invocation. Key schemas are in
[`ARCHITECTURE.md`](../ARCHITECTURE.md); `create_transaction_table()` in
`src/finance/transaction_db_admin.py` is the helper for the `Transactions` one.

## Docker development (Lambda function)

**Note:** The Lambda Docker setup (`docker/email_parsing/`) is separate from the devcontainer. The devcontainer is for local development; the Lambda Docker is for AWS deployment.

### Building and testing locally

```bash
# Build docker image for Lambda (from repo root, using -f flag)
docker build --platform linux/amd64 -f docker/email_parsing/Dockerfile -t docker-image:test .

# Or use the local build script (can be run from any directory):
bash docker/email_parsing/2_build_image.sh

# No local Docker? Build in AWS CodeBuild instead (pushes to ECR; see below):
bash docker/email_parsing/13_codebuild_build_and_push.sh

# Run container locally for testing
docker run -it --rm docker-image:test

# Test Lambda function with sample event
# (Ensure test_event.json is configured properly)
```

The Lambda loads `OPENAI_API_KEY` from SSM Parameter Store first (`/email-parser/openai-api-key`), falling back to the function's environment variables — see the loader note under the deployment workflow. It is not baked into the Docker image.

## AWS deployment workflow

Run the deployment scripts in order from `docker/email_parsing/`:

```bash
cd docker/email_parsing/
./0_authenticate_to_ecr.sh    # Authenticate to AWS ECR
./1_aws_repo_create.sh        # Create ECR repository
./2_build_image.sh            # Build and tag Docker image
./3_push_image.sh             # Push image to ECR
./4_establish_lambda_func.sh  # Create Lambda function
./5_update_func.sh            # Update existing Lambda function
./6_invoke_func.sh            # Post-deploy boot check (side-effect free)
./7_establish_summary_lambda.sh  # Create monthly-summary Lambda function
./8_create_schedule.sh        # Create EventBridge monthly schedule
./9_establish_coverage_lambda.sh  # Create coverage-check Lambda function
./10_create_coverage_schedule.sh  # Create EventBridge daily coverage schedule
./11_set_function_env.sh      # Merge personal-config env vars into a function
./12_create_codebuild_project.sh  # One-time: create the CodeBuild project and its IAM role
./13_codebuild_build_and_push.sh  # Build in CodeBuild and push to ECR (replaces 0, 2, 3)
```

For routine updates to an existing deployment, run step 13 and then step 5. Steps 0, 2, and 3 are the local-Docker alternative to 13: authenticate, build, and push from your own machine.

### Building in CodeBuild

`12_create_codebuild_project.sh` creates the CodeBuild project `tidings-email-parsing`, its service role `tidings-codebuild-email-parsing`, and the log group `/aws/codebuild/tidings-email-parsing`. The role can write that log group and push to the `email-parsing` ECR repository, nothing else. The project runs `docker/email_parsing/buildspec.yml` on a `BUILD_GENERAL1_SMALL` x86_64 Amazon Linux instance in privileged mode (needed for `docker build`), with a 20-minute timeout and no webhook, so it only builds when you start it. The script is safe to re-run: it updates what already exists, so it is also how you re-create or repair the project.

`13_codebuild_build_and_push.sh [git-ref]` starts a build of one commit (default `HEAD`), polls it every 10 seconds, and prints the image URI and digest when it succeeds. CodeBuild checks the source out from the public GitHub repository, not from your working tree, so the commit must be pushed first; the script refuses a commit that is not on any `origin/*` branch. Each build pushes two tags: `latest` (or `IMAGE_TAG=<tag>` when set) and `git-<12-char sha>`, which names that exact build and is what you would roll back to. On failure the script prints the last 60 log lines; the full log is in CloudWatch under `/aws/codebuild/tidings-email-parsing`.

Cost: a build takes about a minute (55 seconds measured, 2026-09-22). [CodeBuild pricing](https://aws.amazon.com/codebuild/pricing/) bills `general1.small` on Linux at $0.005 per build minute, rounded up to the whole minute, so a build costs half a cent. The free tier covers 100 build minutes per month on that instance type and does not expire after the 12-month AWS free tier term.

### What each step relies on

If you want to read the AWS documentation alongside the scripts, the canonical references are:

- Steps 0–3: [Pushing a Docker image to an ECR private repository](https://docs.aws.amazon.com/AmazonECR/latest/userguide/docker-push-ecr-image.html). The build script targets `linux/amd64` because Lambda runs x86_64 by default; `aws ecr create-repository` uses `--image-tag-mutability MUTABLE` and `--image-scanning-configuration scanOnPush=true`. (Note: AWS now recommends configuring image scanning at the registry level via `PutRegistryScanningConfiguration` rather than per-repo with `--image-scanning-configuration`. The per-repo flag still works and is acceptable for a single-account hobby deployment.)
- Step 4: [Creating Lambda functions defined as container images](https://docs.aws.amazon.com/lambda/latest/dg/images-create.html). The script invokes `aws lambda create-function --package-type Image --code ImageUri=<ECR-URI>` at 256 MB with a 60 s timeout, then creates the `email-parser-dlq` SQS queue and attaches it as the on-failure destination behind two retries. The sizing is measured: at 128 MB the live function peaked at 124 MB and ran a p95 of 15.4 s (median 4.9 s), leaving headroom on neither axis.
- Step 5: [Updating Lambda function code with a container image](https://docs.aws.amazon.com/lambda/latest/dg/images-create.html). Uses `aws lambda update-function-code --image-uri` against both the email-parser and monthly-summary functions, waits for each update to settle, then prints the resolved image digest per function — `:latest` is a moving tag, the digest is what proves the new build landed. (The same `images-create.html` page covers both create and update workflows.)
- Step 6: a boot check, not a real invocation — see [Verify the deployment](#verify-the-deployment).
- Step 7: Same Lambda container-image flow for the monthly-summary function. Assumes the role `lambda-s3-trigger-role` already exists.
- Step 8: [Creating a schedule with EventBridge Scheduler](https://docs.aws.amazon.com/scheduler/latest/UserGuide/getting-started.html). Cron `cron(0 17 8 * ? *)` is "minute 0, 17:00 UTC, day-of-month 8, any month, day-of-week placeholder, any year" — the 6-field format EventBridge Scheduler requires.
- Step 11: [Using Lambda environment variables](https://docs.aws.amazon.com/lambda/latest/dg/configuration-envvars.html). Run on demand rather than in sequence — see [Personal config in Lambda](#personal-config-in-lambda).
- Steps 12–13: [Build a Docker image and push it to Amazon ECR with CodeBuild](https://docs.aws.amazon.com/codebuild/latest/userguide/sample-docker.html). The buildspec logs in to ECR, builds from the repository root exactly as `2_build_image.sh` does, and pushes both tags; the Lambda update stays a separate step (5).

The Lambda function loads `OPENAI_API_KEY` from SSM Parameter Store at `/email-parser/openai-api-key` ([Working with Parameter Store](https://docs.aws.amazon.com/systems-manager/latest/userguide/parameter-store-working-with.html)). Falls back to env var, then `.env` for local/CI use.

## Personal config in Lambda

A self-hosted install keeps its personalization in `data/` — the config file, the user
mappings CSV, the suppression list. The Lambda image ships `src/` and the handlers only:
there is no `data/` directory in it, and the files that *are* bundled
(`src/finance/user_mappings.csv`, `src/finance/config/blocked_companies.json`) hold public
demo values. Environment variables are what replaces `data/` there. All of them are
optional; unset, the handlers use the code defaults.

| Variable | Function(s) | Format | Effect when unset |
|----------|-------------|--------|-------------------|
| `USER_ID` | email-parser | a user id string | Budget lookups, the quarantine partition (`USER#<id>`) and the `<id>@local` partition all fall back to `default`. Set it to the same `user_id` the dashboard uses, or quarantined emails never reach Needs review |
| `USER_MAPPINGS` | email-parser, monthly-summary, coverage-check | comma-separated `forwarded_to=user_id` pairs, e.g. `alerts@example.com=alice` | The bundled demo CSV is the whole mapping: monthly-summary queries demo partitions and reports 0 transactions, and email-parser picks the wrong address out of a multi-recipient header and stamps the wrong `user_id` |
| `NOTIFICATION_BLOCKED_COMPANIES` | email-parser | JSON array (`["Example Coffee","Example Transit"]`) or comma-separated list | Only the bundled seed applies, and it ships empty — every transaction notifies |
| `CATEGORIZATION_MODEL` | email-parser | an OpenAI model id | `DEFAULT_OPENAI_CHAT_MODEL`, currently `gpt-5.6-luna` |
| `CATEGORIZATION_REASONING_EFFORT` | email-parser | `none` / `low` / `medium` / `high` / `xhigh` | On the default model, the tuned `none`; on any other model no effort is sent at all. An unrecognized value is logged and dropped, never fatal |
| `SNS_TOPIC_ARN` | all three | topic ARN | No SNS provider is selected and notifications go to the log only |
| `AWS_REGION` | all three | region name — reserved: the Lambda runtime sets it to the function's own region and does not let you override it | n/a in Lambda; outside it the code falls back to `us-west-2` |

Set them with `11_set_function_env.sh`, never with a hand-written
`aws lambda update-function-configuration --environment`: that flag **replaces** the whole
variable map, which is how a 2026-04-08 hand-run wiped this function's environment (the
incident that moved the OpenAI key into SSM — see the `src/finance/secrets.py` docstring).
The script reads the live map, merges only the four keys it owns
(`CATEGORIZATION_MODEL`, `CATEGORIZATION_REASONING_EFFORT`,
`NOTIFICATION_BLOCKED_COMPANIES`, `USER_MAPPINGS`), aborts if any other variable would
change or disappear, and pins the write to the revision it read. `USER_ID`
and `SNS_TOPIC_ARN` are outside its allowlist — set those in the console or at create time.

```bash
# The two personal values: --set-file keeps them out of the shell history, the
# process list, and every line the script prints.
./11_set_function_env.sh --set-file USER_MAPPINGS=mappings.txt
./11_set_function_env.sh --function monthly-summary --set-file USER_MAPPINGS=mappings.txt
./11_set_function_env.sh --set-file NOTIFICATION_BLOCKED_COMPANIES=blocked.json

# Preview a change without writing it
./11_set_function_env.sh --set CATEGORIZATION_MODEL=gpt-5.6-terra --dry-run
```

Both personal variables work on any install, not just Lambda — the same names in a
`docker-compose.yml` `environment:` block do the same thing. `USER_MAPPINGS` takes
precedence over `data/config/user_mappings.csv`, which in turn beats the bundled demo CSV;
`NOTIFICATION_BLOCKED_COMPANIES` is *unioned* with the bundled `blocked_companies.json`
(case-insensitive, no duplicates) rather than replacing it, and is re-read on every
notification, so an edit applies to the next transaction without a restart.

## Verify the deployment

**1. Boot check — safe to run against production.** After `5_update_func.sh`:

```bash
./6_invoke_func.sh
```

It sync-invokes the function with `test_event.json`, whose S3 event names a bucket that
does not exist. The handler logs the model it resolved and then dies fetching that key, so
a `FunctionError` is the **expected** outcome: nothing downstream runs — no DynamoDB
write, no notification, no model call. The script exits 0 when the log tail carries

```text
Categorization model=gpt-5.6-luna reasoning_effort=none
```

and exits 1 when it does not. An absent line means the function never reached the handler:
check the resolved digest step 5 printed, and `/aws/lambda/email-parser` in CloudWatch.

**2. Round-trip test.** `tests/integration/test_lambda_e2e.py` uploads a fictitious `$1.23`
"E2E TEST CAFE" email to the inbound bucket, invokes the function, and asserts the
DynamoDB row, how its category was decided, and the `TransactionContext` enrichment. An
override rule or the model may decide the category; a swallowed AI failure
(`CategoryAudit.source` of `ai_fallback`) fails the test, and when the model decided,
`CategoryAudit.model` must match. It
creates a marked temporary budget target and deletes both that and its own transaction row
in teardown, pass or fail. It is a real invocation, so the notification fires too — expect
one SMS. The test is excluded from every gate; run it by hand:

```bash
E2E_EMAIL_BUCKET=your-inbound-bucket E2E_USER_ID=your-user-id \
  uv run pytest tests/integration/test_lambda_e2e.py -m integration
```

Optional: `E2E_LAMBDA_FUNCTION`, `E2E_TRANSACTIONS_TABLE`, `E2E_BUDGET_TABLE`,
`AWS_REGION`, and `E2E_EXPECTED_MODEL` — set that last one to whatever
`CATEGORIZATION_MODEL` the deployed function carries, or the model check compares
against the code default and fails. If an override rule matches the test merchant on your
account the model never runs and that check is skipped.

**3. Real email.** Send one to your SES inbound address. Within ~30 seconds CloudWatch
Logs show the parser output, the `Transactions` table holds the item, and the dashboard
displays it. If not, read CloudWatch first — the handler logs every step from S3 trigger
through DynamoDB write.

### Changing the model later

```bash
# Point the live function at a different categorizer model
./11_set_function_env.sh --set CATEGORIZATION_MODEL=gpt-5.6-terra
./6_invoke_func.sh    # confirm the log line now names that model

# Roll back to the previous model
./11_set_function_env.sh --set CATEGORIZATION_MODEL=gpt-5.4-nano

# Or drop the overrides entirely, back to the code defaults
./11_set_function_env.sh --unset CATEGORIZATION_MODEL \
                         --unset CATEGORIZATION_REASONING_EFFORT
```

No redeploy is needed: the handler reads both variables per invocation, so the next event
picks the change up. The effort default only applies while the model is the code default —
pin a different model and the call goes out with no reasoning effort unless you set one.

## Next step

Your Lambda is deployed. Now wire notifications: [pick a provider](https://docs.gettidings.com/notifications/) so you get alerted when transactions arrive.
