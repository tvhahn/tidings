#!/bin/bash

ACCOUNT_ID=$(aws sts get-caller-identity --query Account --output text)

docker push "${ACCOUNT_ID}.dkr.ecr.us-west-2.amazonaws.com/email-parsing:latest"