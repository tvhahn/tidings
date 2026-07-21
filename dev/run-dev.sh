#!/usr/bin/env bash
# Run a long-running dev command so that Ctrl-C drops the user into a normal
# interactive bash with the original command pre-seeded in history.
# Up-arrow + Enter then restarts the surface; `exit` closes the tmux window.
set -u
CMD="$*"

# Per-pane history file so each surface's recovery shell only sees its own
# command (and we don't pollute ~/.bash_history with `make dev-*` entries
# from sibling panes).
PANE_ID="${TMUX_PANE:-$$}"
DEV_HISTFILE="${TMPDIR:-/tmp}/dev-history-${PANE_ID//[^A-Za-z0-9_-]/}"
printf '%s\n' "$CMD" > "$DEV_HISTFILE"

# Catch SIGINT in the wrapper itself so a Ctrl-C aimed at the dev command
# doesn't also kill *us* before we can drop the user into a recovery shell.
# Children that install their own SIGINT handler (uvicorn, vite, pnpm, node)
# still receive Ctrl-C normally and shut down.
trap : INT

eval "$CMD"

HISTFILE="$DEV_HISTFILE" exec bash -i
