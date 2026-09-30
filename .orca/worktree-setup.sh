#!/usr/bin/env bash
# worktree-setup.sh — this repo's own worktree delegate.
#
# Scaffolded by /us:repo-setup. The machines dispatcher (~/machines/agents/worktree-setup.sh)
# runs it inside every fresh worktree, after it gortex-tracks the worktree and links the
# generic gitignored config set. It lives at .orca/worktree-setup.sh (committed, in a
# personal repo) or at <git-common-dir>/us/worktree-setup.sh (a work repo: never committed,
# shared by every worktree, run after the repo's own committed delegate).
#
# `.env` is NOT in the generic set, deliberately — it is repo-semantic. If this repo
# needs a per-worktree .env, write it HERE; the dispatcher linking main's .env would
# make an append-style write land in the main checkout and give every worktree one
# shared namespace. If this repo instead wants main's .env verbatim, link it here.
#
# INVARIANT: never block Orca. Every path is non-fatal; always exit 0.
# Never use the errexit option.

log() { echo "worktree-setup: $*" >&2; }

# >>> repo-setup:managed:repo-steps >>>
# Repo-specific steps go here. Examples:
#   - link an extra gitignored file the generic set misses
#   - copy a seed DB / .superpowers ledger the app needs
#   - print a ready-to-run command for the developer
# Keep every step non-fatal (guard with `|| log "WARN: ..."`).
# ty and ruff read ./.venv; without it every import reads as unresolved.
uv sync -q || log "WARN: uv sync failed; ty will not resolve imports"
# <<< repo-setup:managed:repo-steps <<<

exit 0
