#!/bin/bash

ACCOUNT_ID=$(aws sts get-caller-identity --query Account --output text)

# Run the get-login-password command to authenticate the Docker CLI to your Amazon ECR registry.
aws ecr get-login-password --region us-west-2 | docker login --username AWS --password-stdin "${ACCOUNT_ID}.dkr.ecr.us-west-2.amazonaws.com"
