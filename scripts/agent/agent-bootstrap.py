#!/usr/bin/env python3
"""Companion script for `.claude/skills/headless-backend-bootstrap/SKILL.md`.

Three subcommands the skill body refers to:

- `--detect`   Print `get_config_with_features()` from
               `src/finance/app_config.py` as JSON. Source of truth for
               "which providers are active" — never duplicate this in
               prompt logic.
- `--token`    Mint (or re-print) the byo-ui-bootstrap bearer token via
               `make agent-token LABEL=byo-ui-bootstrap`. Idempotent —
               if a token with that label already exists, prints a
               note and does nothing unless `--force` is also passed.
               Skipped when `--no-auth` is passed.
- `--snippets` Print the consumer snippets (curl, optional Claude
               Desktop MCP config when `src/mcp_server/` exists, Python
               httpx).

Exit codes:
  0  success
  1  environment error (data/ not writable, make-target failed, etc.)
  2  user-input error (bad flag combinations)
"""

from __future__ import annotations

import argparse
import json
import subprocess
import sys
from pathlib import Path

BOOTSTRAP_LABEL = "byo-ui-bootstrap"
REPO_ROOT = Path(__file__).resolve().parents[2]


def cmd_detect(_: argparse.Namespace) -> int:
    from src.finance.app_config import get_config_with_features

    print(json.dumps(get_config_with_features(), indent=2))
    return 0


def cmd_token(args: argparse.Namespace) -> int:
    if args.no_auth:
        print(
            "--no-auth: skipping token generation. The API will be unauthenticated.",
            file=sys.stderr,
        )
        print(
            "  Fine for localhost; never bind 0.0.0.0 in this state.",
            file=sys.stderr,
        )
        return 0

    from src.finance import agent_tokens

    existing = [t for t in agent_tokens.list_tokens() if t["label"] == BOOTSTRAP_LABEL]
    if existing and not args.force:
        print(
            f"Token labelled '{BOOTSTRAP_LABEL}' already exists (id={existing[0]['id']}).",
            file=sys.stderr,
        )
        print(
            "Pass --force to issue a fresh one (the old hash stays valid until you `make agent-token-revoke`).",
            file=sys.stderr,
        )
        return 0

    # Defer to the Makefile target so the persistence path stays uniform.
    result = subprocess.run(
        ["make", "agent-token", f"LABEL={BOOTSTRAP_LABEL}"],
        cwd=str(REPO_ROOT),
        capture_output=True,
        text=True,
        check=False,
    )
    sys.stdout.write(result.stdout)
    sys.stderr.write(result.stderr)
    return 0 if result.returncode == 0 else 1


def cmd_snippets(_args: argparse.Namespace) -> int:
    mcp_present = (REPO_ROOT / "src" / "mcp_server").is_dir()

    print("Snippet A — curl with bearer auth")
    print()
    print("```bash")
    print('curl -fsS \\')
    print('  -H "Authorization: Bearer $FINANCE_API_TOKEN" \\')
    print('  "http://localhost:8000/api/v1/summary?month=$(date +%Y-%m)"')
    print("```")
    print()

    print("Snippet B — Claude Desktop MCP config")
    print()
    if mcp_present:
        print("```json")
        print("{")
        print('  "mcpServers": {')
        print('    "finance": {')
        print('      "command": "uvx",')
        print('      "args": ["finance-mcp"],')
        print('      "env": {')
        print('        "FINANCE_API_URL": "http://localhost:8000",')
        print('        "FINANCE_API_TOKEN": "fin_…"')
        print("      }")
        print("    }")
        print("  }")
        print("}")
        print("```")
    else:
        print(
            "MCP server entry-point not present yet (Tier 3 deferred). "
            "Use Snippet A or C until then; any HTTP-tool-using agent "
            "(Claude Desktop custom connectors, n8n, ChatGPT actions) can "
            "consume the bearer-auth REST surface directly."
        )
    print()

    print("Snippet C — Python httpx example")
    print()
    print("```python")
    print("import httpx, os")
    print('BASE = "http://localhost:8000/api/v1"')
    print("HEADERS = {'Authorization': f'Bearer {os.environ[\"FINANCE_API_TOKEN\"]}'}")
    print('r = httpx.get(f"{BASE}/summary", headers=HEADERS, params={"month": "2026-04"})')
    print("r.raise_for_status()")
    print("print(r.json())")
    print("```")
    return 0


def build_parser() -> argparse.ArgumentParser:
    parser = argparse.ArgumentParser(
        prog="agent-bootstrap",
        description="Companion script for the headless-backend-bootstrap skill.",
    )
    parser.add_argument(
        "--no-auth",
        action="store_true",
        help="skip token generation (--token becomes a no-op)",
    )
    parser.add_argument(
        "--force",
        action="store_true",
        help="re-issue token even if one with the bootstrap label exists",
    )

    mode = parser.add_mutually_exclusive_group(required=True)
    mode.add_argument("--detect", action="store_true", help="print config + features as JSON")
    mode.add_argument("--token", action="store_true", help="mint or re-use the bootstrap bearer token")
    mode.add_argument("--snippets", action="store_true", help="print consumer snippets")
    return parser


def main(argv: list[str] | None = None) -> int:
    args = build_parser().parse_args(argv)
    if args.detect:
        return cmd_detect(args)
    if args.token:
        return cmd_token(args)
    if args.snippets:
        return cmd_snippets(args)
    return 2


if __name__ == "__main__":
    raise SystemExit(main())
