#!/usr/bin/env python3
"""Generate the demo OpenAPI schema served at /demo/api/openapi.json.

Filters the committed root ``openapi.json`` down to the paths the demo manifest
actually serves, keeping only the ``get`` operation and ``parameters`` per path.
``components`` is kept whole (pruning transitive ``$ref``s is complexity without
payoff). A ``servers`` entry is added so ``server + path`` resolves to
``/demo/api/v1/...``; the title is changed and a paragraph naming the fiction,
the month window, and the read-only 405 behavior is appended to the description
(spec L6).

Output is ``json.dumps(..., indent=2, sort_keys=True) + "\\n"`` so regen is
byte-stable and ``verify-demo-api`` can gate it with ``git diff --exit-code``.

Stdlib-only — CI runs it with the runner's bare ``python3``.

Usage: python3 scripts/demo/generate_demo_openapi.py
"""

import json
import sys
from pathlib import Path

REPO = Path(__file__).resolve().parents[2]
ROOT_OPENAPI = REPO / "openapi.json"
MANIFEST = REPO / "frontend" / "public" / "demo-api" / "manifest.json"
OUT_FILE = REPO / "frontend" / "public" / "demo-api" / "openapi.json"

DEMO_SERVER = "https://gettidings.com/demo"
DEMO_TITLE = "Tidings demo API (read-only)"
DEMO_DESCRIPTION_SUFFIX = (
    "\n\n**Demo:** this is a read-only snapshot of the Tidings demo journal — the "
    "fictional Mira Lin Chen household, covering 2025-05 through 2026-03. All data "
    "is invented. Any request other than GET, HEAD, or OPTIONS returns 405; "
    "self-host Tidings for a writable journal with bearer-token auth."
)


def main() -> int:
    root = json.loads(ROOT_OPENAPI.read_text())
    manifest = json.loads(MANIFEST.read_text())

    # Manifest keys are canonical URLs relative to /api/v1; the schema paths are
    # rooted at /api/v1 with the query string dropped.
    kept_paths = {"/api/v1" + key.split("?")[0] for key in manifest["endpoints"]}

    src_paths = root.get("paths", {})
    missing = sorted(p for p in kept_paths if p not in src_paths)
    if missing:
        for p in missing:
            print(f"generate_demo_openapi: manifest path absent from openapi.json: {p}", file=sys.stderr)
        return 1

    demo_paths: dict = {}
    for path in sorted(kept_paths):
        op = src_paths[path]
        kept = {k: op[k] for k in ("get", "parameters") if k in op}
        demo_paths[path] = kept

    info = dict(root.get("info", {}))
    info["title"] = DEMO_TITLE
    info["description"] = info.get("description", "") + DEMO_DESCRIPTION_SUFFIX

    demo = {
        "openapi": root["openapi"],
        "info": info,
        "servers": [{"url": DEMO_SERVER}],
        "paths": demo_paths,
        "components": root.get("components", {}),
    }

    OUT_FILE.write_text(json.dumps(demo, indent=2, sort_keys=True) + "\n")
    print(f"generate_demo_openapi: {len(demo_paths)} paths → {OUT_FILE}")
    return 0


if __name__ == "__main__":
    sys.exit(main())
