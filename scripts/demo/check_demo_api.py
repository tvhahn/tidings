#!/usr/bin/env python3
"""Structural gate for the hosted demo API artifacts (run in CI by demo-smoke).

Asserts the invariants that keep the three committed artifacts under
``frontend/public/demo-api/`` mutually consistent and true to the demo world:

1. ``manifest.json`` — parses; ``months`` matches the 11-month window; ``base`` /
   ``openapi`` / ``demo_today`` are the locked values; every ``endpoints`` key is
   already canonical; every value exists on disk under ``frontend/public/``;
   every key's path is a real ``get`` operation in the root ``openapi.json``.
2. ``openapi.json`` (demo) — ``servers`` is the locked value; every path carries
   only ``get`` / ``parameters``; its path set equals the manifest's path set.
3. ``health.json`` — carries every ``HealthResponse.required`` property, is
   ``status: "ok"`` and ``auth_required: false``, and contains no day-resolution
   date after the demo clock (2026-03-19).

Stdlib-only — CI runs it with the runner's bare ``python3``.

Usage: python3 scripts/demo/check_demo_api.py
Exits non-zero with a list of violations.
"""

import json
import re
import sys
from pathlib import Path
from urllib.parse import parse_qsl, urlencode

REPO = Path(__file__).resolve().parents[2]
PUBLIC_DIR = REPO / "frontend" / "public"
DEMO_API_DIR = PUBLIC_DIR / "demo-api"
MANIFEST = DEMO_API_DIR / "manifest.json"
DEMO_OPENAPI = DEMO_API_DIR / "openapi.json"
HEALTH = DEMO_API_DIR / "health.json"
ROOT_OPENAPI = REPO / "openapi.json"

DEMO_TODAY = "2026-03-19"
MONTHS = [
    "2025-05",
    "2025-06",
    "2025-07",
    "2025-08",
    "2025-09",
    "2025-10",
    "2025-11",
    "2025-12",
    "2026-01",
    "2026-02",
    "2026-03",
]
LOCKED_BASE = "/demo/api/v1"
LOCKED_OPENAPI = "/demo/api/openapi.json"
LOCKED_SERVERS = [{"url": "https://gettidings.com/demo"}]

_DATE_RE = re.compile(r"\b(2\d{3}-\d{2}-\d{2})\b")

errors: list[str] = []


def err(msg: str) -> None:
    errors.append(msg)


def canonicalize(url: str) -> str:
    """Mirror of the TS gateway's canonicalize (spec L4), kept trivially small."""
    path, _, query = url.partition("?")
    if len(path) > 1:
        path = path.rstrip("/") or "/"
    if not query:
        return path
    return path + "?" + urlencode(sorted(parse_qsl(query, keep_blank_values=True)))


def check_manifest(manifest: dict, root: dict) -> None:
    if manifest.get("months") != MONTHS:
        err(f"manifest.months {manifest.get('months')!r} != the 11-month window")
    if manifest.get("base") != LOCKED_BASE:
        err(f"manifest.base {manifest.get('base')!r} != {LOCKED_BASE!r}")
    if manifest.get("openapi") != LOCKED_OPENAPI:
        err(f"manifest.openapi {manifest.get('openapi')!r} != {LOCKED_OPENAPI!r}")
    if manifest.get("demo_today") != DEMO_TODAY:
        err(f"manifest.demo_today {manifest.get('demo_today')!r} != {DEMO_TODAY!r}")

    root_paths = root.get("paths", {})
    for key, value in manifest.get("endpoints", {}).items():
        if canonicalize(key) != key:
            err(f"manifest endpoint key not canonical: {key!r} (want {canonicalize(key)!r})")
        asset = PUBLIC_DIR / value.lstrip("/")
        if not asset.is_file():
            err(f"manifest endpoint value has no file: {value!r}")
        api_path = "/api/v1" + key.split("?")[0]
        op = root_paths.get(api_path)
        if op is None or "get" not in op:
            err(f"manifest key {key!r} → {api_path!r} is not a GET op in openapi.json")


def check_demo_openapi(manifest: dict, demo: dict) -> None:
    if demo.get("servers") != LOCKED_SERVERS:
        err(f"demo openapi servers {demo.get('servers')!r} != {LOCKED_SERVERS!r}")

    demo_paths = demo.get("paths", {})
    for path, op in demo_paths.items():
        extra = set(op) - {"get", "parameters"}
        if extra:
            err(f"demo openapi path {path!r} carries unexpected keys: {sorted(extra)}")
        if "get" not in op:
            err(f"demo openapi path {path!r} has no get operation")

    manifest_paths = {"/api/v1" + key.split("?")[0] for key in manifest.get("endpoints", {})}
    if set(demo_paths) != manifest_paths:
        only_demo = sorted(set(demo_paths) - manifest_paths)
        only_manifest = sorted(manifest_paths - set(demo_paths))
        if only_demo:
            err(f"demo openapi has paths absent from manifest: {only_demo}")
        if only_manifest:
            err(f"manifest has paths absent from demo openapi: {only_manifest}")


def check_health(health: dict, root: dict) -> None:
    required = root["components"]["schemas"]["HealthResponse"]["required"]
    for prop in required:
        if prop not in health:
            err(f"health.json missing required HealthResponse property: {prop!r}")
    if health.get("status") != "ok":
        err(f"health.json status {health.get('status')!r} != 'ok'")
    if health.get("auth_required") is not False:
        err(f"health.json auth_required {health.get('auth_required')!r} != false")
    for date in _DATE_RE.findall(HEALTH.read_text()):
        if date > DEMO_TODAY:
            err(f"health.json contains a date after the demo clock: {date}")


def main() -> int:
    for f in (MANIFEST, DEMO_OPENAPI, HEALTH, ROOT_OPENAPI):
        if not f.is_file():
            print(f"check_demo_api: missing artifact {f}", file=sys.stderr)
            return 2

    manifest = json.loads(MANIFEST.read_text())
    demo = json.loads(DEMO_OPENAPI.read_text())
    health = json.loads(HEALTH.read_text())
    root = json.loads(ROOT_OPENAPI.read_text())

    check_manifest(manifest, root)
    check_demo_openapi(manifest, demo)
    check_health(health, root)

    if errors:
        print(f"check_demo_api: {len(errors)} violation(s)", file=sys.stderr)
        for e in errors[:50]:
            print(f"  - {e}", file=sys.stderr)
        if len(errors) > 50:
            print(f"  … and {len(errors) - 50} more", file=sys.stderr)
        return 1

    print(
        f"check_demo_api: OK — {len(manifest['endpoints'])} endpoints, "
        f"{len(demo['paths'])} schema paths, health inside the demo world"
    )
    return 0


if __name__ == "__main__":
    sys.exit(main())
