#!/bin/bash
# Create the coverage-check Lambda function using the same Docker image
# as email-parser but with coverage_handler.handler as the entry point.
# Mirrors 7_establish_summary_lambda.sh; schedule it with
# 10_create_coverage_schedule.sh.

ACCOUNT_ID=$(aws sts get-caller-identity --query Account --output text)

aws lambda create-function \
  --function-name coverage-check \
  --package-type Image \
  --code ImageUri="${ACCOUNT_ID}.dkr.ecr.us-west-2.amazonaws.com/email-parsing:latest" \
  --role "arn:aws:iam::${ACCOUNT_ID}:role/lambda-s3-trigger-role" \
  --image-config Command=coverage_handler.handler \
  --timeout 60 \
  --memory-size 128
