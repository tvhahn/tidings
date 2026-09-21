#!/bin/bash
# Roll the freshly pushed :latest image onto both Lambdas that share it
# (email-parser and monthly-summary — same image, different entry points).
#
# Each update is followed by `wait function-updated` so the next command
# (and anything you run after this script, e.g. 6_invoke_func.sh) never
# races an in-flight code deploy. The resolved image digests printed at the
# end are how you confirm both functions actually picked up the new build —
# :latest is a moving tag, the digest is not.

set -euo pipefail

ACCOUNT_ID=$(aws sts get-caller-identity --query Account --output text)
AWS_REGION="${AWS_REGION:-us-west-2}"
IMAGE_URI="${ACCOUNT_ID}.dkr.ecr.${AWS_REGION}.amazonaws.com/email-parsing:latest"

FUNCTIONS=(email-parser monthly-summary)

for FN in "${FUNCTIONS[@]}"; do
  echo "Updating ${FN} -> ${IMAGE_URI}"
  # --query keeps the default multi-page JSON dump out of the terminal.
  aws lambda update-function-code \
    --function-name "$FN" \
    --image-uri "$IMAGE_URI" \
    --query 'LastUpdateStatus' \
    --output text
  echo "  waiting for ${FN} to finish updating..."
  aws lambda wait function-updated --function-name "$FN"
done

echo
echo "Resolved image digests:"
for FN in "${FUNCTIONS[@]}"; do
  RESOLVED=$(aws lambda get-function \
    --function-name "$FN" \
    --query 'Code.ResolvedImageUri' \
    --output text)
  echo "  ${FN}: ${RESOLVED}"
done
