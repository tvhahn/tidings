#!/bin/bash
set -euo pipefail

ACCOUNT_ID=$(aws sts get-caller-identity --query Account --output text)
AWS_REGION="${AWS_REGION:-us-west-2}"

aws lambda create-function \
  --function-name email-parser \
  --package-type Image \
  --code ImageUri="${ACCOUNT_ID}.dkr.ecr.${AWS_REGION}.amazonaws.com/email-parsing:latest" \
  --role "arn:aws:iam::${ACCOUNT_ID}:role/email-parser-iam"

# Dead-letter queue for the async (S3 → Lambda) path: after the retries below
# are exhausted, the failed event lands here instead of being dropped — a
# poison email is otherwise silently lost. The handler raises when any record
# in a batch fails, which is what routes the event to this destination.
# NB: the email-parser-iam role needs sqs:SendMessage on this queue.
DLQ_URL=$(aws sqs create-queue --queue-name email-parser-dlq --query QueueUrl --output text)
DLQ_ARN=$(aws sqs get-queue-attributes --queue-url "$DLQ_URL" \
  --attribute-names QueueArn --query 'Attributes.QueueArn' --output text)

aws lambda put-function-event-invoke-config \
  --function-name email-parser \
  --maximum-retry-attempts 2 \
  --destination-config "{\"OnFailure\":{\"Destination\":\"${DLQ_ARN}\"}}"

echo "email-parser created; on-failure destination: ${DLQ_ARN}"
