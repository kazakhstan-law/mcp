# kazakhstan-law-mcp — project memory

## Type checking
- ty (`uvx ty check`) reads `./.venv`: run `uv sync` first or every import is unresolved. The
  worktree delegate (`.orca/worktree-setup.sh`) does this for new workspaces.
- ruff enforces ANN on `src` only; `tests/**` is exempt. `src` was ANN-clean on 2026-09-30.
- `src` is ty-clean as of 2026-09-30; keep it that way.
