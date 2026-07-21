#!/bin/bash
# Create the monthly-summary Lambda function using the same Docker image
# as email-parser but with summary_handler.handler as the entry point.

ACCOUNT_ID=$(aws sts get-caller-identity --query Account --output text)

aws lambda create-function \
  --function-name monthly-summary \
  --package-type Image \
  --code ImageUri="${ACCOUNT_ID}.dkr.ecr.us-west-2.amazonaws.com/email-parsing:latest" \
  --role "arn:aws:iam::${ACCOUNT_ID}:role/lambda-s3-trigger-role" \
  --image-config Command=summary_handler.handler \
  --timeout 30 \
  --memory-size 128
