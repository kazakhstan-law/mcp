"""Keep full clones of the scope repositories current.

The corpus is force-pushed on every build, so an update is fetch + reset --hard, never pull.
Full history is required: history and at_date read old commits.
"""

from __future__ import annotations

import argparse
import sys
import time

from kzlaw_mcp.config import ALL_SCOPES, Settings
from kzlaw_mcp.gitio import CommandError, run

TIMEOUT = 3600.0


def refresh_scope(settings: Settings, scope: str) -> str:
    root = settings.corpus_root
    repo = root / scope
    url = settings.remote_template.format(org=settings.github_org, scope=scope)
    if not (repo / ".git").exists():
        run(
            ["git", "clone", "-q", "--single-branch", "--branch", "main", url, scope],
            root,
            timeout=TIMEOUT,
        )
        return "cloned"
    remote = run(["git", "ls-remote", url, "refs/heads/main"], repo, timeout=120).text.split()
    head = run(["git", "rev-parse", "HEAD"], repo, timeout=30).text.strip()
    if remote and remote[0] == head:
        return "unchanged"
    run(["git", "fetch", "-q", "origin", "main"], repo, timeout=TIMEOUT)
    run(["git", "reset", "-q", "--hard", "FETCH_HEAD"], repo, timeout=600)
    return "updated"


def main() -> None:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--loop", type=float, default=0, help="repeat every N seconds")
    parser.add_argument("--scopes", default=",".join(ALL_SCOPES))
    ns = parser.parse_args()
    settings = Settings.from_env()
    settings.corpus_root.mkdir(parents=True, exist_ok=True)
    while True:
        for scope in ns.scopes.split(","):
            try:
                print(f"{scope}: {refresh_scope(settings, scope)}", flush=True)
            except CommandError as exc:
                print(f"{scope}: FAILED {exc}", file=sys.stderr, flush=True)
        if not ns.loop:
            return
        time.sleep(ns.loop)
