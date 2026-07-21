# Tidings launch video — design reference

32 seconds · 1920×1080 · 6 scenes · one shader transition (cross-warp-morph at the s3→s4 product reveal). All other cuts are hard cuts softened by slow content fade-ups on identical cream fields.

## Tokens

Reference values are oklch; `index.html` carries their exact sRGB hex
serializations (e.g. `--rust` → `#c1552c`) because HyperShader's capture parser
cannot read `oklch()` — an unparsed color silently downgrades the s3→s4 shader
to a plain CSS crossfade.

| Token | Value | Use |
|---|---|---|
| `--bg` | `oklch(0.985 0.008 80)` | Warm paper cream — every scene background |
| `--ink` | `oklch(0.26 0.018 60)` | Near-black warm ink — display + card text |
| `--muted` | `oklch(0.52 0.02 60)` | Supporting Inter text, envelope icon |
| `--rust` | `oklch(0.58 0.15 40)` | Brand accent — two underline draws only (scene 2 wordmark, scene 6 "delivered.") |
| `--hairline` | `oklch(0.89 0.015 70 / 0.5)` | Card borders, dividers |
| `--hairline-solid` | `oklch(0.85 0.02 70)` | Connector paths in the flow diagram |
| `--slot` | `oklch(0.95 0.01 78)` | Muted circular icon slot |
| `--card` | `#ffffff` | Cards on cream |

## Type

- **Display**: Source Serif 4, 600, tracking −0.015em. Sizes: 58–72px lines, 118px closing tagline.
- **Supporting**: Inter 400/500/600, 15–28px.
- **Numbers**: `font-variant-numeric: tabular-nums` set on `body`.

## Motion rules

- Fades and 4–16px translates only. Eases: `sine.out`, `sine.inOut`, `power1.inOut`, `power2.inOut`. Durations 0.6s+.
- No bounce, spring, scale-pops, parallax, or glitch. One shader (`cross-warp-morph`, 0.5s) at 16.75s.
- Every scene keeps something moving: slow −4 to −8px drifts (s1, s2, s3, s5), a continuous −16→+16px vertical drift on the browser frame (s4), staggered underline/URL arrivals (s6).
- Scene 3's build completes by 15.7s so the finished diagram holds ≥1s before the shader wipe; its stage is offset +40px right / +44px down for optical centering.
- **Anchor retirement rule:** HyperShader pins the anchor elements' (`#s3`, `#s4`) opacity every tick and scenes composite with transparent backgrounds, so a finished anchor must be retired by hiding its `.scene-content` (see the `#s4 .scene-content` set at 23.0s) — hiding the scene element itself gets overridden and the next scenes render on top of the stale anchor.

## Scene map

| # | Window | Content |
|---|---|---|
| 1 | 0–4s | "Your bank already emails you every transaction." |
| 2 | 4–8s | Thesis line + wordmark, rust underline draws in |
| 3 | 8–17s | Delivery flow: 3 email cards → stroke-drawn connectors → envelope slot → journal card assembles; three claims fade up |
| 4 | 17–23s | Browser-framed journal screenshot drifting upward; caption "Groceries is $14 over ceiling." |
| 5 | 23–26s | "Open source. Self-hosted." + supporting line |
| 6 | 26–32s | "Your spending, *delivered.*" — italic word slides in, rust underline; URL line; fade to cream |

## Brand guardrails honored

- Rust never fills a surface — it appears only as two 2–3px underline draws.
- No gradients, shadows, textures, stock imagery, dark frames.
- Sentence case, no exclamation marks, copy verbatim from the brief.
