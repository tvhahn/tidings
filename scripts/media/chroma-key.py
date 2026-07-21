#!/usr/bin/env -S uv run --script
# /// script
# requires-python = ">=3.10"
# dependencies = ["pillow", "numpy"]
# ///
"""Chroma-key a flat-matte image plate into a transparent PNG.

Made for gpt-image-2 output, which can't emit alpha: generate the asset on a
flat matte color (cyan works well for warm/orange subjects), then extract.
The matte color is sampled automatically from the image corners. Alpha is a
smoothstep on the color distance to the matte, and foreground colors are
un-premultiplied (fg = (observed - (1-a)*matte) / a) so edges keep their own
color instead of a matte-tinted fringe.

Usage:
  uv run scripts/media/chroma-key.py plate.png cutout.png [--lo 40] [--hi 140]

--lo: distance below which a pixel is fully matte (alpha 0)
--hi: distance above which a pixel is fully subject (alpha 1)
"""
import argparse

import numpy as np
from PIL import Image


def main() -> None:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("input")
    parser.add_argument("output")
    parser.add_argument("--lo", type=float, default=40.0)
    parser.add_argument("--hi", type=float, default=140.0)
    args = parser.parse_args()

    img = np.asarray(Image.open(args.input).convert("RGB"), dtype=np.float64)
    h, w, _ = img.shape

    corners = np.concatenate([
        img[:16, :16].reshape(-1, 3),
        img[:16, -16:].reshape(-1, 3),
        img[-16:, :16].reshape(-1, 3),
        img[-16:, -16:].reshape(-1, 3),
    ])
    matte = np.median(corners, axis=0)

    dist = np.sqrt(((img - matte) ** 2).sum(axis=-1))
    t = np.clip((dist - args.lo) / (args.hi - args.lo), 0.0, 1.0)
    alpha = t * t * (3 - 2 * t)  # smoothstep

    a = alpha[..., None]
    fg = np.where(a > 1e-3, (img - (1 - a) * matte) / np.maximum(a, 1e-3), 0.0)
    fg = np.clip(fg, 0, 255)

    out = np.dstack([fg, alpha * 255]).astype(np.uint8)
    Image.fromarray(out, "RGBA").save(args.output)

    kept = (alpha > 0.5).mean() * 100
    print(f"matte color: {matte.astype(int).tolist()}, "
          f"subject coverage: {kept:.1f}%, wrote {args.output}")


if __name__ == "__main__":
    main()
