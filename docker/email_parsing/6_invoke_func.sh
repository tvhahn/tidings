#!/bin/bash
# Post-deploy boot check for the email-parser Lambda — side-effect free.
#
# What it proves: the newly deployed image boots, the handler imports, the
# OpenAI key resolves, and the categorization model / reasoning effort the
# function will actually use are the ones you expect. It reads them straight
# out of the invocation's log tail:
#
#     Categorization model=<model> reasoning_effort=<effort>
#
# Why the invoke "fails", and why that is EXPECTED: test_event.json is a
# canned S3 event pointing at the non-existent bucket `my-bucket`. The
# handler logs the categorization line during start-up and then dies on the
# S3 get_object for that fake key, so the invoke comes back with a
# FunctionError. Nothing downstream ever runs — no DynamoDB write, no SMS /
# SNS notification, and no model call is made (the key is loaded, not used).
# That is precisely what makes this safe to run against production.
#
# Exit status: 0 if the `Categorization model=` line was found (regardless of
# the expected FunctionError), 1 if it was absent — which means the function
# did not get far enough to log it, and the deploy needs a look.

set -euo pipefail

FUNCTION_NAME="email-parser"

# Resolve the payload next to this script so the check works from any cwd.
SCRIPT_DIR=$(cd -- "$(dirname -- "${BASH_SOURCE[0]}")" && pwd)
EVENT_FILE="${SCRIPT_DIR}/test_event.json"

if [[ ! -f "$EVENT_FILE" ]]; then
  echo "error: event payload not found: ${EVENT_FILE}" >&2
  exit 1
fi

RESPONSE_FILE=$(mktemp)
trap 'rm -f "$RESPONSE_FILE"' EXIT

echo "Invoking ${FUNCTION_NAME} with ${EVENT_FILE} (boot check)..."
INVOKE_RESULT=$(aws lambda invoke \
  --function-name "$FUNCTION_NAME" \
  --cli-binary-format raw-in-base64-out \
  --payload "file://${EVENT_FILE}" \
  --log-type Tail \
  --query '{Log:LogResult,Error:FunctionError}' \
  --output json \
  "$RESPONSE_FILE")

LOG_B64=$(printf '%s' "$INVOKE_RESULT" | jq -r '.Log // ""')
FUNCTION_ERROR=$(printf '%s' "$INVOKE_RESULT" | jq -r '.Error // ""')

if [[ -z "$LOG_B64" ]]; then
  echo "error: the invoke returned no log tail — cannot verify the model." >&2
  exit 1
fi

LOG_TAIL=$(printf '%s' "$LOG_B64" | base64 --decode)

# The tail carries plenty of unrelated start-up noise; show only the lines
# that matter.
MODEL_LINES=$(printf '%s\n' "$LOG_TAIL" | grep -F 'Categorization model=' || true)
REPORT_LINE=$(printf '%s\n' "$LOG_TAIL" | grep -E '^REPORT ' || true)

echo
if [[ -n "$MODEL_LINES" ]]; then
  printf '%s\n' "$MODEL_LINES"
fi
if [[ -n "$REPORT_LINE" ]]; then
  printf '%s\n' "$REPORT_LINE"
fi
echo

if [[ -z "$MODEL_LINES" ]]; then
  echo "FAIL: no 'Categorization model=' line in the log tail for ${FUNCTION_NAME}." >&2
  echo "      The function did not reach the start of the handler. Check the" >&2
  echo "      deployed image (5_update_func.sh prints the resolved digest) and" >&2
  echo "      the full CloudWatch log group /aws/lambda/${FUNCTION_NAME}." >&2
  exit 1
fi

if [[ -n "$FUNCTION_ERROR" ]]; then
  echo "OK: boot check passed. FunctionError=${FUNCTION_ERROR} is EXPECTED —"
  echo "    test_event.json points at the non-existent bucket 'my-bucket', so"
  echo "    the handler fails at the S3 read. No DB write, no SMS, no model call."
else
  echo "OK: boot check passed (no FunctionError reported)."
fi
