#!/bin/bash
# Set (or clear) the categorization model / reasoning-effort overrides on a
# Lambda function WITHOUT disturbing any other environment variable.
#
# Why this script exists: `aws lambda update-function-configuration
# --environment` REPLACES the whole variable map, and on 2026-04-08 a hand-run
# invocation of exactly that flag silently wiped the function's other
# variables. This script reads the live map first, merges only
# CATEGORIZATION_MODEL / CATEGORIZATION_REASONING_EFFORT into it, refuses to
# write if any pre-existing key would change or disappear (exit 2), and pins
# the write to the RevisionId it read (a compare-and-swap, so a concurrent
# change fails the call instead of being overwritten).
#
# The two variables are OPTIONAL overrides — with neither set, the handler
# uses the model and effort baked into the code.
#
# Usage:
#   11_set_categorization_model.sh [--function NAME] [--model ID]
#                                  [--effort LEVEL] [--unset-model]
#                                  [--unset-effort] [--dry-run]
#
#   --function NAME   Lambda to modify (default: email-parser)
#   --model ID        value for CATEGORIZATION_MODEL
#   --effort LEVEL    value for CATEGORIZATION_REASONING_EFFORT; one of
#                     none | low | medium | high | xhigh
#                     (`minimal` is NOT accepted — the GPT-5.6 API rejects it)
#   --unset-model     remove CATEGORIZATION_MODEL
#   --unset-effort    remove CATEGORIZATION_REASONING_EFFORT
#   --dry-run         show the merge (key names only) and exit without writing
#   -h, --help        this text
#
# Examples:
#   # Raise reasoning effort on the parser
#   ./11_set_categorization_model.sh --effort high
#
#   # Preview a model + effort change before committing to it
#   ./11_set_categorization_model.sh --model gpt-5.6-luna --effort medium --dry-run
#
#   # Rollback lever: pin the previous model
#   ./11_set_categorization_model.sh --model gpt-5.4-nano
#
#   # Full rollback: drop both overrides, back to the code defaults
#   ./11_set_categorization_model.sh --unset-model --unset-effort
#
# Exit codes: 0 ok / 1 usage or AWS error / 2 the merge would have altered a
# variable this script does not own (nothing was written).

set -euo pipefail

MODEL_KEY="CATEGORIZATION_MODEL"
EFFORT_KEY="CATEGORIZATION_REASONING_EFFORT"
VALID_EFFORTS=(none low medium high xhigh)

usage() {
  cat <<'EOF'
Set or clear the categorization overrides on a Lambda, merging into the
function's existing environment instead of replacing it.

Usage:
  11_set_categorization_model.sh [--function NAME] [--model ID]
                                 [--effort LEVEL] [--unset-model]
                                 [--unset-effort] [--dry-run]

  --function NAME   Lambda to modify (default: email-parser)
  --model ID        value for CATEGORIZATION_MODEL
  --effort LEVEL    value for CATEGORIZATION_REASONING_EFFORT; one of
                    none | low | medium | high | xhigh
                    ('minimal' is NOT accepted - the GPT-5.6 API rejects it)
  --unset-model     remove CATEGORIZATION_MODEL
  --unset-effort    remove CATEGORIZATION_REASONING_EFFORT
  --dry-run         show the merge (key names only) and exit without writing
  -h, --help        this text

At least one of --model / --effort / --unset-model / --unset-effort is
required. --model and --unset-model cannot be combined (same for effort).

Examples:
  # Raise reasoning effort on the parser
  ./11_set_categorization_model.sh --effort high

  # Preview a model + effort change before committing to it
  ./11_set_categorization_model.sh --model gpt-5.6-luna --effort medium --dry-run

  # Rollback lever: pin the previous model
  ./11_set_categorization_model.sh --model gpt-5.4-nano

  # Full rollback: drop both overrides, back to the code defaults
  ./11_set_categorization_model.sh --unset-model --unset-effort

Exit codes: 0 ok / 1 usage or AWS error / 2 the merge would have altered a
variable this script does not own (nothing was written).
EOF
}

die() {
  echo "error: $*" >&2
  exit 1
}

# Is $1 a key of the live (pre-merge) variable map? Key names only.
has_key() {
  printf '%s' "$BEFORE" | jq -e --arg k "$1" 'has($k)' >/dev/null
}

for cmd in aws jq; do
  command -v "$cmd" >/dev/null 2>&1 \
    || die "'${cmd}' is required but not on PATH. Install it and retry."
done

FUNCTION_NAME="email-parser"
MODEL=""
EFFORT=""
SET_MODEL=0
SET_EFFORT=0
UNSET_MODEL=0
UNSET_EFFORT=0
DRY_RUN=0

while [[ $# -gt 0 ]]; do
  case "$1" in
    --function)
      [[ $# -ge 2 ]] || die "--function needs a value"
      FUNCTION_NAME="$2"
      shift 2
      ;;
    --model)
      [[ $# -ge 2 ]] || die "--model needs a value"
      MODEL="$2"
      SET_MODEL=1
      shift 2
      ;;
    --effort)
      [[ $# -ge 2 ]] || die "--effort needs a value"
      EFFORT="$2"
      SET_EFFORT=1
      shift 2
      ;;
    --unset-model)
      UNSET_MODEL=1
      shift
      ;;
    --unset-effort)
      UNSET_EFFORT=1
      shift
      ;;
    --dry-run)
      DRY_RUN=1
      shift
      ;;
    -h|--help)
      usage
      exit 0
      ;;
    *)
      echo "error: unknown argument: $1" >&2
      echo >&2
      usage >&2
      exit 1
      ;;
  esac
done

[[ -n "$FUNCTION_NAME" ]] || die "--function may not be empty"

if (( SET_MODEL + SET_EFFORT + UNSET_MODEL + UNSET_EFFORT == 0 )); then
  echo "error: nothing to do — pass at least one of --model / --effort /" >&2
  echo "       --unset-model / --unset-effort." >&2
  echo >&2
  usage >&2
  exit 1
fi

if (( SET_MODEL && UNSET_MODEL )); then
  die "--model and --unset-model are mutually exclusive"
fi
if (( SET_EFFORT && UNSET_EFFORT )); then
  die "--effort and --unset-effort are mutually exclusive"
fi

if (( SET_MODEL )) && [[ -z "$MODEL" ]]; then
  die "--model may not be empty (use --unset-model to remove the override)"
fi

if (( SET_EFFORT )); then
  EFFORT_OK=0
  for level in "${VALID_EFFORTS[@]}"; do
    if [[ "$EFFORT" == "$level" ]]; then
      EFFORT_OK=1
      break
    fi
  done
  if (( ! EFFORT_OK )); then
    die "invalid --effort '${EFFORT}'. Valid levels: ${VALID_EFFORTS[*]} (note: 'minimal' is rejected by the GPT-5.6 API)"
  fi
fi

# --- Read the live configuration in a single call -------------------------

CURRENT=$(aws lambda get-function-configuration \
  --function-name "$FUNCTION_NAME" \
  --query '{Rev:RevisionId,Vars:Environment.Variables}' \
  --output json)

REVISION_ID=$(printf '%s' "$CURRENT" | jq -r '.Rev // ""')
# A function with no environment block at all reports Vars: null.
BEFORE=$(printf '%s' "$CURRENT" | jq -c '.Vars // {}')

[[ -n "$REVISION_ID" ]] || die "could not read RevisionId for ${FUNCTION_NAME}"

# --- Merge (only the two keys this script owns) ---------------------------

AFTER=$(printf '%s' "$BEFORE" | jq -c \
  --arg mk "$MODEL_KEY" \
  --arg ek "$EFFORT_KEY" \
  --arg model "$MODEL" \
  --arg effort "$EFFORT" \
  --argjson set_model "$SET_MODEL" \
  --argjson set_effort "$SET_EFFORT" \
  --argjson unset_model "$UNSET_MODEL" \
  --argjson unset_effort "$UNSET_EFFORT" \
  '
    (if $set_model == 1 then .[$mk] = $model else . end)
    | (if $unset_model == 1 then del(.[$mk]) else . end)
    | (if $set_effort == 1 then .[$ek] = $effort else . end)
    | (if $unset_effort == 1 then del(.[$ek]) else . end)
  ')

# --- Guard: every other pre-existing key must survive byte-identical ------

CLOBBERED=$(jq -rn \
  --argjson before "$BEFORE" \
  --argjson after "$AFTER" \
  --arg mk "$MODEL_KEY" \
  --arg ek "$EFFORT_KEY" \
  '
    $before
    | to_entries
    | map(select(.key != $mk and .key != $ek))
    | map(select(
        . as $e
        | (($after | has($e.key)) | not) or ($after[$e.key] != $e.value)
      ))
    | map(.key)
    | join(", ")
  ')

if [[ -n "$CLOBBERED" ]]; then
  echo "ABORT: the merged environment would drop or change variable(s) this" >&2
  echo "       script does not own: ${CLOBBERED}" >&2
  echo "       Nothing was written to ${FUNCTION_NAME}." >&2
  exit 2
fi

# --- Report the plan (key names only — never other variables' values) -----

BEFORE_KEYS=$(printf '%s' "$BEFORE" | jq -r 'keys_unsorted | join(", ") | if . == "" then "(none)" else . end')
AFTER_KEYS=$(printf '%s' "$AFTER" | jq -r 'keys_unsorted | join(", ") | if . == "" then "(none)" else . end')

echo "Function:    ${FUNCTION_NAME}"
echo "Revision:    ${REVISION_ID}"
echo "Keys before: ${BEFORE_KEYS}"
echo "Keys after:  ${AFTER_KEYS}"
echo "Changes:"
if (( SET_MODEL )); then
  echo "  set       ${MODEL_KEY}=${MODEL}"
elif (( UNSET_MODEL )); then
  if has_key "$MODEL_KEY"; then
    echo "  unset     ${MODEL_KEY}"
  else
    echo "  unset     ${MODEL_KEY} (was not set — no-op)"
  fi
elif has_key "$MODEL_KEY"; then
  echo "  unchanged ${MODEL_KEY}"
else
  echo "  not set   ${MODEL_KEY} (handler uses the code default)"
fi
if (( SET_EFFORT )); then
  echo "  set       ${EFFORT_KEY}=${EFFORT}"
elif (( UNSET_EFFORT )); then
  if has_key "$EFFORT_KEY"; then
    echo "  unset     ${EFFORT_KEY}"
  else
    echo "  unset     ${EFFORT_KEY} (was not set — no-op)"
  fi
elif has_key "$EFFORT_KEY"; then
  echo "  unchanged ${EFFORT_KEY}"
else
  echo "  not set   ${EFFORT_KEY} (handler uses the code default)"
fi
UNTOUCHED=$(printf '%s' "$BEFORE" | jq -r --arg mk "$MODEL_KEY" --arg ek "$EFFORT_KEY" \
  'keys_unsorted | map(select(. != $mk and . != $ek)) | join(", ")')
if [[ -n "$UNTOUCHED" ]]; then
  echo "  unchanged ${UNTOUCHED}"
fi

if (( DRY_RUN )); then
  echo
  echo "Dry run — no update-function-configuration call was made."
  exit 0
fi

# --- Write ----------------------------------------------------------------

# The payload goes through a file: the `Variables={...}` shorthand is exactly
# the form that caused the 2026-04-08 clobber, and a file keeps values off the
# process list.
TMP_ENV=""
cleanup() {
  if [[ -n "$TMP_ENV" ]]; then
    rm -f "$TMP_ENV"
  fi
}
trap cleanup EXIT

TMP_ENV=$(mktemp)
chmod 600 "$TMP_ENV"
jq -n --argjson vars "$AFTER" '{Variables: $vars}' > "$TMP_ENV"

echo
echo "Updating ${FUNCTION_NAME} (compare-and-swap on revision ${REVISION_ID})..."
# --query is REQUIRED: the default response echoes every variable's value.
aws lambda update-function-configuration \
  --function-name "$FUNCTION_NAME" \
  --environment "file://${TMP_ENV}" \
  --revision-id "$REVISION_ID" \
  --query 'Environment.Variables | keys(@)' \
  --output json

aws lambda wait function-updated --function-name "$FUNCTION_NAME"
echo "Done."
