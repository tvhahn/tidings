# AWS deployment guide

**For AWS users with a registered domain who want to scale beyond the local Docker self-host path.** By the end, you'll have a Lambda function triggered by S3 events processing emails into DynamoDB, plus a monthly-summary Lambda triggered on schedule by EventBridge.

> **Prerequisite — a registered domain.** This path requires a domain you control DNS for. SES inbound depends on MX and DKIM records on that domain; without one, nothing in this guide works. If you do not already own a domain, the IMAP/Docker path ([Email setup](https://docs.gettidings.com/self-hosting/email/)) does the same job without DNS.

## Prerequisites

Before running the deployment scripts:

1. **Two IAM roles in the AWS console.** Create `email-parser-iam` (with `AWSLambdaBasicExecutionRole` plus `s3:GetObject` on the inbound bucket) and `lambda-s3-trigger-role` (used by the monthly-summary function). The deployment scripts assume both already exist.
2. **Email-to-S3 routing.** Complete [Email-to-S3 setup](email-to-s3-setup.md) so your S3 bucket already receives bank emails — a separate setup step covering domain verification, SES inbound, MX record, and the S3 receipt rule. Lambda is downstream of that pipeline; without inbound emails landing in S3, the function has nothing to trigger on.

## Docker development (Lambda function)

**Note:** The Lambda Docker setup (`docker/email_parsing/`) is separate from the devcontainer. The devcontainer is for local development; the Lambda Docker is for AWS deployment.

### Building and testing locally

```bash
# Build docker image for Lambda (from repo root, using -f flag)
docker build --platform linux/amd64 -f docker/email_parsing/Dockerfile -t docker-image:test .

# Or use the build script (can be run from any directory):
bash docker/email_parsing/2_build_image.sh

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
./6_invoke_func.sh            # Test invoke Lambda function
./7_establish_summary_lambda.sh  # Create monthly-summary Lambda function
./8_create_schedule.sh        # Create EventBridge monthly schedule
./9_establish_coverage_lambda.sh  # Create coverage-check Lambda function
./10_create_coverage_schedule.sh  # Create EventBridge daily coverage schedule
```

For routine updates to an existing deployment, you typically only need steps 0, 2, 3, and 5.

### What each step relies on

If you want to read the AWS documentation alongside the scripts, the canonical references are:

- Steps 0–3: [Pushing a Docker image to an ECR private repository](https://docs.aws.amazon.com/AmazonECR/latest/userguide/docker-push-ecr-image.html). The build script targets `linux/amd64` because Lambda runs x86_64 by default; `aws ecr create-repository` uses `--image-tag-mutability MUTABLE` and `--image-scanning-configuration scanOnPush=true`. (Note: AWS now recommends configuring image scanning at the registry level via `PutRegistryScanningConfiguration` rather than per-repo with `--image-scanning-configuration`. The per-repo flag still works and is acceptable for a single-account hobby deployment.)
- Step 4: [Creating Lambda functions defined as container images](https://docs.aws.amazon.com/lambda/latest/dg/images-create.html). The script invokes `aws lambda create-function --package-type Image --code ImageUri=<ECR-URI>`.
- Step 5: [Updating Lambda function code with a container image](https://docs.aws.amazon.com/lambda/latest/dg/images-create.html). Uses `aws lambda update-function-code --image-uri` against both the email-parser and monthly-summary functions. (The same `images-create.html` page covers both create and update workflows.)
- Step 7: Same Lambda container-image flow for the monthly-summary function. Assumes the role `lambda-s3-trigger-role` already exists.
- Step 8: [Creating a schedule with EventBridge Scheduler](https://docs.aws.amazon.com/scheduler/latest/UserGuide/getting-started.html). Cron `cron(0 17 8 * ? *)` is "minute 0, 17:00 UTC, day-of-month 8, any month, day-of-week placeholder, any year" — the 6-field format EventBridge Scheduler requires.

The Lambda function loads `OPENAI_API_KEY` from SSM Parameter Store at `/email-parser/openai-api-key` ([Working with Parameter Store](https://docs.aws.amazon.com/systems-manager/latest/userguide/parameter-store-working-with.html)). Falls back to env var, then `.env` for local/CI use.

## Verify the deployment

Send a test email to your SES inbound address. Within ~30 seconds:

1. CloudWatch Logs for the email-parser function should show parser output.
2. The `Transactions` table in DynamoDB should have a new item with the parsed transaction.
3. The dashboard should display the parsed transaction.

If any of those don't happen, check CloudWatch Logs first — the Lambda function logs every step from S3 trigger through DynamoDB write.

## Next step

Your Lambda is deployed. Now wire notifications: [pick a provider](https://docs.gettidings.com/notifications/) so you get alerted when transactions arrive.
