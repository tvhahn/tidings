#!/bin/bash
# Create an EventBridge Scheduler rule that invokes the monthly-summary Lambda
# on the 8th of every month at 5:00 PM UTC (10:00 AM Pacific).
#
# Prerequisites:
#   1. monthly-summary Lambda must exist (run 7_establish_summary_lambda.sh)
#   2. An IAM role that allows Scheduler to invoke the Lambda. The script
#      creates this role automatically if it does not exist.

ACCOUNT_ID=$(aws sts get-caller-identity --query Account --output text)
REGION=us-west-2
LAMBDA_ARN="arn:aws:lambda:${REGION}:${ACCOUNT_ID}:function:monthly-summary"
ROLE_NAME="eventbridge-invoke-monthly-summary"
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

echo "Creating EventBridge schedule monthly-summary-sms..."
aws scheduler create-schedule \
  --name monthly-summary-sms \
  --schedule-expression "cron(0 17 8 * ? *)" \
  --target "{
    \"Arn\": \"${LAMBDA_ARN}\",
    \"RoleArn\": \"${ROLE_ARN}\"
  }" \
  --flexible-time-window '{"Mode": "OFF"}'

echo "Done. Schedule: 8th of every month at 5:00 PM UTC (10:00 AM Pacific)."
