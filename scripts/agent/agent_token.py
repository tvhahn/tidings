"""CLI for managing agent bearer tokens.

Wraps src.finance.agent_tokens helpers so operators can issue + revoke
tokens without writing Python. Three subcommands: generate, show, revoke.

Driven by the Makefile targets `agent-token`, `agent-token-show`,
`agent-token-revoke`. See `docs/guides/agent-access.md` for end-to-end
usage (curl + Claude Desktop snippets).
"""

from __future__ import annotations

import argparse
import sys

from src.finance import agent_tokens


def _cmd_generate(args: argparse.Namespace) -> int:
    label = (args.label or "").strip()
    if not label:
        print("error: --label is required (e.g. --label 'laptop-claude')", file=sys.stderr)
        return 2
    try:
        record, raw = agent_tokens.add_token(label=label, scope=args.scope)
    except ValueError as exc:
        print(f"error: {exc}", file=sys.stderr)
        return 2
    print()
    print(f"  Token: {raw}")
    print(f"     id: {record['id']}")
    print(f"  scope: {record['scope']}")
    print(f"  label: {record['label']}")
    print()
    print("Save this token now — it will NOT be shown again.")
    print("Pass it as `Authorization: Bearer <token>` on /api/v1/* requests.")
    return 0


def _cmd_show(_args: argparse.Namespace) -> int:
    rows = agent_tokens.list_tokens()
    if not rows:
        print("(no agent tokens configured)")
        return 0
    width_id = max(len("id"), *(len(r["id"]) for r in rows))
    width_label = max(len("label"), *(len(r["label"]) for r in rows))
    width_scope = max(len("scope"), *(len(r["scope"]) for r in rows))
    header = f"{'id':<{width_id}}  {'label':<{width_label}}  {'scope':<{width_scope}}  created_at         last_used_at"
    print(header)
    print("-" * len(header))
    for r in rows:
        last_used = r["last_used_at"] or "—"
        print(
            f"{r['id']:<{width_id}}  "
            f"{r['label']:<{width_label}}  "
            f"{r['scope']:<{width_scope}}  "
            f"{r['created_at']}  "
            f"{last_used}"
        )
    return 0


def _cmd_revoke(args: argparse.Namespace) -> int:
    token_id = (args.id or "").strip()
    if not token_id:
        print("error: --id is required (run `make agent-token-show` to find it)", file=sys.stderr)
        return 2
    if agent_tokens.revoke_token(token_id):
        print(f"revoked token {token_id}")
        return 0
    print(f"error: no token with id {token_id!r}", file=sys.stderr)
    return 1


def _build_parser() -> argparse.ArgumentParser:
    parser = argparse.ArgumentParser(prog="agent_token", description=__doc__.splitlines()[0])
    sub = parser.add_subparsers(dest="cmd", required=True)

    gen = sub.add_parser("generate", help="issue a new bearer token (printed once)")
    gen.add_argument("--label", required=True, help="human-readable label, e.g. 'laptop-claude'")
    gen.add_argument(
        "--scope",
        choices=("read", "read+write"),
        default=agent_tokens.DEFAULT_SCOPE,
        help="token scope (default: read+write)",
    )
    gen.set_defaults(func=_cmd_generate)

    show = sub.add_parser("show", help="list all configured tokens (hashes only)")
    show.set_defaults(func=_cmd_show)

    revoke = sub.add_parser("revoke", help="delete a token by id")
    revoke.add_argument("--id", required=True, help="token id from `show`")
    revoke.set_defaults(func=_cmd_revoke)

    return parser


def main(argv: list[str] | None = None) -> int:
    parser = _build_parser()
    args = parser.parse_args(argv)
    return int(args.func(args))


if __name__ == "__main__":
    raise SystemExit(main())
