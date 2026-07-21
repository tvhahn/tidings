#!/bin/bash
# Create an EventBridge Scheduler rule that invokes the coverage-check Lambda
# once a day at 5:00 PM UTC (10:00 AM Pacific) to notify on institutions whose
# bank-alert cadence has just gone quiet (ingestion coverage).
#
# Prerequisites:
#   1. The coverage-check Lambda exists — create it with
#      9_establish_coverage_lambda.sh (same email-parsing image,
#      coverage_handler.handler entry point).
#   2. An IAM role that allows Scheduler to invoke the Lambda. The script
#      creates this role automatically if it does not exist.

ACCOUNT_ID=$(aws sts get-caller-identity --query Account --output text)
REGION=us-west-2
LAMBDA_ARN="arn:aws:lambda:${REGION}:${ACCOUNT_ID}:function:coverage-check"
ROLE_NAME="eventbridge-invoke-coverage-check"
ROLE_ARN="arn:aws:iam::${ACCOUNT_ID}:role/${ROLE_NAME}"

# --- Create the scheduler execution role (idempotent) ---

TRUST_POLICY='{
  "Version": "2012-10-17",
  "Statement": [{
    "Effect": "Allow",
    "Principal": {"Service": "scheduler.amazonaws.com"},
    "Action": "sts:AssumeRole"
  }]
}'

INVOKE_POLICY="{
  \"Version\": \"2012-10-17\",
  \"Statement\": [{
    \"Effect\": \"Allow\",
    \"Action\": \"lambda:InvokeFunction\",
    \"Resource\": \"${LAMBDA_ARN}\"
  }]
}"

echo "Creating IAM role ${ROLE_NAME} (skipped if exists)..."
aws iam create-role \
  --role-name "$ROLE_NAME" \
  --assume-role-policy-document "$TRUST_POLICY" \
  2>/dev/null || echo "  Role already exists."

aws iam put-role-policy \
  --role-name "$ROLE_NAME" \
  --policy-name invoke-lambda \
  --policy-document "$INVOKE_POLICY"

# Allow time for IAM propagation
echo "Waiting 10s for IAM propagation..."
sleep 10

# --- Create the schedule ---

echo "Creating EventBridge schedule coverage-quiet-check..."
aws scheduler create-schedule \
  --name coverage-quiet-check \
  --schedule-expression "cron(0 17 * * ? *)" \
  --target "{
    \"Arn\": \"${LAMBDA_ARN}\",
    \"RoleArn\": \"${ROLE_ARN}\"
  }" \
  --flexible-time-window '{"Mode": "OFF"}'

echo "Done. Schedule: every day at 5:00 PM UTC (10:00 AM Pacific)."
