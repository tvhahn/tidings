---
name: generate-image
description: Generate raster image assets with the Azure OpenAI gpt-image-2 deployment, and cut them out to transparent PNGs. Use when you need hero art, glow/ember/smoke/haze layers, textures, illustrations, or any generated image — especially anything needing transparency, since gpt-image-2 can't emit alpha and there is a two-step matte→cutout workflow.
argument-hint: "[what to generate, e.g. 'a calm abstract gradient on pure black']"
---

# Generate Image Assets — Azure gpt-image-2

Two `uv`-run scripts in `scripts/` back this workflow: `generate-image.py`
(stdlib-only) and `chroma-key.py` (pulls `pillow` + `numpy` via its inline `uv`
header, auto-fetched on run). The three credentials `AZURE_OPENAI_ENDPOINT` /
`AZURE_OPENAI_API_KEY` / `AZURE_OPENAI_API_VERSION` load from the repo-root `.env`
automatically — no setup needed. If a run reports missing config, the `.env` is
absent or missing the `AZURE_OPENAI_*` keys, not a code fault. (The `gpt-image-2`
deployment name is a `--deployment` default baked into the code, **not** an env
var — override it on the CLI, not `.env`.)

## 1. Generate

```bash
uv run scripts/media/generate-image.py "<prompt>" --out asset.png \
    --size 1536x1024 --quality high
```

- `--size`: any `WxH` with both dimensions divisible by 16, longest edge ≤ 3840,
  and a total pixel budget of at least `3456x2304` (~8 MP — probed live
  2026-07-14: `3456x2304` generates, `3840x2560` trips the budget; the exact
  ceiling between them is unprobed, and probing acceptance bills a generation).
  Largest confirmed 3:2 is `3456x2304`. The old fixed trio (`1024x1024` /
  `1536x1024` / `1024x1536`) still applies to gpt-image-1-series deployments only.
- `--quality`: `low` | `medium` | `high`. A high-quality `1536x1024` takes ≈ 1–2 min.
- `--background`: `auto` | `opaque`. **Not `transparent`** — gpt-image-2 rejects it
  (HTTP 400); it cannot emit alpha. Get transparency via step 2 instead.
- `--deployment`: defaults to `gpt-image-2`; override only if the deployment name changes.

## 1b. Edit with a reference image

The deployment also supports the `images/edits` endpoint (probed live
2026-07-14): it takes an input image plus a prompt and transforms the image
per the prompt while preserving composition — restyles ("this room at
night"), palette shifts, additions/removals of elements. Same `--size` /
`--quality` rules as generation; each call bills like a generation, and the
endpoint 429s (`EngineOverloaded`) under load — retry with a wait.

```bash
uv run scripts/media/generate-image.py "the same room at night, moonlit" \
    --edit day.png --out night.png --size 3456x2304 --quality high
```

Use this whenever a new asset must match an existing one (light/dark pairs,
seasonal variants, prop changes) — a fresh generation from a similar prompt
gives a different scene; an edit keeps the geometry.

## 2. Transparency (gpt-image-2 has no alpha)

**Native alpha, if you need it often:** gpt-image-2 *dropped* the transparent-background
support the gpt-image-1 series still has (in exchange for up-to-4K output). Deploy a
`gpt-image-1` / `gpt-image-1-mini` / `gpt-image-1.5` model and call
`--deployment <that-name> --background transparent` (PNG only) for a real alpha channel,
no cutout step. Trade-off: gpt-image-1 caps at `1024x1024` / `1024x1536` / `1536x1024`.
(Doc-confirmed on OpenAI + Azure; not tested here — this resource only has a gpt-image-2
deployment, which returns HTTP 400 `"...not supported for this model"` for `transparent`.)

Otherwise, two local patterns:

**Additive glow — embers, smoke, haze, light rays, sparks.** Generate on **pure
black**, then composite in CSS with `mix-blend-mode: screen`. Black drops out for
free; no cutout script needed.

**Opaque subject — an object, an icon, a solid shape.** Generate on a **flat cyan
matte** ("on a flat cyan background, no gradient, no texture") — cyan keys
cleanest against warm subjects — then extract alpha:

```bash
uv run scripts/media/chroma-key.py plate.png cutout.png [--lo 40] [--hi 140]
```

The matte color is auto-sampled from the image corners. Alpha is a smoothstep on
per-pixel color distance to the matte: `--lo` = distance below which a pixel is
fully matte (alpha 0), `--hi` = distance above which it is fully subject (alpha 1).
Edges are un-premultiplied so they keep their own color instead of a cyan fringe.
If you see a colored halo, raise `--lo`; if the subject gets holes / goes
translucent, **lower** `--hi` (fewer pixels have to clear the full-opacity threshold).
The script prints the sampled matte color and subject-coverage %, so sanity-check
those before trusting the cutout.

## Where assets go

Frontend art lives in `frontend/src/marketing/assets/` (e.g.
`screenshot-journal.webp`). Put generated art there and **import it** from the
component (`import hero from "../assets/hero.png";`) so Vite's pipeline hashes and
optimizes it — don't drop unoptimized PNGs in `frontend/public/` unless the asset
must be referenced by a stable, unhashed URL. Prefer `.webp` for photographic /
gradient art once you've cut it; keep `.png` when you need the alpha channel.

Before shipping any generated image into a user-facing surface, honor the calm
Tidings brand — no alarmist, high-energy, or gamified imagery. When in doubt,
check `docs/brand/README.md`.

## Prompting notes

- State the background explicitly ("on pure black" / "on a flat cyan background,
  no gradient") — an even, untextured matte keys far better than a busy one.
- For cutouts, describe the subject as a clean silhouette or solid shape.
- Regenerate rather than upscale — request the final `--size` directly.

## Gotchas

- **Real alpha is impossible from this deployment — two dead ends, both confirmed
  live:** (1) `background: "transparent"` → HTTP 400 `"Transparent background is not
  supported for this model."` (rejected at the model level). (2) Asking for a
  transparent background *in the prompt* → HTTP 200 but an **opaque RGB PNG with a
  gray checkerboard painted in** — it fakes the *look* of transparency, so it passes
  a thumbnail glance but is useless as an asset. Always use step 2 for real alpha.
- `chroma-key.py` needs `pillow` + `numpy`; they're declared inline in its `uv`
  script header, so `uv run` fetches them — no `uv add` required.
- Each call to `generate-image.py` bills the Azure deployment, so avoid needless
  re-runs; both scripts are otherwise safe to run repeatedly.
