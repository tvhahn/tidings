# tidings-launch

A HyperFrames video composition — the Tidings launch announcement (32s, 1920×1080). Plain HTML + GSAP; rendered to MP4 by the `hyperframes` CLI.

## Requirements

- **Node.js 22+** — [nodejs.org](https://nodejs.org/)
- **FFmpeg** — `brew install ffmpeg` (macOS) or `sudo apt install ffmpeg` (Debian/Ubuntu) or [ffmpeg.org/download](https://ffmpeg.org/download.html) (Windows)

Verify: `npx hyperframes doctor`

## Preview

```bash
npx hyperframes preview
```

Opens the HyperFrames Studio at `http://localhost:3002` with frame-accurate scrubbing.

## Refine with Claude Code

This project was drafted in Claude Design. To polish animations, timing, and pacing:

```bash
npx skills add heygen-com/hyperframes   # install HyperFrames skills (one-time)
npx hyperframes lint                     # verify structure (should pass with zero errors)
npx hyperframes preview                  # open the studio for live feedback
```

Then open in Claude Code and iterate:

- "Slow the connector-path draws in scene 3"
- "Hold the journal card a beat longer before the claims appear"
- "Tighten scene 5 to 2.5s"

## Render

```bash
npx hyperframes render . -o output.mp4 -q high
```

(The argument is the project directory — it renders that directory's
`index.html`.) 1920×1080 / 30fps by default. Needs `ffmpeg` *and* `ffprobe` on
PATH. The committed `output.mp4` was rendered with exactly this command.
