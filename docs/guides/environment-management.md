# Local Environment and Dependency Management Guide

This guide provides detailed instructions for setting up and managing a local Python development environment using `uv`. All commands should be run from the project root.

## Quick Start (TL;DR)
```bash
# DevContainer users: environment is ready automatically (uv sync runs on creation)

# Local setup (one command)
uv sync              # Creates .venv, installs Python 3.12, installs all deps

# Daily workflow (option A: explicit activation)
source .venv/bin/activate
pytest tests/
deactivate

# Daily workflow (option B: no activation needed)
uv run pytest tests/
uv run ruff check src/ tests/
```

## What is `uv`?

**`uv`** is an extremely fast Python package manager and project tool, written in Rust. It handles everything this project needs: Python version management, virtual environment creation, dependency resolution, and package installation.

**`pyenv`** is **not required**. `uv` installs and manages the correct Python version (3.12) automatically. If you already use `pyenv`, it will work fine alongside `uv`, but it's not a prerequisite.

## Setting Up the Environment

### DevContainer (recommended)

The DevContainer is the primary development environment. Open the project in VS Code with the Dev Containers extension (or GitHub Codespaces) and the `postCreateCommand` runs `uv sync` automatically. No manual setup needed.

### Local Setup

A single command creates the virtual environment, installs Python 3.12 if needed, and installs all dependencies:

```bash
uv sync
```

This creates the `.venv` folder (excluded from version control via `.gitignore`).

### Activating the Environment

You have two options for running commands:

**Option A: Activate the venv** (traditional approach)

```bash
source .venv/bin/activate   # macOS / Linux
.venv\Scripts\Activate.ps1  # Windows (PowerShell)
```

Your shell prompt will show `(.venv)` when active. You need to activate in each new terminal session.

**Option B: Use `uv run`** (no activation needed)

Prefix commands with `uv run` to execute them inside the virtual environment without activating it:

```bash
uv run pytest tests/ -v
uv run ruff check src/ tests/
```

This is what CI uses and avoids the "forgot to activate" problem.

### Deactivating the Environment

If you activated the venv manually:

```bash
deactivate
```

## Managing Dependencies

Dependencies are managed using two files:
- **`pyproject.toml`** — Source of truth. Production deps in `[project.dependencies]`, dev deps in `[dependency-groups] dev`.
- **`uv.lock`** — Auto-generated lock file with exact pinned versions. Committed to version control.

### Installing Dependencies

```bash
uv sync                    # Install all deps (production + dev)
uv sync --no-group dev     # Install production deps only (e.g., in Docker)
```

### Adding or Updating Dependencies

Use `uv add` to add a package — it edits `pyproject.toml` and updates `uv.lock` in one step:

```bash
# Production dependency (needed in Lambda)
uv add <package>

# Development dependency (testing, notebooks)
uv add --group dev <package>
```

To update a package to a newer version:

```bash
uv add <package>@latest
```

Or edit `pyproject.toml` manually, then run `uv sync` to update the lock file and install.

### Removing Dependencies

```bash
uv remove <package>
uv remove --group dev <package>
```

## Common Issues & Solutions

### "Command not found" errors
**Problem:** You're getting errors like `pytest: command not found` or `python: no module named 'openai'`
**Solution:** Either activate the venv (`source .venv/bin/activate`) or use `uv run` prefix (e.g., `uv run pytest`).

### Wrong Python version
**Problem:** `python --version` shows the wrong version
**Solution:** Run `uv sync` — it will install and use the correct Python version (3.12) automatically.

### Dependencies not found
**Problem:** Import errors even after installation
**Solution:** Run `uv sync` to ensure all dependencies are installed, then use `uv run` or activate the venv.

## Make Commands

You can also use the Makefile for convenience:

```bash
make env    # Run uv sync (set up entire environment in one command)
```
