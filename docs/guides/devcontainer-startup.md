# Devcontainer startup and tmux workflow

For contributors. The devcontainer auto-starts both dev servers on boot and
runs them in tmux, so any entry point — VS Code, a terminal, SSH — attaches
to the same running pair. The devcontainer stack is
`.devcontainer/docker-compose.yml`; the root `docker-compose.yml` is the
self-hoster stack, not this.

Throughout this page, `<container>` is your devcontainer's name — find it
with `docker ps --filter name=devcontainer`.

## MCP server setup (first time)

The repo registers MCP servers via a workspace-root `.mcp.json` (Claude Code
auto-discovers it). The file is gitignored because the `context7` entry
carries a personal bearer token, so each developer keeps their own copy:

```bash
cp .mcp.json.example .mcp.json
# replace the context7 placeholder with your token,
# or delete the context7 block if you don't use it
```

Both `chrome-devtools` and `context7` register the next time Claude Code
starts in this workspace. The first interactive session prompts once to
trust the project's MCP servers — accept it.

Worktrees: use Claude Code's built-in worktrees (`EnterWorktree` or
`claude --worktree`). `.mcp.json` is gitignored, so copy it into a new
worktree yourself if you need MCP servers there.

**Pre-warm:** `postCreateCommand` runs
`npx -y chrome-devtools-mcp@latest --version` to populate the npm cache so
the first MCP invocation doesn't pay the download cost.

## Startup sequence

```
Container starts ─── sleep infinity (keeps container alive)
    │
    ▼
postStartCommand ─── dev/start-dev-servers.sh
    │
    ▼
tmux session "dev"
    ├── api      → make dev-api      (uvicorn :8000 --reload)
    └── frontend → make dev-frontend  (vite :5173)
```

## tmux session architecture

Dev servers and Claude Code run in **separate** tmux sessions:

| Session | Windows | Created by |
|---------|---------|------------|
| `dev` | `api`, `frontend` | `postStartCommand` (automatic) |
| `claude` | Claude Code | `c1` inside the container (on demand) |
| `claude-2`, etc. | Parallel Claude instances | `c1 2` |

Switch between sessions with `Ctrl+b s` (session list) or `Ctrl+b (`/`)`
(prev/next).

### `c1` — Claude Code in persistent tmux

The image ships a `c1` helper that opens Claude Code in a tmux session that
survives disconnects:

```bash
c1       # switch to or create the "claude" session
c1 2     # switch to or create "claude-2"
```

If already inside tmux, `c1` uses `tmux switch-client` instead of
`tmux attach`, avoiding nested tmux.

### From VS Code

A task in `.vscode/tasks.json` auto-runs on folder open and attaches a
terminal panel to the `dev` session (`tmux attach -t dev`). Switch between
the `api` and `frontend` windows with `Ctrl+b n`/`Ctrl+b p`. Requires
`"task.allowAutomaticTasks": "on"` (set in `devcontainer.json`).

### From a plain terminal

```bash
docker exec -it <container> tmux attach -t dev   # the servers
docker exec -it <container> zsh                  # a shell; run c1 from here
```

## Dev server scripts

`dev/start-dev-servers.sh`, called by `postStartCommand` on every container
start:

```bash
#!/bin/bash
tmux kill-session -t dev 2>/dev/null || true
tmux new-session -d -s dev -n api 'cd /workspace && make dev-api'
tmux new-window -t dev -n frontend 'cd /workspace && make dev-frontend'
```

| Target | Description |
|--------|-------------|
| `make dev-api` | FastAPI with uvicorn `--reload` on port 8000 |
| `make dev-frontend` | Vite dev server on port 5173 |
| `make dev` | Both (backgrounds API, foreground frontend) |
| `make dev-attach` | Attach to the `dev` tmux session |
| `make dev-restart` | Restart both servers in their tmux windows |

The full port map — including the marketing, demo, and docs surfaces — is in
[`dev-surfaces.md`](dev-surfaces.md).

## Port forwarding

| Port | Service | Access |
|------|---------|--------|
| 5173 | Vite frontend | `http://<host-ip>:5173` |
| 8000 | FastAPI backend | `http://<host-ip>:8000` |
| 8888 | Jupyter (optional) | `http://<host-ip>:8888` |

Ports are published in `.devcontainer/docker-compose.yml` and forwarded in
`devcontainer.json`. The frontend proxies `/api/*` to the backend via Vite's
dev-server config.

## Troubleshooting

**Dev servers not starting.** Check whether the tmux session exists:

```bash
docker exec <container> tmux list-sessions
docker exec <container> tmux list-windows -t dev
```

If missing, run the startup script manually:

```bash
docker exec <container> bash /workspace/dev/start-dev-servers.sh
```

**pnpm not found.** The Dockerfile runs `corepack enable` to make pnpm
available system-wide. If the frontend tmux window exits immediately,
rebuild the container.

**VS Code task not auto-running.** Ensure `task.allowAutomaticTasks` is
`"on"`, then close and reopen the window — the `folderOpen` trigger only
fires on open.

**Server crashed in tmux.** The window stays open showing the error.
`make dev-restart` restarts both; or attach to the window
(`tmux attach -t dev:api`), read the error, and re-run the command.

---

## Appendix: an always-on rig (one maintainer's setup)

Everything below is one maintainer's personal setup, documented because it
works well — none of it is required, and the paths and names are examples to
adapt, not conventions to follow.

**Always-on container via systemd.** A user service brings the devcontainer
up at boot so the dev dashboard is reachable on the LAN without a manual
start. `~/.config/systemd/user/tidings-dev.service`:

```ini
[Unit]
Description=Tidings devcontainer

[Service]
Type=oneshot
RemainAfterExit=yes
WorkingDirectory=/home/<user>/path/to/tidings
ExecStartPre=/bin/bash -c 'for i in $(seq 1 30); do docker info >/dev/null 2>&1 && exit 0; sleep 2; done; exit 1'
ExecStart=/usr/bin/docker compose -f .devcontainer/docker-compose.yml up -d
ExecStop=/usr/bin/docker compose -f .devcontainer/docker-compose.yml stop

[Install]
WantedBy=default.target
```

Notes that make it work: `Type=oneshot` + `RemainAfterExit=yes` keeps the
service "active" after compose returns; the `ExecStartPre` loop waits for
the Docker daemon (user-level systemd can't `After=docker.service`); and
`loginctl enable-linger $USER` makes user services start at boot rather than
login. Manage with `systemctl --user status|start|stop|disable tidings-dev`.

**Remote attach.** From any machine that can SSH to the host, a small
wrapper script (`devcontainer up` if needed, then
`docker exec -it <container> tmux attach`) gives the same tmux sessions from
a laptop or a phone SSH client. That plus `c1`'s persistent sessions means a
Claude Code run started at a desk can be checked from anywhere.
