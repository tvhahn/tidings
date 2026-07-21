#!/usr/bin/env bash
# Prove the PII gate pipeline is live end-to-end, not silently disarmed.
#
# Two things can turn the gate green while it scans for nothing: an absent/empty
# secret (no .pii-patterns file) or a malformed/neutered alphabet. This script:
#   1. runs the linter (compile + empty-match + duplicate + comment-trap +
#      min-count checks) over the resolved patterns file;
#   2. runs a live canary through the real scripts/pii/audit_oss_release.py and
#      asserts the canary is CAUGHT — if it isn't, the alphabet is not actually
#      scanning for anything and the gate is disarmed.
#
# Fork-safe: with no patterns file (public forks have no secret) it skips green.
#
# The canary literal is ASSEMBLED AT RUNTIME by concatenation and never appears
# whole at rest in this repo — a matching literal in a tracked file would itself
# be flagged by the very pattern this test relies on.
set -euo pipefail

script_dir="$(cd "$(dirname "${BASH_SOURCE[0]}")" && pwd)"
repo_root="$(dirname "$(dirname "$script_dir")")"

patterns="$repo_root/.pii-patterns"
min_count=120

while [ "$#" -gt 0 ]; do
  case "$1" in
    --patterns)
      patterns="$2"
      shift 2
      ;;
    --min-count)
      min_count="$2"
      shift 2
      ;;
    *)
      echo "usage: check_pii_gate_armed.sh [--patterns PATH] [--min-count N]" >&2
      exit 2
      ;;
  esac
done

if [ ! -f "$patterns" ]; then
  echo "pii-gate: not armed — no patterns file; self-test skipped"
  exit 0
fi

python3 "$repo_root/scripts/pii/lint_pii_patterns.py" --patterns "$patterns" --min-count "$min_count"

# Assemble the canary at runtime — the joined literal must never sit in the tree.
canary="TIDINGS-PII-"
canary="${canary}CANARY"

tmpdir="$(mktemp -d)"
trap 'rm -rf "$tmpdir"' EXIT
printf '%s\n' "$canary" > "$tmpdir/canary.txt"

set +e
python3 "$repo_root/scripts/pii/audit_oss_release.py" --target "$tmpdir" --patterns "$patterns"
audit_code=$?
set -e

if [ "$audit_code" -eq 1 ]; then
  echo "pii-gate: armed — canary caught, continue"
  exit 0
fi

echo "pii-gate: SELF-TEST FAILED — canary not caught (audit exit ${audit_code}); the gate is scanning for nothing"
exit 1
