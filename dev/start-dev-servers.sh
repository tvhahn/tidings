#!/bin/bash
# Start dev servers in a detached tmux session.
# Called by postStartCommand and the VS Code 'Start Dev Servers' task.
# Must be idempotent.

EXPECTED_WINDOWS=5   # api, frontend, docs, marketing, demo

if tmux has-session -t dev 2>/dev/null; then
  window_count=$(tmux list-windows -t dev 2>/dev/null | wc -l)
  if [ "$window_count" -ge "$EXPECTED_WINDOWS" ]; then
    exit 0
  fi
  tmux kill-session -t dev 2>/dev/null || true
fi

# Kill stale dev server processes that may have survived a previous session.
for port in \
    "${API_PORT:-8000}" \
    "${VITE_DEV_PORT:-5173}" \
    "${DOCS_DEV_PORT:-4321}" \
    "${MARKETING_DEV_PORT:-5175}" \
    "${DEMO_DEV_PORT:-5176}"; do
  pid=$(ss -tlnp "sport = :$port" 2>/dev/null | grep -oP 'pid=\K\d+' | head -1)
  [ -n "$pid" ] && kill "$pid" 2>/dev/null && sleep 0.5
done

WRAP="bash /workspace/dev/run-dev.sh"

tmux new-session -d -s dev -n api       "cd /workspace && $WRAP make dev-api"
tmux new-window  -t dev    -n frontend  "cd /workspace && $WRAP make dev-frontend"
tmux new-window  -t dev    -n docs      "cd /workspace && $WRAP make dev-docs"
tmux new-window  -t dev    -n marketing "cd /workspace && $WRAP make dev-marketing"
tmux new-window  -t dev    -n demo      "cd /workspace && $WRAP make dev-demo"
