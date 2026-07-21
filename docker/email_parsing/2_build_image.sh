#!/bin/bash
# Build from repo root using -f to specify the Dockerfile location
# Must be run from the repository root directory

ACCOUNT_ID=$(aws sts get-caller-identity --query Account --output text)

SCRIPT_DIR="$(cd "$(dirname "$0")" && pwd)"
REPO_ROOT="$(cd "$SCRIPT_DIR/../.." && pwd)"

cd "$REPO_ROOT"
docker build --platform linux/amd64 -f docker/email_parsing/Dockerfile -t "${ACCOUNT_ID}.dkr.ecr.us-west-2.amazonaws.com/email-parsing:latest" .
