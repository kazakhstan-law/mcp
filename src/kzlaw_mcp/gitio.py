"""Subprocess helpers for git and ripgrep: argument lists only, never a shell."""

from __future__ import annotations

import subprocess
from dataclasses import dataclass
from pathlib import Path


class CommandError(RuntimeError):
    """A subprocess failed or timed out."""


@dataclass(frozen=True)
class Output:
    text: str
    truncated: bool
    returncode: int


def run(
    args: list[str],
    cwd: Path,
    *,
    timeout: float,
    max_bytes: int = 2_000_000,
    ok: tuple[int, ...] = (0,),
) -> Output:
    try:
        proc = subprocess.run(args, cwd=cwd, capture_output=True, timeout=timeout, check=False)
    except subprocess.TimeoutExpired as exc:
        raise CommandError(f"{args[0]} timed out after {timeout:.0f}s") from exc
    if proc.returncode not in ok:
        err = proc.stderr.decode("utf-8", "replace").strip()[:300]
        raise CommandError(f"{args[0]} exited {proc.returncode}: {err}")
    data = proc.stdout
    truncated = len(data) > max_bytes
    return Output(data[:max_bytes].decode("utf-8", "replace"), truncated, proc.returncode)


class Git:
    """Read-only git plumbing on one repository."""

    def __init__(self, repo: Path, timeout: float) -> None:
        self.repo = repo
        self.timeout = timeout

    def _git(self, *args: str, ok: tuple[int, ...] = (0,), max_bytes: int = 2_000_000) -> Output:
        return run(["git", *args], self.repo, timeout=self.timeout, ok=ok, max_bytes=max_bytes)

    def head(self) -> str:
        return self._git("rev-parse", "HEAD").text.strip()

    def rev_before(self, date: str) -> str | None:
        """The last commit on or before `date` (YYYY-MM-DD). Corpus commits are UTC midnight."""
        return (
            self._git("rev-list", "-1", f"--before={date}T23:59:59Z", "HEAD").text.strip() or None
        )

    def rev_parse(self, rev: str) -> str | None:
        """The full sha of commit `rev`, or None when there is none."""
        out = self._git(
            "rev-parse", "--verify", "--quiet", "--end-of-options", f"{rev}^{{commit}}", ok=(0, 1)
        )
        return out.text.strip() or None

    def diff_names(self, a: str, b: str, *paths: str) -> list[str]:
        """Paths under `paths` that differ between commits `a` and `b` (a rename is two paths)."""
        out = self._git("diff", "--name-only", "--no-renames", a, b, "--", *paths)
        return [line for line in out.text.splitlines() if line]

    def commit_date(self, sha: str) -> str:
        return self._git("log", "-1", "--format=%cs", sha).text.strip()

    def ls_tree(self, sha: str, *paths: str) -> list[str]:
        out = self._git("ls-tree", "-r", "--name-only", sha, "--", *paths, max_bytes=64_000_000)
        return [line for line in out.text.splitlines() if line]

    def blob(self, sha: str, path: str) -> str:
        return self._git("cat-file", "blob", f"{sha}:{path}", max_bytes=16_000_000).text

    def blob_size(self, sha: str, path: str) -> int:
        return int(self._git("cat-file", "-s", f"{sha}:{path}").text.strip())

    def grep(
        self, sha: str, pattern: str, paths: list[str], *, fixed: bool
    ) -> list[tuple[str, int]]:
        """(path, line) of every match of `pattern` in `paths` at `sha`."""
        flag = "-F" if fixed else "-E"
        out = self._git("grep", "-n", flag, "-e", pattern, sha, "--", *paths, ok=(0, 1))
        hits = []
        for line in out.text.splitlines():
            _, path, lineno, _ = line.split(":", 3)  # "<sha>:<path>:<line>:<text>"
            hits.append((path, int(lineno)))
        return hits

    def grep_lines(
        self, sha: str, needles: list[str], paths: list[str]
    ) -> list[tuple[str, int, str]]:
        """(path, line, text) of every line in `paths` at `sha` that contains one of `needles`."""
        pats = [a for n in needles for a in ("-e", n)]
        out = self._git(
            "grep", "-n", "-F", *pats, sha, "--", *paths, ok=(0, 1), max_bytes=4_000_000
        )
        hits = []
        for line in out.text.splitlines():
            _, path, lineno, text = line.split(":", 3)
            hits.append((path, int(lineno), text))
        return hits

    def log(self, *args: str) -> str:
        return self._git("log", *args, max_bytes=1_000_000).text
