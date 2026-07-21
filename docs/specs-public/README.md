# Public specs

Git-tracked spec folders that ship with the public repository.

Most dated specs live in `docs/specs/`, which is deliberately **local-only**
(excluded via `.git/info/exclude`) because it carries development history from
the private `expense_reporting` repo. This folder is the opposite: work that is
meant to be public — launch assets, published design references, anything a
reader of the open-source repo should be able to see.

Same conventions as the local-only `docs/specs/`: one folder per spec, named
`YYYY-MM-DD-<slug>/`, primary file `README.md`.

## Contents

| Spec | Description |
|------|-------------|
| [`2026-07-04-tidings-launch-video/`](./2026-07-04-tidings-launch-video/) | The Tidings launch announcement video — a 32s HyperFrames composition (plain HTML + GSAP) rendered to MP4, with design reference and preview player |
