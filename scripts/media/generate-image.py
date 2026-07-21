#!/usr/bin/env -S uv run --script
# /// script
# requires-python = ">=3.10"
# ///
"""Generate images with the Azure OpenAI gpt-image-2 deployment.

Reads AZURE_OPENAI_ENDPOINT / AZURE_OPENAI_API_KEY / AZURE_OPENAI_API_VERSION
from the environment, falling back to the repo-root .env. Stdlib only.

Transparency: the default gpt-image-2 model has NO alpha -- background="transparent"
returns HTTP 400 "not supported for this model", and asking for it in the prompt just
paints a fake opaque checkerboard. Real alpha needs one of: (a) a gpt-image-1-series
deployment (--deployment gpt-image-1 --background transparent, PNG only, but capped at
1024x1024/1024x1536/1536x1024); (b) a flat matte here + scripts/media/chroma-key.py; or
(c) glow/smoke on pure black composited with mix-blend-mode: screen.

Usage:
  uv run scripts/media/generate-image.py "a glowing ember" --out ember.png
  uv run scripts/media/generate-image.py "hanging cables, silhouette" \
      --out fore.png --size 1536x1024 --quality high
  uv run scripts/media/generate-image.py "the same room at night, moonlit" \
      --edit day.png --out night.png --size 3456x2304 --quality high
"""
import argparse
import base64
import json
import os
import sys
import urllib.error
import urllib.request
import uuid

REPO_ROOT = os.path.dirname(os.path.dirname(os.path.dirname(os.path.abspath(__file__))))


def load_env_file(path: str) -> None:
    if not os.path.exists(path):
        return
    with open(path) as f:
        for line in f:
            line = line.strip()
            if not line or line.startswith("#") or "=" not in line:
                continue
            key, _, value = line.partition("=")
            os.environ.setdefault(key.strip(), value.strip())


def parse_size(value: str) -> str:
    """gpt-image-2 accepts any WxH where both are divisible by 16, the longest
    edge is <= 3840, and the total stays inside a pixel budget of ~8 MP
    (3456x2304 passes; 3840x2560 is rejected). Probed live 2026-07-14 — the
    API's own 400s state these rules. gpt-image-1-series deployments keep the
    old fixed trio (1024x1024 / 1536x1024 / 1024x1536)."""
    try:
        w, h = (int(p) for p in value.lower().split("x"))
    except ValueError:
        raise argparse.ArgumentTypeError(f"size must be WxH, got {value!r}")
    if w % 16 or h % 16:
        raise argparse.ArgumentTypeError("width and height must be divisible by 16")
    if max(w, h) > 3840:
        raise argparse.ArgumentTypeError("longest edge must be <= 3840")
    if w * h > 3456 * 2304:
        raise argparse.ArgumentTypeError(
            "exceeds the ~8 MP pixel budget (3456x2304 is the largest 3:2)")
    return f"{w}x{h}"


def main() -> int:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("prompt")
    parser.add_argument("--out", default="generated.png", help="output PNG path")
    parser.add_argument("--size", default="1024x1024", type=parse_size,
                        help="WxH, both divisible by 16, longest edge <= 3840, "
                             "<= 3456x2304 pixels total (e.g. 3456x2304, 1536x1024)")
    parser.add_argument("--quality", default="medium",
                        choices=["low", "medium", "high"])
    # "transparent" only works on gpt-image-1-series deployments; the default
    # gpt-image-2 rejects it (HTTP 400). See module docstring / chroma-key.py.
    parser.add_argument("--background", default="auto",
                        choices=["auto", "opaque", "transparent"])
    parser.add_argument("--deployment", default="gpt-image-2")
    parser.add_argument("--edit", metavar="IMAGE",
                        help="path to a reference image; switches to the "
                             "images/edits endpoint, which transforms the "
                             "reference per the prompt (composition-preserving "
                             "restyles, e.g. a night version of a day plate)")
    args = parser.parse_args()

    load_env_file(os.path.join(REPO_ROOT, ".env"))
    endpoint = os.environ.get("AZURE_OPENAI_ENDPOINT", "").rstrip("/")
    api_key = os.environ.get("AZURE_OPENAI_API_KEY", "")
    api_version = os.environ.get("AZURE_OPENAI_API_VERSION", "")
    if not (endpoint and api_key and api_version):
        print("Missing AZURE_OPENAI_* config (env or repo-root .env)", file=sys.stderr)
        return 1

    if args.edit:
        # images/edits takes multipart form data (probed live 2026-07-14 on
        # gpt-image-2: same size/quality params as generations).
        url = (f"{endpoint}/openai/deployments/{args.deployment}"
               f"/images/edits?api-version={api_version}")
        with open(args.edit, "rb") as f:
            image_bytes = f.read()
        boundary = uuid.uuid4().hex
        fields = {"prompt": args.prompt, "size": args.size,
                  "quality": args.quality, "n": "1"}
        parts = [
            (f'--{boundary}\r\nContent-Disposition: form-data; '
             f'name="{name}"\r\n\r\n{value}\r\n').encode()
            for name, value in fields.items()
        ]
        parts.append(
            (f'--{boundary}\r\nContent-Disposition: form-data; name="image"; '
             f'filename="{os.path.basename(args.edit)}"\r\n'
             f'Content-Type: image/png\r\n\r\n').encode()
            + image_bytes + b"\r\n")
        parts.append(f"--{boundary}--\r\n".encode())
        req = urllib.request.Request(
            url,
            data=b"".join(parts),
            headers={"api-key": api_key,
                     "Content-Type": f"multipart/form-data; boundary={boundary}"},
        )
    else:
        url = (f"{endpoint}/openai/deployments/{args.deployment}"
               f"/images/generations?api-version={api_version}")
        body = {
            "prompt": args.prompt,
            "size": args.size,
            "quality": args.quality,
            "background": args.background,
            "output_format": "png",
            "n": 1,
        }
        req = urllib.request.Request(
            url,
            data=json.dumps(body).encode(),
            headers={"api-key": api_key, "Content-Type": "application/json"},
        )
    try:
        with urllib.request.urlopen(req, timeout=900) as resp:
            data = json.load(resp)
    except urllib.error.HTTPError as e:
        print(f"HTTP {e.code}: {e.read().decode(errors='replace')[:500]}",
              file=sys.stderr)
        return 1

    png = base64.b64decode(data["data"][0]["b64_json"])
    os.makedirs(os.path.dirname(os.path.abspath(args.out)), exist_ok=True)
    with open(args.out, "wb") as f:
        f.write(png)
    print(f"wrote {args.out} ({len(png) // 1024} KB)")
    return 0


if __name__ == "__main__":
    sys.exit(main())
