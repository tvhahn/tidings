#!/bin/bash
# Set (or clear) the handler's personal-config environment variables on a
# Lambda function WITHOUT disturbing any other environment variable.
#
# Why this script exists: `aws lambda update-function-configuration
# --environment` REPLACES the whole variable map, and on 2026-04-08 a hand-run
# invocation of exactly that flag silently wiped this function's variables.
# This script reads the live map first, merges only the keys it owns, refuses
# to write if any pre-existing key would change or disappear (exit 2), and pins
# the write to the RevisionId it read (a compare-and-swap, so a concurrent
# change fails the call instead of being overwritten).
#
# The Lambda image ships `src/` and the handlers only — there is no `data/`
# directory, so these variables are the personalization channel that a
# self-hosted install gets from `data/`. All of them are OPTIONAL: unset, the
# handlers use the bundled defaults baked into the code.
#
# Owned keys (nothing else may be set through this script):
#   CATEGORIZATION_MODEL              categorizer model id
#   CATEGORIZATION_REASONING_EFFORT   none | low | medium | high | xhigh
#                                     (`minimal` is NOT accepted — the GPT-5.6
#                                     API rejects it)
#   NOTIFICATION_BLOCKED_COMPANIES    SMS suppression list; a JSON array of
#                                     strings or a comma-separated list
#   USER_MAPPINGS                     comma-separated `forwarded_to=user_id`
#                                     pairs
#
# The last two hold personal data (merchant names, forwarding addresses). This
# script never prints their values — not in the plan, not in the dry run, not
# in the AWS response — and `--set-file` keeps them out of the shell history
# and the process list too. Prefer `--set-file` for those two.
#
# Usage:
#   11_set_function_env.sh [--function NAME] [--set KEY=VALUE]
#                          [--set-file KEY=PATH] [--unset KEY] [--dry-run]
#
#   --function NAME     Lambda to modify (default: email-parser)
#   --set KEY=VALUE     set an owned key to VALUE (repeatable)
#   --set-file KEY=PATH set an owned key to the contents of PATH, with one
#                       trailing newline stripped (repeatable)
#   --unset KEY         remove an owned key (repeatable)
#   --dry-run           show the merge and exit without writing
#   -h, --help          this text
#
# Examples:
#   # Rollback lever: pin the previous model
#   ./11_set_function_env.sh --set CATEGORIZATION_MODEL=gpt-5.4-nano
#
#   # Full rollback: drop both overrides, back to the code defaults
#   ./11_set_function_env.sh --unset CATEGORIZATION_MODEL \
#                            --unset CATEGORIZATION_REASONING_EFFORT
#
#   # Restore the SMS suppression list from a local file (value never printed)
#   ./11_set_function_env.sh --set-file NOTIFICATION_BLOCKED_COMPANIES=blocked.json
#
#   # Point the monthly summary at the right DynamoDB partitions
#   ./11_set_function_env.sh --function monthly-summary \
#                            --set-file USER_MAPPINGS=mappings.txt
#
# Exit codes: 0 ok / 1 usage or AWS error / 2 the merge would have altered a
# variable this script does not own (nothing was written).

set -euo pipefail

MODEL_KEY="CATEGORIZATION_MODEL"
EFFORT_KEY="CATEGORIZATION_REASONING_EFFORT"
BLOCKED_KEY="NOTIFICATION_BLOCKED_COMPANIES"
MAPPINGS_KEY="USER_MAPPINGS"

# Every key this script is allowed to touch. A key outside this list is a usage
# error — the whole point is that the rest of the map is untouchable.
OWNED_KEYS=("$MODEL_KEY" "$EFFORT_KEY" "$BLOCKED_KEY" "$MAPPINGS_KEY")

# Keys whose values are safe to echo. The other owned keys carry personal data
# and are reported as a character count only.
PRINTABLE_KEYS=("$MODEL_KEY" "$EFFORT_KEY")

VALID_EFFORTS=(none low medium high xhigh)

usage() {
  cat <<'EOF'
Set or clear the handler's environment overrides on a Lambda, merging into the
function's existing environment instead of replacing it.

Usage:
  11_set_function_env.sh [--function NAME] [--set KEY=VALUE]
                         [--set-file KEY=PATH] [--unset KEY] [--dry-run]

  --function NAME     Lambda to modify (default: email-parser)
  --set KEY=VALUE     set an owned key to VALUE (repeatable)
  --set-file KEY=PATH set an owned key to the contents of PATH, with one
                      trailing newline stripped (repeatable)
  --unset KEY         remove an owned key (repeatable)
  --dry-run           show the merge and exit without writing
  -h, --help          this text

Owned keys (anything else is rejected):
  CATEGORIZATION_MODEL              categorizer model id
  CATEGORIZATION_REASONING_EFFORT   none | low | medium | high | xhigh
                                    ('minimal' is NOT accepted - the GPT-5.6
                                    API rejects it)
  NOTIFICATION_BLOCKED_COMPANIES    SMS suppression list; a JSON array of
                                    strings or a comma-separated list
  USER_MAPPINGS                     comma-separated forwarded_to=user_id pairs

NOTIFICATION_BLOCKED_COMPANIES and USER_MAPPINGS hold personal data: their
values are never printed, and --set-file also keeps them out of the shell
history and the process list.

At least one of --set / --set-file / --unset is required. The same key may not
be both set and unset, nor set twice.

Examples:
  # Rollback lever: pin the previous model
  ./11_set_function_env.sh --set CATEGORIZATION_MODEL=gpt-5.4-nano

  # Full rollback: drop both overrides, back to the code defaults
  ./11_set_function_env.sh --unset CATEGORIZATION_MODEL --unset CATEGORIZATION_REASONING_EFFORT

  # Restore the SMS suppression list from a local file (value never printed)
  ./11_set_function_env.sh --set-file NOTIFICATION_BLOCKED_COMPANIES=blocked.json

  # Point the monthly summary at the right DynamoDB partitions
  ./11_set_function_env.sh --function monthly-summary --set-file USER_MAPPINGS=mappings.txt

Exit codes: 0 ok / 1 usage or AWS error / 2 the merge would have altered a
variable this script does not own (nothing was written).
EOF
}

die() {
  echo "error: $*" >&2
  exit 1
}

# Is $1 one of the keys this script owns?
is_owned() {
  local candidate="$1" key
  for key in "${OWNED_KEYS[@]}"; do
    [[ "$candidate" == "$key" ]] && return 0
  done
  return 1
}

# May $1's value be echoed? (False for the personal keys.)
is_printable() {
  local candidate="$1" key
  for key in "${PRINTABLE_KEYS[@]}"; do
    [[ "$candidate" == "$key" ]] && return 0
  done
  return 1
}

# Is $1 already present in the live (pre-merge) variable map? Key names only.
has_key() {
  printf '%s' "$BEFORE" | jq -e --arg k "$1" 'has($k)' >/dev/null
}

# Is $1 scheduled to be set / unset by this invocation?
is_scheduled_set() {
  local candidate="$1" key
  for key in "${SET_ORDER[@]:-}"; do
    [[ "$candidate" == "$key" ]] && return 0
  done
  return 1
}

is_scheduled_unset() {
  local candidate="$1" key
  for key in "${UNSET_ORDER[@]:-}"; do
    [[ "$candidate" == "$key" ]] && return 0
  done
  return 1
}

for cmd in aws jq; do
  command -v "$cmd" >/dev/null 2>&1 \
    || die "'${cmd}' is required but not on PATH. Install it and retry."
done

FUNCTION_NAME="email-parser"
DRY_RUN=0

# Parallel bookkeeping for the requested changes. SET_SOURCE[key] is either
# "inline" (value in SET_VALUE[key]) or "file" (path in SET_FILE[key]); the
# inline value never reaches jq's argv for a file-sourced key.
SET_ORDER=()
UNSET_ORDER=()
declare -A SET_SOURCE=()
declare -A SET_VALUE=()
declare -A SET_FILE=()

record_set() {
  local key="$1"
  is_owned "$key" \
    || die "'${key}' is not a key this script owns. Owned keys: ${OWNED_KEYS[*]}"
  if [[ -n "${SET_SOURCE[$key]:-}" ]]; then
    die "${key} was given more than once"
  fi
  SET_ORDER+=("$key")
}

while [[ $# -gt 0 ]]; do
  case "$1" in
    --function)
      [[ $# -ge 2 ]] || die "--function needs a value"
      FUNCTION_NAME="$2"
      shift 2
      ;;
    --set)
      [[ $# -ge 2 ]] || die "--set needs a KEY=VALUE argument"
      [[ "$2" == *=* ]] || die "--set expects KEY=VALUE, got '$2'"
      SET_KEY="${2%%=*}"
      SET_VAL="${2#*=}"
      record_set "$SET_KEY"
      [[ -n "$SET_VAL" ]] \
        || die "--set ${SET_KEY}= has an empty value (use --unset ${SET_KEY} to remove it)"
      SET_SOURCE["$SET_KEY"]="inline"
      SET_VALUE["$SET_KEY"]="$SET_VAL"
      shift 2
      ;;
    --set-file)
      [[ $# -ge 2 ]] || die "--set-file needs a KEY=PATH argument"
      [[ "$2" == *=* ]] || die "--set-file expects KEY=PATH, got '$2'"
      SET_KEY="${2%%=*}"
      SET_PATH="${2#*=}"
      record_set "$SET_KEY"
      [[ -n "$SET_PATH" ]] || die "--set-file ${SET_KEY}= has an empty path"
      [[ -r "$SET_PATH" ]] || die "--set-file ${SET_KEY}: cannot read '${SET_PATH}'"
      [[ -s "$SET_PATH" ]] \
        || die "--set-file ${SET_KEY}: '${SET_PATH}' is empty (use --unset ${SET_KEY} to remove it)"
      SET_SOURCE["$SET_KEY"]="file"
      SET_FILE["$SET_KEY"]="$SET_PATH"
      shift 2
      ;;
    --unset)
      [[ $# -ge 2 ]] || die "--unset needs a KEY argument"
      UNSET_KEY="$2"
      is_owned "$UNSET_KEY" \
        || die "'${UNSET_KEY}' is not a key this script owns. Owned keys: ${OWNED_KEYS[*]}"
      if is_scheduled_unset "$UNSET_KEY"; then
        die "${UNSET_KEY} was given more than once"
      fi
      UNSET_ORDER+=("$UNSET_KEY")
      shift 2
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

if (( ${#SET_ORDER[@]} + ${#UNSET_ORDER[@]} == 0 )); then
  echo "error: nothing to do — pass at least one of --set / --set-file / --unset." >&2
  echo >&2
  usage >&2
  exit 1
fi

for key in "${UNSET_ORDER[@]}"; do
  if is_scheduled_set "$key"; then
    die "${key} cannot be both set and unset in one invocation"
  fi
done

# Reject an obviously bad effort before talking to AWS at all. A file-sourced
# effort is validated after the merge instead (same check, same message).
validate_effort() {
  local value="$1" level
  for level in "${VALID_EFFORTS[@]}"; do
    [[ "$value" == "$level" ]] && return 0
  done
  die "invalid ${EFFORT_KEY} '${value}'. Valid levels: ${VALID_EFFORTS[*]} (note: 'minimal' is rejected by the GPT-5.6 API)"
}

if [[ "${SET_SOURCE[$EFFORT_KEY]:-}" == "inline" ]]; then
  validate_effort "${SET_VALUE[$EFFORT_KEY]}"
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

# --- Merge (only the keys this script owns) -------------------------------
#
# Values reach jq through --arg / --rawfile, never interpolated into the
# program text. A file-sourced value is read by jq itself (--rawfile), so it
# stays out of this script's argv, its variables and the process list; jq
# strips the single trailing newline a text editor leaves behind.

AFTER="$BEFORE"
for key in "${SET_ORDER[@]}"; do
  if [[ "${SET_SOURCE[$key]}" == "file" ]]; then
    AFTER=$(printf '%s' "$AFTER" | jq -c \
      --arg k "$key" \
      --rawfile v "${SET_FILE[$key]}" \
      '.[$k] = ($v | rtrimstr("\n"))')
  else
    AFTER=$(printf '%s' "$AFTER" | jq -c \
      --arg k "$key" \
      --arg v "${SET_VALUE[$key]}" \
      '.[$k] = $v')
  fi
done
for key in "${UNSET_ORDER[@]}"; do
  AFTER=$(printf '%s' "$AFTER" | jq -c --arg k "$key" 'del(.[$k])')
done

# A file can also arrive as a lone newline, or as a value that trims to
# nothing — treat that like an empty --set rather than writing a blank var.
for key in "${SET_ORDER[@]}"; do
  RESULT_LEN=$(printf '%s' "$AFTER" | jq -r --arg k "$key" '.[$k] | length')
  (( RESULT_LEN > 0 )) \
    || die "${key} resolved to an empty value (use --unset ${key} to remove it)"
done

# Effort stays validated whichever way it arrives — the value is not personal,
# so it can be read back out of the merged map and named in the error.
if is_scheduled_set "$EFFORT_KEY"; then
  validate_effort "$(printf '%s' "$AFTER" | jq -r --arg k "$EFFORT_KEY" '.[$k]')"
fi

# --- Guard: every other pre-existing key must survive byte-identical ------

OWNED_JSON=$(printf '%s\n' "${OWNED_KEYS[@]}" | jq -R . | jq -sc .)

CLOBBERED=$(jq -rn \
  --argjson before "$BEFORE" \
  --argjson after "$AFTER" \
  --argjson owned "$OWNED_JSON" \
  '
    $before
    | to_entries
    | map(select(.key as $k | ($owned | index($k)) | not))
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

# --- Report the plan (key names only for the personal keys) ---------------

BEFORE_KEYS=$(printf '%s' "$BEFORE" | jq -r 'keys_unsorted | join(", ") | if . == "" then "(none)" else . end')
AFTER_KEYS=$(printf '%s' "$AFTER" | jq -r 'keys_unsorted | join(", ") | if . == "" then "(none)" else . end')

echo "Function:    ${FUNCTION_NAME}"
echo "Revision:    ${REVISION_ID}"
echo "Keys before: ${BEFORE_KEYS}"
echo "Keys after:  ${AFTER_KEYS}"
echo "Changes:"
for key in "${SET_ORDER[@]}"; do
  if is_printable "$key"; then
    echo "  set       ${key}=$(printf '%s' "$AFTER" | jq -r --arg k "$key" '.[$k]')"
  else
    # Personal value: length only, never the text — dry run included.
    echo "  set       ${key} ($(printf '%s' "$AFTER" | jq -r --arg k "$key" '.[$k] | length') chars)"
  fi
done
for key in "${UNSET_ORDER[@]}"; do
  if has_key "$key"; then
    echo "  unset     ${key}"
  else
    echo "  unset     ${key} (was not set — no-op)"
  fi
done
for key in "${OWNED_KEYS[@]}"; do
  if is_scheduled_set "$key" || is_scheduled_unset "$key"; then
    continue
  fi
  if has_key "$key"; then
    echo "  unchanged ${key}"
  else
    echo "  not set   ${key} (handler uses the code default)"
  fi
done
UNTOUCHED=$(printf '%s' "$BEFORE" | jq -r --argjson owned "$OWNED_JSON" \
  'keys_unsorted | map(select(. as $k | ($owned | index($k)) | not)) | join(", ")')
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
