#!/bin/bash

ACCOUNT_ID=$(aws sts get-caller-identity --query Account --output text)

aws lambda update-function-code --function-name email-parser --image-uri "${ACCOUNT_ID}.dkr.ecr.us-west-2.amazonaws.com/email-parsing:latest"
aws lambda update-function-code --function-name monthly-summary --image-uri "${ACCOUNT_ID}.dkr.ecr.us-west-2.amazonaws.com/email-parsing:latest"