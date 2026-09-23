#!/bin/bash
# Build the Lambda container image in AWS CodeBuild and push it to ECR.
# Replaces the local-Docker steps 0 (ECR login), 2 (build), and 3 (push).
#
# Usage: 13_codebuild_build_and_push.sh [git-ref]      (default: HEAD)
#        IMAGE_TAG=<tag> 13_codebuild_build_and_push.sh [git-ref]
#
# CodeBuild builds from the public GitHub repo, not from this working tree, so
# the commit must already be pushed to origin; uncommitted or unpushed changes
# are not in the image. The build pushes two tags: $IMAGE_TAG (default
# `latest`) and `git-<12-char sha>`, a fixed name for that exact build.
#
# Then run 5_update_func.sh to roll :latest onto the Lambda functions.
#
# The CodeBuild project is created once by 12_create_codebuild_project.sh.

set -euo pipefail

AWS_REGION="${AWS_REGION:-us-west-2}"
export AWS_REGION
PROJECT_NAME="tidings-email-parsing"
ECR_REPO="email-parsing"
IMAGE_TAG="${IMAGE_TAG:-latest}"
BUILDSPEC_PATH="docker/email_parsing/buildspec.yml"
POLL_SECONDS=10
LOG_LINES=60

command -v jq >/dev/null || { echo "jq is required" >&2; exit 1; }

SCRIPT_DIR="$(cd "$(dirname "$0")" && pwd)"
REPO_ROOT="$(cd "$SCRIPT_DIR/../.." && pwd)"
cd "$REPO_ROOT"

REF="${1:-HEAD}"

git fetch -q origin
SHA=$(git rev-parse --verify --quiet "${REF}^{commit}") || {
  echo "Cannot resolve '${REF}' to a commit" >&2
  exit 1
}
SHORT_SHA="${SHA:0:12}"

if [ -z "$(git branch -r --contains "$SHA")" ]; then
  echo "Commit ${SHORT_SHA} is not on any origin/* branch." >&2
  echo "CodeBuild builds from GitHub, so push the commit first, then re-run." >&2
  exit 1
fi

START_ARGS=(
  --project-name "$PROJECT_NAME"
  --source-version "$SHA"
  --environment-variables-override "name=IMAGE_TAG,value=${IMAGE_TAG},type=PLAINTEXT"
)

# Commits older than the buildspec itself do not contain it; send the local
# copy inline so those commits (for example a rollback target) still build.
if ! git cat-file -e "${SHA}:${BUILDSPEC_PATH}" 2>/dev/null; then
  echo "Commit ${SHORT_SHA} has no ${BUILDSPEC_PATH}; using the local copy inline."
  START_ARGS+=(--buildspec-override "$(cat "$BUILDSPEC_PATH")")
fi

echo "Starting CodeBuild ${PROJECT_NAME}: commit ${SHORT_SHA}, tags ${IMAGE_TAG} and git-${SHORT_SHA}"
BUILD_ID=$(aws codebuild start-build "${START_ARGS[@]}" --query 'build.id' --output text)
echo "Build ${BUILD_ID}"
echo "Logs: CloudWatch group /aws/codebuild/${PROJECT_NAME}"

trap 'echo; echo "Stopped watching. The build keeps running; stop it with: aws codebuild stop-build --id ${BUILD_ID}"; exit 130' INT

STARTED=$SECONDS
while true; do
  STATE=$(aws codebuild batch-get-builds --ids "$BUILD_ID" \
    --query 'builds[0].[buildStatus, currentPhase]' --output text)
  read -r STATUS PHASE <<<"$STATE"
  ELAPSED=$((SECONDS - STARTED))
  printf '  [%02d:%02d] %s\n' $((ELAPSED / 60)) $((ELAPSED % 60)) "$PHASE"
  if [ "$STATUS" != "IN_PROGRESS" ]; then
    break
  fi
  sleep "$POLL_SECONDS"
done
trap - INT

if [ "$STATUS" = "SUCCEEDED" ]; then
  ACCOUNT_ID=$(aws sts get-caller-identity --query Account --output text)
  URI="${ACCOUNT_ID}.dkr.ecr.${AWS_REGION}.amazonaws.com/${ECR_REPO}"
  DIGEST=$(aws ecr describe-images --repository-name "$ECR_REPO" \
    --image-ids "imageTag=git-${SHORT_SHA}" \
    --query 'imageDetails[0].imageDigest' --output text)
  echo
  echo "Build succeeded."
  echo "  image:  ${URI}:git-${SHORT_SHA}"
  echo "  also:   ${URI}:${IMAGE_TAG}"
  echo "  digest: ${DIGEST}"
  if [ "$IMAGE_TAG" = "latest" ]; then
    echo "Next: bash docker/email_parsing/5_update_func.sh"
  fi
  exit 0
fi

echo
echo "Build ended with status ${STATUS}."
LOGS=$(aws codebuild batch-get-builds --ids "$BUILD_ID" \
  --query 'builds[0].logs.[groupName, streamName]' --output text)
read -r LOG_GROUP LOG_STREAM <<<"$LOGS"
if [ "$LOG_GROUP" != "None" ] && [ "$LOG_STREAM" != "None" ]; then
  echo "Last ${LOG_LINES} log lines (${LOG_GROUP} / ${LOG_STREAM}):"
  aws logs get-log-events --log-group-name "$LOG_GROUP" \
    --log-stream-name "$LOG_STREAM" --no-start-from-head --limit "$LOG_LINES" \
    --output json | jq -j '.events[].message | select(test("\\S"))'
else
  echo "No CloudWatch log stream was recorded for this build."
fi
exit 1
