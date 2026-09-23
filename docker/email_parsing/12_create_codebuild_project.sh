#!/bin/bash
# One-time setup: create (or bring up to date) the AWS CodeBuild project that
# builds the Lambda container image in AWS instead of on a local Docker daemon.
#
# Creates or updates:
#   - IAM role `tidings-codebuild-email-parsing`, trusted by
#     codebuild.amazonaws.com, with one inline policy scoped to exactly what
#     the build needs: write its own CloudWatch log group, get an ECR auth
#     token, and push/pull/describe images in the `email-parsing` repo.
#   - CloudWatch log group `/aws/codebuild/tidings-email-parsing`.
#   - CodeBuild project `tidings-email-parsing`: source is the public GitHub
#     repo (no credentials, no webhook), buildspec
#     docker/email_parsing/buildspec.yml, no artifacts, a small x86_64 Amazon
#     Linux standard image in privileged mode (needed for `docker build`),
#     20-minute timeout.
#
# Safe to re-run: existing resources are updated in place, nothing is deleted.
# Routine builds use 13_codebuild_build_and_push.sh, not this script.

set -euo pipefail

AWS_REGION="${AWS_REGION:-us-west-2}"
export AWS_REGION
PROJECT_NAME="tidings-email-parsing"
ROLE_NAME="tidings-codebuild-email-parsing"
POLICY_NAME="tidings-codebuild-email-parsing"
ECR_REPO="email-parsing"
LOG_GROUP="/aws/codebuild/${PROJECT_NAME}"
SOURCE_LOCATION="https://github.com/tvhahn/tidings.git"
BUILDSPEC="docker/email_parsing/buildspec.yml"
DEFAULT_BRANCH="main"
# Newest x86_64 Amazon Linux 2023 standard image as of 2026-09 (from
# `aws codebuild list-curated-environment-images`). It ships Docker.
BUILD_IMAGE="${BUILD_IMAGE:-aws/codebuild/amazonlinux-x86_64-standard:6.0}"

ACCOUNT_ID=$(aws sts get-caller-identity --query Account --output text)
echo "Account ${ACCOUNT_ID}, region ${AWS_REGION}"

# --- IAM role ---------------------------------------------------------------

TRUST_POLICY=$(jq -n '{
  Version: "2012-10-17",
  Statement: [{
    Effect: "Allow",
    Principal: {Service: "codebuild.amazonaws.com"},
    Action: "sts:AssumeRole"
  }]
}')

LOG_GROUP_ARN="arn:aws:logs:${AWS_REGION}:${ACCOUNT_ID}:log-group:${LOG_GROUP}"
ECR_REPO_ARN="arn:aws:ecr:${AWS_REGION}:${ACCOUNT_ID}:repository/${ECR_REPO}"

# The bare log-group ARN is listed alongside the `:*` form because
# CreateLogGroup is authorized against the group ARN itself, which `:*` does
# not match (the same pair AWS's generated CodeBuild service policy uses).
ROLE_POLICY=$(jq -n --arg lg "$LOG_GROUP_ARN" --arg repo "$ECR_REPO_ARN" '{
  Version: "2012-10-17",
  Statement: [
    {
      Sid: "BuildLogs",
      Effect: "Allow",
      Action: ["logs:CreateLogGroup", "logs:CreateLogStream", "logs:PutLogEvents"],
      Resource: [$lg, ($lg + ":*")]
    },
    {
      Sid: "EcrAuth",
      Effect: "Allow",
      Action: "ecr:GetAuthorizationToken",
      Resource: "*"
    },
    {
      Sid: "EcrPushPull",
      Effect: "Allow",
      Action: [
        "ecr:BatchCheckLayerAvailability",
        "ecr:CompleteLayerUpload",
        "ecr:InitiateLayerUpload",
        "ecr:PutImage",
        "ecr:UploadLayerPart",
        "ecr:BatchGetImage",
        "ecr:GetDownloadUrlForLayer",
        "ecr:DescribeImages"
      ],
      Resource: $repo
    }
  ]
}')

if aws iam get-role --role-name "$ROLE_NAME" >/dev/null 2>&1; then
  echo "Role ${ROLE_NAME} exists; updating its trust policy"
  aws iam update-assume-role-policy --role-name "$ROLE_NAME" \
    --policy-document "$TRUST_POLICY"
  ROLE_IS_NEW=0
else
  echo "Creating role ${ROLE_NAME}"
  aws iam create-role --role-name "$ROLE_NAME" \
    --assume-role-policy-document "$TRUST_POLICY" \
    --description "CodeBuild service role for ${PROJECT_NAME}: build logs and push to ECR ${ECR_REPO}" \
    --query 'Role.Arn' --output text
  ROLE_IS_NEW=1
fi

echo "Putting inline policy ${POLICY_NAME}"
aws iam put-role-policy --role-name "$ROLE_NAME" \
  --policy-name "$POLICY_NAME" --policy-document "$ROLE_POLICY"

ROLE_ARN=$(aws iam get-role --role-name "$ROLE_NAME" --query 'Role.Arn' --output text)

# --- Log group --------------------------------------------------------------

if aws logs describe-log-groups --log-group-name-prefix "$LOG_GROUP" \
    --query "logGroups[?logGroupName=='${LOG_GROUP}'] | length(@)" --output text \
    | grep -qx 1; then
  echo "Log group ${LOG_GROUP} exists"
else
  echo "Creating log group ${LOG_GROUP}"
  aws logs create-log-group --log-group-name "$LOG_GROUP"
fi

# --- CodeBuild project --------------------------------------------------------

PROJECT_JSON=$(jq -n \
  --arg name "$PROJECT_NAME" \
  --arg location "$SOURCE_LOCATION" \
  --arg buildspec "$BUILDSPEC" \
  --arg branch "$DEFAULT_BRANCH" \
  --arg image "$BUILD_IMAGE" \
  --arg role "$ROLE_ARN" \
  --arg logGroup "$LOG_GROUP" '{
  name: $name,
  description: "Builds the email-parsing Lambda image from GitHub and pushes it to ECR",
  source: {
    type: "GITHUB",
    location: $location,
    buildspec: $buildspec,
    gitCloneDepth: 1,
    reportBuildStatus: false
  },
  sourceVersion: $branch,
  artifacts: {type: "NO_ARTIFACTS"},
  environment: {
    type: "LINUX_CONTAINER",
    computeType: "BUILD_GENERAL1_SMALL",
    image: $image,
    imagePullCredentialsType: "CODEBUILD",
    privilegedMode: true
  },
  serviceRole: $role,
  timeoutInMinutes: 20,
  logsConfig: {
    cloudWatchLogs: {status: "ENABLED", groupName: $logGroup},
    s3Logs: {status: "DISABLED"}
  }
}')

EXISTING=$(aws codebuild batch-get-projects --names "$PROJECT_NAME" \
  --query 'length(projects)' --output text)

if [ "$EXISTING" = "1" ]; then
  echo "Updating CodeBuild project ${PROJECT_NAME}"
  aws codebuild update-project --cli-input-json "$PROJECT_JSON" \
    --query 'project.arn' --output text
else
  echo "Creating CodeBuild project ${PROJECT_NAME}"
  # A just-created role takes a few seconds to become assumable; CodeBuild
  # rejects the project with "not authorized to perform sts:AssumeRole" until
  # then. Retry only that error.
  ATTEMPTS=0
  until OUT=$(aws codebuild create-project --cli-input-json "$PROJECT_JSON" \
      --query 'project.arn' --output text 2>&1); do
    ATTEMPTS=$((ATTEMPTS + 1))
    if [ "$ROLE_IS_NEW" = "1" ] && [ "$ATTEMPTS" -lt 12 ] \
        && grep -q 'AssumeRole' <<<"$OUT"; then
      echo "  role not assumable yet, retrying in 5 s (${ATTEMPTS}/12)"
      sleep 5
    else
      echo "$OUT" >&2
      exit 1
    fi
  done
  echo "$OUT"
fi

echo
echo "Done. Start a build with: bash docker/email_parsing/13_codebuild_build_and_push.sh [git-ref]"
