# kazakhstan-law MCP server — Implementation Plan

> **For agentic workers:** REQUIRED SUB-SKILL: Use superpowers:subagent-driven-development (recommended) or superpowers:executing-plans to implement this plan task-by-task. Steps use checkbox (`- [ ]`) syntax for tracking.

**Goal:** A public, read-only remote MCP server (search, read, history, at_date) over git clones of the `kazakhstan-law` corpus, deployed on latitude behind hub, plus an on-stage Telegram demo built from Claude Code Channels.

**Architecture:** Python package `kzlaw_mcp`: pure text locators, a `Corpus` that reads everything through git objects at a pinned sha, four tool functions, a call gate (rate limit, concurrency, JSONL log) and a FastMCP Streamable HTTP server. A second process refreshes the clones hourly. Docker compose on latitude; Caddy on hub terminates TLS and proxies over the tailnet.

**Tech Stack:** Python ≥ 3.13, `mcp[cli]` ≥ 1.28.1 (FastMCP), PyYAML, ripgrep, git, uv, pytest, Docker compose, Caddy, Claude Code (Channels, `claude -p`).

**Spec:** `docs/superpowers/specs/2026-09-26-mcp-design.md`

## Global Constraints

- Repository `kazakhstan-law/mcp`, **public**; local checkout `~/my/kazakhstan-law-mcp`. No secrets committed: `.env` is gitignored, only `.env.example` is tracked.
- Independent of `qaz-code`: import nothing from it, no Postgres, no embeddings.
- Dependencies: `mcp[cli]>=1.28.1`, `pyyaml>=6.0`; dev: `pytest>=8`, `ruff>=0.6`, `httpx>=0.27`. Nothing else without asking.
- Every subprocess takes an argument list, never a shell; user text goes after `-e` / `--` (or as one `-S<phrase>` argument), so it can never become an option. Every subprocess has a timeout.
- Everything the tools return is read at **one commit sha**, and every citation link is pinned to that sha: `https://github.com/kazakhstan-law/<scope>/blob/<sha>/<path>`.
- Search is case-insensitive. Default scopes are `codes,government,ministerial`; `local-*` only on request.
- Tool results carry a ready-to-paste Markdown `citation` link. No disclaimer inside answers; the disclaimer lives in the README, the landing page and the server description.
- `~/kazakhstan-law-0916` on g15 is **read-only**: the corpus publish run copies its `.git`. Local runs may point the *server* at it (read-only git operations and `rg` only); never point `kzlaw-refresh` at it.
- Model for the demo and the reference runs: **Opus 5.5**, `claude-opus-5-5`.
- Artifacts (code, comments, commits, docs) in English; the landing page, the demo bot's `CLAUDE.md` and the connect instructions for people are in Russian.
- Personal repository: commit **and push** at the end of every task (from Task 1 on, once the GitHub repository exists). Commit messages end with `Co-Authored-By: Claude Opus 5.5 <noreply@anthropic.com>`.
- Run all tests with `uv run pytest`; lint with `uv run ruff check . && uv run ruff format --check .`.

## Review Focus

1. **A query that looks like an option or broken regex** (`--files`, `-e x`, `(`, a 5 000-char string) → a clear tool error or normal results, never an option injection or a crash. Test: Task 4.
2. **A date before the act existed, or before the corpus starts** → an explicit "not in force on that date" / "no history before" message, not an empty passage. Test: Task 5.
3. **An anchor the act does not have** (model guesses `st9999`, or an article repealed at that date) → "anchor not found" naming the act and pointing to search, not a silent empty result. Test: Task 5.
4. **A point label that repeats** (ПДД annexes restart numbering, so `1.` exists twice) → all matches (up to 3) with their headings, not silently the first. Test: Task 5.
5. **A spoofed `X-Forwarded-For` from a client that is not hub** → ignored; the rate limit keys on the real peer. Test: Task 7.

---

## File Structure

```
pyproject.toml                  package, scripts, pytest/ruff config
.gitignore  .env.example
README.md                       what it is, connect instructions (RU), disclaimer, dev notes
Dockerfile  compose.yml         image with git + ripgrep; services server + refresh
deploy/Caddyfile.snippet        the hub route, copied into metheoryt/vps by hand
deploy/demo-bot/CLAUDE.md       answer rules for the Telegram session (RU)
deploy/demo-bot/settings.json   permission lockdown for the Telegram session
deploy/demo-bot/kzlaw-demo-bot.service   user systemd unit (tmux wrapper)
scripts/smoke.py                MCP client: list tools, call search, against any URL
src/kzlaw_mcp/
  __init__.py
  config.py      Settings (env), scope lists
  gitio.py       run(), CommandError, Git (read-only git plumbing)
  locate.py      pure text: article_span, point_spans, line_context, anchor/point grammar
  corpus.py      InputError, ActRef, Corpus (act index, meta, files, citation URLs), labels
  search.py      search tool
  passages.py    read and at_date tools
  history.py     history tool
  gate.py        RateLimiter, CallLog, client_ip, Gate
  server.py      FastMCP wiring, instructions, landing + health routes, main()
  refresh.py     clone / fetch + reset loop, main()
tests/
  conftest.py            fixture corpus (two git repos with dated commits), settings fixture
  test_gitio.py  test_locate.py  test_corpus.py  test_search.py
  test_passages.py  test_history.py  test_gate.py  test_server.py  test_refresh.py
  reference/test_reference.py   opt-in: real questions through claude -p
```

---

### Task 1: Scaffold, settings, git runner, fixture corpus

**Files:**
- Create: `pyproject.toml`, `.gitignore`, `.env.example`, `src/kzlaw_mcp/__init__.py`, `src/kzlaw_mcp/config.py`, `src/kzlaw_mcp/gitio.py`, `tests/conftest.py`, `tests/test_gitio.py`

**Interfaces:**
- Produces:
  - `config.DEFAULT_SCOPES: tuple[str, ...]`, `config.LOCAL_SCOPES`, `config.ALL_SCOPES` (25 names)
  - `config.Settings` (frozen dataclass) with fields `corpus_root: Path, github_org="kazakhstan-law", host="127.0.0.1", port=8000, public_url="http://127.0.0.1:8000/mcp", trusted_proxies=frozenset({"100.64.0.1"}), log_path: Path|None=None, ip_salt="", rate_calls=60, rate_window_s=600.0, max_parallel=6, subprocess_timeout_s=20.0, head_ttl_s=60.0, remote_template="https://github.com/{org}/{scope}.git"`; `Settings.from_env() -> Settings`
  - `gitio.CommandError(RuntimeError)`, `gitio.Output(text, truncated, returncode)`, `gitio.run(args, cwd, *, timeout, max_bytes=2_000_000, ok=(0,)) -> Output`
  - `gitio.Git(repo: Path, timeout: float)` with `head() -> str`, `rev_before(date: str) -> str | None`, `commit_date(sha) -> str`, `ls_tree(sha, *paths) -> list[str]`, `blob(sha, path) -> str`, `blob_size(sha, path) -> int`, `grep(sha, pattern, paths, *, fixed: bool) -> list[tuple[str, int]]`, `log(*args) -> str`
  - fixtures `corpus_root` (Path with repos `codes/`, `ministerial/`), `settings` (Settings on it), constants `KOAP`, `PDD`, `KOAP_CODE="81245"`, `PDD_CODE="183572"`, `CONST_CODE="1005029"`

- [ ] **Step 1: Create the GitHub repository and push the existing spec commits**

The directory already holds a git repo with the spec commits on `main`. Use the `metheoryt` gh account (the one that publishes the corpus).

```bash
cd ~/my/kazakhstan-law-mcp
gh repo create kazakhstan-law/mcp --public --source . --remote origin \
  --description "MCP server over the kazakhstan-law git corpus: search, read, history, text at a date" --push
git log --oneline origin/main
```
Expected: the two or three `docs:` commits listed.

- [ ] **Step 2: Write `pyproject.toml`, `.gitignore`, `.env.example`**

```toml
[project]
name = "kazakhstan-law-mcp"
version = "0.1.0"
description = "Remote MCP server over the kazakhstan-law git corpus"
readme = "README.md"
requires-python = ">=3.13"
dependencies = ["mcp[cli]>=1.28.1", "pyyaml>=6.0"]

[project.scripts]
kzlaw-mcp = "kzlaw_mcp.server:main"
kzlaw-refresh = "kzlaw_mcp.refresh:main"

[dependency-groups]
dev = ["pytest>=8", "ruff>=0.6", "httpx>=0.27"]

[build-system]
requires = ["hatchling"]
build-backend = "hatchling.build"

[tool.hatch.build.targets.wheel]
packages = ["src/kzlaw_mcp"]

[tool.pytest.ini_options]
testpaths = ["tests"]
markers = ["reference: real questions through claude -p against a live server (costs quota)"]
addopts = "-m 'not reference'"

[tool.ruff]
line-length = 100
```

`.gitignore`:
```
.venv/
__pycache__/
.env
data/
*.egg-info/
```

`.env.example`:
```
# Copy to .env on the server. Never commit .env.
KZLAW_PUBLIC_URL=https://cyphy.kz/kazakhstan-law/mcp
# Random, server-local: salts the client-IP hash in the call log.
KZLAW_IP_SALT=
```

Create an empty `README.md` (filled in Task 10) and `src/kzlaw_mcp/__init__.py` containing `"""MCP server over the kazakhstan-law git corpus."""`. Run `uv sync` — it creates `uv.lock`.

- [ ] **Step 3: Write `src/kzlaw_mcp/config.py`**

```python
"""Runtime settings, read from KZLAW_* environment variables."""

from __future__ import annotations

import os
from dataclasses import dataclass, field
from pathlib import Path

DEFAULT_SCOPES: tuple[str, ...] = ("codes", "government", "ministerial")
LOCAL_SCOPES: tuple[str, ...] = tuple(
    f"local-{name}"
    for name in (
        "abai", "akmola", "aktobe", "almaty-city", "almaty-oblast", "astana", "atyrau",
        "central", "east-kazakhstan", "joint", "karaganda", "kostanay", "kyzylorda",
        "mangystau", "north-kazakhstan", "pavlodar", "shymkent", "turkestan", "ulytau",
        "west-kazakhstan", "zhambyl", "zhetisu",
    )
)
ALL_SCOPES: tuple[str, ...] = DEFAULT_SCOPES + LOCAL_SCOPES


@dataclass(frozen=True)
class Settings:
    corpus_root: Path
    github_org: str = "kazakhstan-law"
    host: str = "127.0.0.1"
    port: int = 8000
    public_url: str = "http://127.0.0.1:8000/mcp"
    trusted_proxies: frozenset[str] = field(default_factory=lambda: frozenset({"100.64.0.1"}))
    log_path: Path | None = None
    ip_salt: str = ""
    rate_calls: int = 60
    rate_window_s: float = 600.0
    max_parallel: int = 6
    subprocess_timeout_s: float = 20.0
    head_ttl_s: float = 60.0
    remote_template: str = "https://github.com/{org}/{scope}.git"

    @classmethod
    def from_env(cls) -> Settings:
        env = os.environ
        log = env.get("KZLAW_LOG_PATH")
        proxies = env.get("KZLAW_TRUSTED_PROXIES", "100.64.0.1")
        return cls(
            corpus_root=Path(env.get("KZLAW_CORPUS_ROOT", "/corpus")),
            github_org=env.get("KZLAW_GITHUB_ORG", "kazakhstan-law"),
            host=env.get("KZLAW_HOST", "127.0.0.1"),
            port=int(env.get("KZLAW_PORT", "8000")),
            public_url=env.get("KZLAW_PUBLIC_URL", "http://127.0.0.1:8000/mcp"),
            trusted_proxies=frozenset(p.strip() for p in proxies.split(",") if p.strip()),
            log_path=Path(log) if log else None,
            ip_salt=env.get("KZLAW_IP_SALT", ""),
            rate_calls=int(env.get("KZLAW_RATE_CALLS", "60")),
            rate_window_s=float(env.get("KZLAW_RATE_WINDOW_S", "600")),
            max_parallel=int(env.get("KZLAW_MAX_PARALLEL", "6")),
            subprocess_timeout_s=float(env.get("KZLAW_SUBPROCESS_TIMEOUT_S", "20")),
            head_ttl_s=float(env.get("KZLAW_HEAD_TTL_S", "60")),
            remote_template=env.get(
                "KZLAW_REMOTE_TEMPLATE", "https://github.com/{org}/{scope}.git"
            ),
        )
```

- [ ] **Step 4: Write the fixture corpus in `tests/conftest.py`**

Two repos that reproduce the corpus shapes the tools depend on (spec §3.2): a split act whose part is renamed between versions (КоАП, anchors), a point-based order without anchors where one point label repeats (ПДД), the Constitution at `00-constitution/`, UTC-midnight commit dates and `Cause-Act-*` trailers.

```python
"""A tiny corpus with the shapes the tools depend on (spec §3.2)."""

from __future__ import annotations

import os
import shutil
import subprocess
from pathlib import Path

import pytest

from kzlaw_mcp.config import Settings

KOAP = "02-codes/2014/0705-ob-administrativnykh-pravonarusheniiakh-81245"
KOAP_CODE = "81245"
PDD = "07-ministerial/103003000000-qriim/2023/0630-ob-utverzhdenii-pravil-dorozhnogo-dvizheniia-183572"
PDD_CODE = "183572"
CONST_CODE = "1005029"


def meta(code: str, title: str, requisite: str) -> str:
    return (
        f"act_code: '{code}'\n"
        f"requisite: {requisite}\n"
        f"title:\n  rus: {title}\n  kaz: {title} (kaz)\n"
    )


def commit(repo: Path, date: str, files: dict[str, str | None], subject: str,
           trailers: dict[str, str] | None = None) -> None:
    for rel, content in files.items():
        path = repo / rel
        if content is None:
            shutil.rmtree(path) if path.is_dir() else path.unlink()
        else:
            path.parent.mkdir(parents=True, exist_ok=True)
            path.write_text(content, encoding="utf-8")
    subprocess.run(["git", "add", "-A"], cwd=repo, check=True)
    body = "\n".join(f"{k}: {v}" for k, v in (trailers or {}).items())
    message = f"{subject}\n\n{body}" if body else subject
    stamp = f"{date}T00:00:00Z"
    env = {
        **os.environ,
        "GIT_AUTHOR_NAME": "corpus", "GIT_AUTHOR_EMAIL": "corpus@example.invalid",
        "GIT_COMMITTER_NAME": "corpus", "GIT_COMMITTER_EMAIL": "corpus@example.invalid",
        "GIT_AUTHOR_DATE": stamp, "GIT_COMMITTER_DATE": stamp,
    }
    subprocess.run(["git", "commit", "-q", "-m", message], cwd=repo, env=env, check=True)


def init(repo: Path) -> Path:
    repo.mkdir(parents=True)
    subprocess.run(["git", "init", "-q", "-b", "main"], cwd=repo, check=True)
    return repo


ART_593 = '<a id="st593"></a>\n\n### Статья 593. Нарушение правил проезда\n\n1. Текст статьи 593.\n'


def koap_part(parts_3: str) -> str:
    return (
        "↑ [Вся редакция](../rus.md)\n\n"
        "## Глава 30. Административные правонарушения на транспорте\n\n"
        '<a id="st592"></a>\n\n'
        "### Статья 592. Превышение установленной скорости движения\n\n"
        "1. Превышение водителями установленной скорости движения на величину "
        "от десяти до двадцати километров в час -\n\nвлечет предупреждение.\n\n"
        f"{parts_3}\n"
        + ART_593
    )


KOAP_2022 = koap_part(
    "3. Те же действия, совершенные на величину от сорока и более километров в час, -\n\n"
    "влекут штраф в размере двадцати месячных расчетных показателей.\n"
)
KOAP_2024 = koap_part(
    "3. Те же действия, совершенные на величину от сорока до шестидесяти километров в час, -\n\n"
    "влекут штраф в размере двадцати месячных расчетных показателей.\n\n"
    "3-1. Те же действия, совершенные на величину от шестидесяти и более километров в час, -\n\n"
    "влекут штраф в размере сорока месячных расчетных показателей.\n\n"
    "> *Сноска. Статья 592 дополнена частью 3-1 Законом РК от 03.10.2024 № 131-VIII.*\n"
)


def pdd_text(with_scooters: bool) -> str:
    scooters = (
        "168-1. Водители электрических самокатов двигаются по велосипедной дорожке.\n\n"
        "Лицам, не достигшим восемнадцати лет, движение по проезжей части запрещается.\n\n"
        "> *Сноска. Глава дополнена пунктом 168-1 приказом от 31.08.2023 № 671.*\n\n"
        if with_scooters else ""
    )
    return (
        "# Об утверждении Правил дорожного движения\n\n"
        "## Глава 1. Общие положения\n\n"
        "1. Настоящие Правила устанавливают порядок дорожного движения.\n\n"
        "## Глава 24. Движение средств индивидуальной мобильности\n\n"
        "*167. Исключен приказом от 31.08.2023 № 671.*\n\n"
        + scooters
        + "169. Средства индивидуальной мобильности не перевозят пассажиров.\n\n"
        "## Разметка дорожная\n\n"
        "## Глава 1. Горизонтальная разметка\n\n"
        "1. Горизонтальная разметка наносится краской.\n"
    )


@pytest.fixture(scope="session")
def corpus_root(tmp_path_factory) -> Path:
    root = tmp_path_factory.mktemp("corpus")

    codes = init(root / "codes")
    commit(codes, "1995-08-30", {
        "00-constitution/rus.md": '# Конституция\n\n<a id="st1"></a>\n\n### Статья 1\n\n1. Республика.\n',
        "00-constitution/meta.yaml": meta(CONST_CODE, "Конституция Республики Казахстан", "Конституция"),
    }, "Конституция")
    koap_meta = meta(KOAP_CODE, "Об административных правонарушениях",
                     "Кодекс Республики Казахстан от 5 июля 2014 года № 235-V.")
    commit(codes, "2022-01-10", {
        f"{KOAP}/meta.yaml": koap_meta,
        f"{KOAP}/rus.md": "# Об административных правонарушениях\n\n| [Глава 30](rus/sec002-ch010.md) |\n",
        f"{KOAP}/rus/sec002-ch010.md": KOAP_2022,
        f"{KOAP}/kaz.md": "# ӘКІМШІЛІК ҚҰҚЫҚБҰЗУШЫЛЫҚ ТУРАЛЫ\n\nЖылдамдықты асыру.\n",
    }, "№100-VII О внесении изменений в Кодекс", {
        "Cause-Act-Code": "999100", "Cause-Act-Requisite": "Закон РК от 10 января 2022 года № 100-VII",
        "Acts-Changed": "1",
    })
    commit(codes, "2024-10-03", {
        f"{KOAP}/rus/sec002-ch010.md": None,
        f"{KOAP}/rus/sec002-ch030.md": KOAP_2024,
        f"{KOAP}/rus.md": "# Об административных правонарушениях\n\n| [Глава 30](rus/sec002-ch030.md) |\n",
    }, "№131-VIII О внесении изменений и дополнений в Кодекс", {
        "Cause-Act-Code": "999131", "Cause-Act-Requisite": "Закон РК от 3 октября 2024 года № 131-VIII",
        "Acts-Changed": "1",
    })

    ministerial = init(root / "ministerial")
    pdd_meta = meta(PDD_CODE, "Об утверждении Правил дорожного движения",
                    "Приказ Министра внутренних дел РК от 30 июня 2023 года № 534")
    commit(ministerial, "2023-06-30", {
        f"{PDD}/meta.yaml": pdd_meta, f"{PDD}/rus.md": pdd_text(False),
    }, "3 акта без указанного основания")
    commit(ministerial, "2023-08-31", {f"{PDD}/rus.md": pdd_text(True)},
           "№671 О внесении изменений в приказ № 534", {
               "Cause-Act-Code": "999671",
               "Cause-Act-Requisite": "Приказ Министра внутренних дел РК от 31 августа 2023 года № 671",
               "Acts-Changed": "1",
           })
    return root


@pytest.fixture
def settings(corpus_root, tmp_path) -> Settings:
    return Settings(corpus_root=corpus_root, log_path=tmp_path / "calls.jsonl", ip_salt="test")


@pytest.fixture
def anyio_backend():
    return "asyncio"
```

- [ ] **Step 5: Write the failing test `tests/test_gitio.py`**

```python
import pytest

from conftest import KOAP
from kzlaw_mcp.gitio import CommandError, Git, run


def test_run_rejects_unexpected_exit(tmp_path):
    with pytest.raises(CommandError):
        run(["git", "rev-parse", "HEAD"], tmp_path, timeout=5)


def test_run_truncates(tmp_path):
    out = run(["python3", "-c", "print('x' * 1000)"], tmp_path, timeout=5, max_bytes=10)
    assert out.truncated and out.text == "x" * 10


def test_git_reads_objects_at_a_revision(corpus_root):
    g = Git(corpus_root / "codes", timeout=10)
    head = g.head()
    old = g.rev_before("2023-01-01")
    assert old and old != head
    assert g.rev_before("1990-01-01") is None
    assert g.commit_date(old) == "2022-01-10"
    assert f"{KOAP}/rus/sec002-ch010.md" in g.ls_tree(old, f"{KOAP}/rus")
    assert f"{KOAP}/rus/sec002-ch010.md" not in g.ls_tree(head, f"{KOAP}/rus")
    assert "от сорока и более" in g.blob(old, f"{KOAP}/rus/sec002-ch010.md")
    assert g.blob_size(head, f"{KOAP}/rus.md") > 0


def test_git_grep_returns_paths_and_lines(corpus_root):
    g = Git(corpus_root / "codes", timeout=10)
    hits = g.grep(g.head(), '<a id="st592"></a>', [f"{KOAP}/rus.md", f"{KOAP}/rus"], fixed=True)
    assert hits == [(f"{KOAP}/rus/sec002-ch030.md", 5)]
    assert g.grep(g.head(), "no such text", [f"{KOAP}/rus"], fixed=True) == []
```

Add `tests/__init__.py`? No — pytest's rootdir conftest import works with `from conftest import …` because `tests/` is on `sys.path` in rootdir-less mode; if the import fails, add `pythonpath = ["tests"]` to `[tool.pytest.ini_options]`.

- [ ] **Step 6: Run to see it fail**

Run: `uv run pytest tests/test_gitio.py -v`
Expected: FAIL — `ModuleNotFoundError: No module named 'kzlaw_mcp.gitio'`.

- [ ] **Step 7: Write `src/kzlaw_mcp/gitio.py`**

```python
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


def run(args: list[str], cwd: Path, *, timeout: float, max_bytes: int = 2_000_000,
        ok: tuple[int, ...] = (0,)) -> Output:
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

    def __init__(self, repo: Path, timeout: float):
        self.repo = repo
        self.timeout = timeout

    def _git(self, *args: str, ok: tuple[int, ...] = (0,), max_bytes: int = 2_000_000) -> Output:
        return run(["git", *args], self.repo, timeout=self.timeout, ok=ok, max_bytes=max_bytes)

    def head(self) -> str:
        return self._git("rev-parse", "HEAD").text.strip()

    def rev_before(self, date: str) -> str | None:
        """The last commit on or before `date` (YYYY-MM-DD). Corpus commits are UTC midnight."""
        return self._git("rev-list", "-1", f"--before={date}T23:59:59Z", "HEAD").text.strip() or None

    def commit_date(self, sha: str) -> str:
        return self._git("log", "-1", "--format=%cs", sha).text.strip()

    def ls_tree(self, sha: str, *paths: str) -> list[str]:
        out = self._git("ls-tree", "-r", "--name-only", sha, "--", *paths, max_bytes=64_000_000)
        return [line for line in out.text.splitlines() if line]

    def blob(self, sha: str, path: str) -> str:
        return self._git("cat-file", "blob", f"{sha}:{path}", max_bytes=16_000_000).text

    def blob_size(self, sha: str, path: str) -> int:
        return int(self._git("cat-file", "-s", f"{sha}:{path}").text.strip())

    def grep(self, sha: str, pattern: str, paths: list[str], *, fixed: bool) -> list[tuple[str, int]]:
        """(path, line) of every match of `pattern` in `paths` at `sha`."""
        flag = "-F" if fixed else "-E"
        out = self._git("grep", "-n", flag, "-e", pattern, sha, "--", *paths, ok=(0, 1))
        hits = []
        for line in out.text.splitlines():
            _, path, lineno, _ = line.split(":", 3)  # "<sha>:<path>:<line>:<text>"
            hits.append((path, int(lineno)))
        return hits

    def log(self, *args: str) -> str:
        return self._git("log", *args, max_bytes=1_000_000).text
```

- [ ] **Step 8: Run tests, lint, commit, push**

Run: `uv run pytest tests/test_gitio.py -v` → PASS. Then `uv run ruff check . && uv run ruff format .`

```bash
git add -A && git commit -m "feat: scaffold, settings, git runner, fixture corpus" && git push
```

---

### Task 2: Text locators

**Files:**
- Create: `src/kzlaw_mcp/locate.py`, `tests/test_locate.py`

**Interfaces:**
- Produces: `ANCHOR_LINE`, `ANCHOR_ID`, `POINT_LABEL`, `POINT_START`, `HEADING` (compiled regexes); `Span(start: int, end: int, text: str, heading: str | None)` (1-based inclusive lines); `LineContext(anchor, point, heading)`; `article_span(text, anchor) -> Span | None`; `point_spans(text, label, *, within: Span | None = None) -> list[Span]`; `line_context(lines: list[str], lineno: int) -> LineContext`; `headings(text) -> list[str]`

- [ ] **Step 1: Write the failing test**

```python
from conftest import KOAP_2024, pdd_text
from kzlaw_mcp.locate import ANCHOR_ID, POINT_LABEL, article_span, line_context, point_spans


def test_article_span_runs_to_the_next_article():
    span = article_span(KOAP_2024, "st592")
    assert span.heading == "Статья 592. Превышение установленной скорости движения"
    assert "3-1. Те же действия" in span.text and "Сноска" in span.text
    assert "Статья 593" not in span.text
    assert span.text.splitlines()[0] == '<a id="st592"></a>'


def test_article_span_missing_anchor():
    assert article_span(KOAP_2024, "st9999") is None


def test_point_inside_an_article():
    art = article_span(KOAP_2024, "st592")
    [part] = point_spans(KOAP_2024, "3-1", within=art)
    assert part.text.startswith("3-1. Те же действия")
    assert "сорока месячных" in part.text
    assert "Статья 593" not in part.text


def test_point_label_repeats_across_annexes():
    spans = point_spans(pdd_text(True), "1")
    assert [s.heading for s in spans] == ["Глава 1. Общие положения", "Глава 1. Горизонтальная разметка"]


def test_point_span_keeps_continuation_and_footnote():
    [span] = point_spans(pdd_text(True), "168-1")
    assert "восемнадцати лет" in span.text and "№ 671" in span.text
    assert "169." not in span.text


def test_line_context_inside_article_part():
    lines = KOAP_2024.split("\n")
    lineno = next(i for i, l in enumerate(lines, 1) if l.startswith("3-1."))
    ctx = line_context(lines, lineno + 2)  # the "влекут штраф" continuation line
    assert (ctx.anchor, ctx.point) == ("st592", "3-1")
    assert ctx.heading.startswith("Статья 592")


def test_line_context_without_anchors():
    lines = pdd_text(True).split("\n")
    lineno = next(i for i, l in enumerate(lines, 1) if "восемнадцати" in l)
    ctx = line_context(lines, lineno)
    assert (ctx.anchor, ctx.point, ctx.heading) == (None, "168-1", "Глава 24. Движение средств индивидуальной мобильности")


def test_chapter_heading_resets_the_anchor():
    text = '<a id="st1"></a>\n\n### Статья 1\n\nтекст\n\n## Глава 2\n\nвводный абзац\n'
    lines = text.split("\n")
    assert line_context(lines, len(lines) - 1).anchor is None


def test_grammar():
    for ok in ("st592", "st62-1", "an3_st1", "st62_p2", "st62_p2_sp3"):
        assert ANCHOR_ID.match(ok)
    for bad in ("592", "st", "../st1", "st1;rm", "ST592"):
        assert not ANCHOR_ID.match(bad)
    assert POINT_LABEL.match("168-1") and not POINT_LABEL.match("1.2; x")
```

- [ ] **Step 2: Run to see it fail**

Run: `uv run pytest tests/test_locate.py -v` → FAIL, `ModuleNotFoundError`.

- [ ] **Step 3: Write `src/kzlaw_mcp/locate.py`**

```python
"""Find an article, a point, or the context of a line inside one rendered act file.

Pure functions over text. Articles carry explicit anchors (`<a id="st592"></a>` on its own
line, then the heading). Many orders (e.g. the traffic rules) have no anchors at all: their
points are lines starting with a label such as `168-1. `, and a repealed point is italic
(`*167. Исключен …*`). Annexes restart point numbering, so a label can repeat in one file.
"""

from __future__ import annotations

import re
from dataclasses import dataclass

ANCHOR_LINE = re.compile(r'^<a id="([^"]+)"></a>$')
_N = r"[0-9]+(?:-[0-9]+)*"
ANCHOR_ID = re.compile(rf"^(?:an{_N}_)?st{_N}(?:_p{_N})?(?:_sp{_N})?$")
POINT_LABEL = re.compile(rf"^{_N}$")
POINT_START = re.compile(rf"^\*?({_N})\.\s")
HEADING = re.compile(r"^(#{1,6})\s+(.*\S)")


@dataclass(frozen=True)
class Span:
    start: int  # 1-based, first line
    end: int  # 1-based, last line, inclusive
    text: str
    heading: str | None


@dataclass(frozen=True)
class LineContext:
    anchor: str | None
    point: str | None
    heading: str | None


def _heading(line: str) -> tuple[int, str] | None:
    m = HEADING.match(line)
    return (len(m.group(1)), m.group(2)) if m else None


def _span(lines: list[str], i: int, j: int, heading: str | None) -> Span:
    while j > i + 1 and not lines[j - 1].strip():
        j -= 1
    return Span(i + 1, j, "\n".join(lines[i:j]), heading)


def headings(text: str) -> list[str]:
    return [line for line in text.split("\n") if HEADING.match(line)]


def article_span(text: str, anchor: str) -> Span | None:
    """From the anchor line to the next anchor that is not its child, or a shallower heading."""
    lines = text.split("\n")
    try:
        i = lines.index(f'<a id="{anchor}"></a>')
    except ValueError:
        return None
    level, title = None, None
    j = i + 1
    while j < len(lines):
        m = ANCHOR_LINE.match(lines[j])
        if m and not m.group(1).startswith(anchor + "_"):
            break
        h = _heading(lines[j])
        if h:
            if level is None:
                level, title = h
            elif h[0] <= level:
                break
        j += 1
    return _span(lines, i, j, title)


def point_spans(text: str, label: str, *, within: Span | None = None) -> list[Span]:
    """Every point `label` in `text` (or inside `within`), each up to the next point or heading."""
    lines = text.split("\n")
    lo, hi = (within.start - 1, within.end) if within else (0, len(lines))
    found, heading = [], None
    for i in range(lo, hi):
        h = _heading(lines[i])
        if h:
            heading = h[1]
            continue
        m = POINT_START.match(lines[i])
        if not m or m.group(1) != label:
            continue
        j = i + 1
        while j < hi and not (
            POINT_START.match(lines[j]) or _heading(lines[j]) or ANCHOR_LINE.match(lines[j])
        ):
            j += 1
        found.append(_span(lines, i, j, heading))
    return found


def line_context(lines: list[str], lineno: int) -> LineContext:
    """The anchor, point label and heading in force at 1-based line `lineno`.

    A heading directly preceded by an anchor is that article's heading; any other heading
    opens a new container and clears the anchor.
    """
    anchor = point = heading = None
    prev = ""
    for line in lines[:lineno]:
        if m := ANCHOR_LINE.match(line):
            anchor, point = m.group(1), None
        elif h := _heading(line):
            heading, point = h[1], None
            if not ANCHOR_LINE.match(prev):
                anchor = None
        elif m := POINT_START.match(line):
            point = m.group(1)
        if line.strip():
            prev = line
    return LineContext(anchor, point, heading)
```

- [ ] **Step 4: Run tests** — `uv run pytest tests/test_locate.py -v` → PASS.

- [ ] **Step 5: Commit, push**

```bash
git add -A && git commit -m "feat: article, point and line-context locators" && git push
```

---

### Task 3: Corpus — act index, metadata, citation links

**Files:**
- Create: `src/kzlaw_mcp/corpus.py`, `tests/test_corpus.py`

**Interfaces:**
- Consumes: `Settings`, `ALL_SCOPES`, `Git`
- Produces:
  - `InputError(ValueError)` — bad tool input; its message is shown to the model
  - `ActRef(code: str, scope: str, path: str)` — `path` is the act directory relative to its repo
  - `Corpus(settings)` with `.settings`, `scopes() -> list[str]`, `git(scope) -> Git`, `head(scope) -> str`, `find(act_code) -> ActRef`, `meta(ref, sha) -> dict`, `lang_files(ref, sha, lang) -> list[str]`, `citation_url(ref, sha, file, *, anchor, lines, size) -> str`, `commit_url(scope, sha) -> str`
  - `check_lang(lang) -> str`, `title_of(meta, lang) -> str`, `locator_label(anchor, point) -> str`, `RENDER_LIMIT = 384 * 1024`

- [ ] **Step 1: Write the failing test**

```python
import pytest

from conftest import CONST_CODE, KOAP, KOAP_CODE, PDD_CODE
from kzlaw_mcp.corpus import Corpus, InputError, locator_label


def test_scopes_are_the_repos_on_disk(settings):
    assert Corpus(settings).scopes() == ["codes", "ministerial"]


def test_find_by_code(settings):
    c = Corpus(settings)
    assert c.find(KOAP_CODE).path == KOAP and c.find(KOAP_CODE).scope == "codes"
    assert c.find(PDD_CODE).scope == "ministerial"
    assert c.find(CONST_CODE).path == "00-constitution"


@pytest.mark.parametrize("bad", ["../etc", "81245/..", "", "1" * 13, "812 45"])
def test_find_rejects_non_codes(settings, bad):
    with pytest.raises(InputError):
        Corpus(settings).find(bad)


def test_find_unknown_code(settings):
    with pytest.raises(InputError, match="not in the corpus"):
        Corpus(settings).find("424242")


def test_files_follow_the_revision(settings):
    c = Corpus(settings)
    ref = c.find(KOAP_CODE)
    g = c.git("codes")
    old = g.rev_before("2023-01-01")
    assert c.lang_files(ref, old, "rus") == [f"{KOAP}/rus.md", f"{KOAP}/rus/sec002-ch010.md"]
    assert c.lang_files(ref, c.head("codes"), "rus")[1].endswith("sec002-ch030.md")
    assert c.lang_files(ref, c.head("codes"), "kaz") == [f"{KOAP}/kaz.md"]
    assert c.meta(ref, old)["requisite"].startswith("Кодекс")


def test_citation_urls(settings):
    c = Corpus(settings)
    ref = c.find(KOAP_CODE)
    base = f"https://github.com/kazakhstan-law/codes/blob/abc/{KOAP}/rus/x.md"
    f = f"{KOAP}/rus/x.md"
    assert c.citation_url(ref, "abc", f, anchor="st592", lines=(5, 20), size=1000) == base + "#st592"
    # too large for GitHub to render: anchors do not exist, fall back to line numbers
    assert c.citation_url(ref, "abc", f, anchor="st592", lines=(5, 20), size=500_000) == (
        base + "?plain=1#L5-L20"
    )
    assert c.citation_url(ref, "abc", f, anchor=None, lines=(7, 9), size=10) == base + "?plain=1#L7-L9"


def test_labels():
    assert locator_label("st592", None) == "ст. 592"
    assert locator_label("st592", "3-1") == "ст. 592, ч. 3-1"
    assert locator_label(None, "168-1") == "п. 168-1"
    assert locator_label("an3_st1", None) == "прил. 3, ст. 1"
```

- [ ] **Step 2: Run to see it fail** — `uv run pytest tests/test_corpus.py -v` → FAIL.

- [ ] **Step 3: Write `src/kzlaw_mcp/corpus.py`**

```python
"""The corpus as a set of git clones: act index by code, metadata, files, citation links."""

from __future__ import annotations

import re
import threading
import time
from dataclasses import dataclass
from urllib.parse import quote

import yaml

from kzlaw_mcp.config import ALL_SCOPES, Settings
from kzlaw_mcp.gitio import Git

ACT_CODE = re.compile(r"^[0-9]{1,12}$")
CODE_IN_PATH = re.compile(r"-([0-9]+)/meta\.yaml$")
# GitHub stops rendering Markdown somewhere between 390 and 432 KB; without rendering no
# anchor exists, so larger files are cited by line numbers in the plain view.
RENDER_LIMIT = 384 * 1024
LANGS = ("rus", "kaz")


class InputError(ValueError):
    """Bad tool input. The message is returned to the calling model."""


@dataclass(frozen=True)
class ActRef:
    code: str
    scope: str
    path: str


def check_lang(lang: str) -> str:
    if lang not in LANGS:
        raise InputError("lang must be 'rus' or 'kaz'")
    return lang


def title_of(meta: dict, lang: str) -> str:
    title = meta.get("title") or {}
    return title.get(lang) or title.get("rus") or ""


def locator_label(anchor: str | None, point: str | None) -> str:
    parts = []
    if anchor and (m := re.match(r"^(?:an([0-9-]+)_)?st([0-9-]+)", anchor)):
        if m.group(1):
            parts.append(f"прил. {m.group(1)}")
        parts.append(f"ст. {m.group(2)}")
    if point:
        parts.append(("ч. " if parts else "п. ") + point)
    return ", ".join(parts)


class Corpus:
    def __init__(self, settings: Settings):
        self.settings = settings
        self._index: dict[str, ActRef] = {}
        self._heads: dict[str, str] = {}
        self._checked = float("-inf")
        self._lock = threading.Lock()

    def scopes(self) -> list[str]:
        root = self.settings.corpus_root
        return [s for s in ALL_SCOPES if (root / s / ".git").exists()]

    def git(self, scope: str) -> Git:
        return Git(self.settings.corpus_root / scope, self.settings.subprocess_timeout_s)

    def head(self, scope: str) -> str:
        self._refresh()
        return self._heads[scope]

    def find(self, act_code: str) -> ActRef:
        code = str(act_code).strip()
        if not ACT_CODE.match(code):
            raise InputError(f"act_code must be the act's numeric code, got {act_code!r}")
        self._refresh()
        try:
            return self._index[code]
        except KeyError:
            raise InputError(
                f"act {code} is not in the corpus (only acts in force are indexed); use search"
            ) from None

    def meta(self, ref: ActRef, sha: str) -> dict:
        return yaml.safe_load(self.git(ref.scope).blob(sha, f"{ref.path}/meta.yaml")) or {}

    def lang_files(self, ref: ActRef, sha: str, lang: str) -> list[str]:
        """`<act>/<lang>.md` first, then its parts `<act>/<lang>/*.md`, as they are at `sha`."""
        main = f"{ref.path}/{lang}.md"
        files = self.git(ref.scope).ls_tree(sha, main, f"{ref.path}/{lang}")
        return sorted(files, key=lambda f: (f != main, f))

    def citation_url(self, ref: ActRef, sha: str, file: str, *, anchor: str | None,
                     lines: tuple[int, int] | None, size: int) -> str:
        base = f"https://github.com/{self.settings.github_org}/{ref.scope}/blob/{sha}/{quote(file)}"
        if anchor and size <= RENDER_LIMIT:
            return f"{base}#{anchor}"
        if lines:
            return f"{base}?plain=1#L{lines[0]}-L{lines[1]}"
        return base

    def commit_url(self, scope: str, sha: str) -> str:
        return f"https://github.com/{self.settings.github_org}/{scope}/commit/{sha}"

    def _refresh(self) -> None:
        with self._lock:
            if time.monotonic() - self._checked < self.settings.head_ttl_s:
                return
            for scope in self.scopes():
                head = self.git(scope).head()
                if self._heads.get(scope) != head:
                    self._reindex(scope, head)
                    self._heads[scope] = head
            self._checked = time.monotonic()

    def _reindex(self, scope: str, head: str) -> None:
        g = self.git(scope)
        index = {code: ref for code, ref in self._index.items() if ref.scope != scope}
        for path in g.ls_tree(head):
            if not path.endswith("meta.yaml"):
                continue
            act_dir = path.rsplit("/", 1)[0]
            if m := CODE_IN_PATH.search(path):
                code = m.group(1)
            else:  # the Constitution: 00-constitution/meta.yaml
                code = str((yaml.safe_load(g.blob(head, path)) or {}).get("act_code", ""))
            if code:
                index[code] = ActRef(code, scope, act_dir)
        self._index = index
```

- [ ] **Step 4: Run tests** — `uv run pytest tests/test_corpus.py -v` → PASS.

- [ ] **Step 5: Measure the index on the real corpus** (read-only on `~/kazakhstan-law-0916`)

```bash
uv run python -c "
import time; from pathlib import Path
from kzlaw_mcp.config import Settings; from kzlaw_mcp.corpus import Corpus
c = Corpus(Settings(corpus_root=Path.home()/'kazakhstan-law-0916'))
t = time.monotonic(); r = c.find('183572'); print(r, f'{time.monotonic()-t:.1f}s', len(c._index))"
```
Expected: the ПДД `ActRef` in `ministerial`, a few seconds, an index size in the tens of thousands. Record the figure in the commit message. If it is over ~30 s, stop and report: the index would then need building once at startup in the background instead of lazily.

- [ ] **Step 6: Commit, push**

```bash
git add -A && git commit -m "feat: corpus index, metadata and sha-pinned citation links" && git push
```

---

### Task 4: `search`

**Files:**
- Create: `src/kzlaw_mcp/search.py`, `tests/test_search.py`

**Interfaces:**
- Consumes: `Corpus`, `InputError`, `check_lang`, `title_of`, `line_context`, `run`, `CommandError`, `DEFAULT_SCOPES`, `ALL_SCOPES`
- Produces: `search(corpus, query: str, lang: str = "rus", scopes: list[str] | None = None, limit: int = 20) -> dict` with keys `query, lang, scopes, missing_scopes, sha: {scope: sha}, truncated: bool, acts: [{act_code, scope, title, requisite, hits: [{file, line, anchor, point, heading, text}]}], hint`

- [ ] **Step 1: Write the failing test**

```python
import pytest

from conftest import KOAP_CODE, PDD_CODE
from kzlaw_mcp.corpus import Corpus, InputError
from kzlaw_mcp.search import search


def test_finds_an_article_case_insensitively(settings):
    res = search(Corpus(settings), "превышение установленной скорости")
    [act] = res["acts"]
    assert act["act_code"] == KOAP_CODE and act["title"] == "Об административных правонарушениях"
    hit = act["hits"][0]
    assert hit["anchor"] == "st592" and hit["heading"].startswith("Статья 592")
    assert hit["file"].endswith("rus/sec002-ch030.md")  # current revision only


def test_hits_without_anchors_carry_the_point(settings):
    res = search(Corpus(settings), "восемнадцати лет")
    [act] = res["acts"]
    assert act["act_code"] == PDD_CODE
    assert act["hits"][0]["point"] == "168-1" and act["hits"][0]["anchor"] is None


def test_kazakh_is_case_insensitive(settings):
    res = search(Corpus(settings), "әкімшілік", lang="kaz")
    assert [a["act_code"] for a in res["acts"]] == [KOAP_CODE]


def test_codes_rank_before_ministerial(settings):
    res = search(Corpus(settings), "километров|самокат")
    assert [a["scope"] for a in res["acts"]] == ["codes", "ministerial"]


def test_limit_truncates(settings):
    res = search(Corpus(settings), "километров|самокат", limit=1)
    assert len(res["acts"]) == 1 and res["truncated"] is True


def test_missing_scope_is_reported(settings):
    res = search(Corpus(settings), "самокат", scopes=["ministerial", "local-abai"])
    assert res["missing_scopes"] == ["local-abai"] and res["acts"]


def test_no_hits_gives_a_hint(settings):
    res = search(Corpus(settings), "гиппопотам")
    assert res["acts"] == [] and "wording" in res["hint"]


@pytest.mark.parametrize("query", ["--files", "-e x", "--pre=sh"])
def test_option_like_queries_are_patterns(settings, query):
    assert search(Corpus(settings), query)["acts"] == []  # searched as text, nothing matches


@pytest.mark.parametrize("query", ["(", "x", "a" * 201])
def test_bad_queries(settings, query):
    with pytest.raises(InputError):
        search(Corpus(settings), query)


def test_bad_scope(settings):
    with pytest.raises(InputError, match="unknown scope"):
        search(Corpus(settings), "самокат", scopes=["../etc"])
```

- [ ] **Step 2: Run to see it fail** — `uv run pytest tests/test_search.py -v` → FAIL.

- [ ] **Step 3: Write `src/kzlaw_mcp/search.py`**

```python
"""search: ripgrep over the working trees of the current revision."""

from __future__ import annotations

import json
from pathlib import Path

import yaml

from kzlaw_mcp.config import ALL_SCOPES, DEFAULT_SCOPES
from kzlaw_mcp.corpus import Corpus, InputError, check_lang, title_of
from kzlaw_mcp.gitio import CommandError, run
from kzlaw_mcp.locate import line_context

MAX_QUERY = 200
MAX_HITS = 20
PER_FILE = 3
MAX_LINE = 300
NO_HITS = (
    "No matches. Try other wording: legal terms instead of colloquial ones, word stems "
    "('самокат' also matches 'самокатов'), or alternatives joined with '|'."
)
HINT = "Open a passage with read(act_code, anchor=...) or read(act_code, point=...)."


def _act_dir(rel: str, lang: str) -> str:
    parent, name = rel.rsplit("/", 1)
    if name == f"{lang}.md":
        return parent
    return parent.rsplit("/", 1)[0]  # <act>/<lang>/<part>.md


def search(corpus: Corpus, query: str, lang: str = "rus", scopes: list[str] | None = None,
           limit: int = MAX_HITS) -> dict:
    query = (query or "").strip()
    if not 2 <= len(query) <= MAX_QUERY:
        raise InputError(f"query must be 2..{MAX_QUERY} characters")
    lang = check_lang(lang)
    wanted = list(dict.fromkeys(scopes)) if scopes else list(DEFAULT_SCOPES)
    unknown = [s for s in wanted if s not in ALL_SCOPES]
    if unknown:
        raise InputError(f"unknown scope(s) {unknown}; valid: {', '.join(ALL_SCOPES)}")
    available = corpus.scopes()
    missing = [s for s in wanted if s not in available]
    wanted = [s for s in wanted if s in available]
    if not wanted:
        raise InputError("none of the requested scopes is available on this server")
    limit = max(1, min(int(limit), MAX_HITS))
    root: Path = corpus.settings.corpus_root
    args = [
        "rg", "--json", "--ignore-case", "--max-count", str(PER_FILE), "--max-columns", "2000",
        "--glob", f"**/{lang}.md", "--glob", f"**/{lang}/*.md",
        "-e", query, "--", *wanted,
    ]
    try:
        out = run(args, root, timeout=corpus.settings.subprocess_timeout_s,
                  max_bytes=4_000_000, ok=(0, 1))
    except CommandError as exc:
        raise InputError(f"search failed (is the regex valid?): {exc}") from exc

    by_act: dict[tuple[str, str], list[tuple[str, int, str]]] = {}
    for line in out.text.splitlines():
        try:
            event = json.loads(line)
        except json.JSONDecodeError:
            continue  # the cut-off last line of truncated output
        if event.get("type") != "match":
            continue
        data = event["data"]
        path = data["path"].get("text")
        if not path:
            continue
        scope, rel = path.split("/", 1)
        by_act.setdefault((scope, _act_dir(rel, lang)), []).append(
            (rel, data["line_number"], data["lines"].get("text", "").strip())
        )

    order = {s: i for i, s in enumerate(wanted)}
    ranked = sorted(by_act.items(), key=lambda kv: (order[kv[0][0]], -len(kv[1]), kv[0][1]))
    acts, used, file_lines = [], 0, {}
    for (scope, act_dir), hits in ranked:
        if used >= limit:
            break
        meta = yaml.safe_load((root / scope / act_dir / "meta.yaml").read_text("utf-8")) or {}
        items = []
        for rel, lineno, text in sorted(hits)[: limit - used]:
            if rel not in file_lines:
                file_lines[rel] = (root / scope / rel).read_text("utf-8").split("\n")
            ctx = line_context(file_lines[rel], lineno)
            items.append({
                "file": rel, "line": lineno, "anchor": ctx.anchor, "point": ctx.point,
                "heading": ctx.heading, "text": text[:MAX_LINE],
            })
        used += len(items)
        acts.append({
            "act_code": str(meta.get("act_code", "")), "scope": scope,
            "title": title_of(meta, lang), "requisite": meta.get("requisite", ""), "hits": items,
        })
    return {
        "query": query, "lang": lang, "scopes": wanted, "missing_scopes": missing,
        "sha": {s: corpus.head(s) for s in wanted},
        "truncated": out.truncated or len(acts) < len(ranked)
        or sum(len(h) for _, h in ranked) > used,
        "acts": acts,
        "hint": HINT if acts else NO_HITS,
    }
```

Note on `test_bad_queries["x"]`: one character is below the 2-char floor; `"("` is an invalid regex, `rg` exits 2, which surfaces as `InputError`.

- [ ] **Step 4: Run tests** — `uv run pytest tests/test_search.py -v` → PASS.

- [ ] **Step 5: Time it on the real corpus** (read-only)

```bash
uv run python -c "
import time; from pathlib import Path
from kzlaw_mcp.config import Settings; from kzlaw_mcp.corpus import Corpus; from kzlaw_mcp.search import search
c = Corpus(Settings(corpus_root=Path.home()/'kazakhstan-law-0916')); c.find('81245')
for q in ['электрическ\\w* самокат', 'превышение установленной скорости', 'закон']:
    t = time.monotonic(); r = search(c, q); print(q, len(r['acts']), r['truncated'], f'{time.monotonic()-t:.2f}s')"
```
Expected: each under ~3 s; `закон` truncated. The ПДД (183572) appears for the scooter query.

- [ ] **Step 6: Commit, push**

```bash
git add -A && git commit -m "feat: search tool over ripgrep" && git push
```

---

### Task 5: `read` and `at_date`

**Files:**
- Create: `src/kzlaw_mcp/passages.py`, `tests/test_passages.py`

**Interfaces:**
- Consumes: `Corpus`, `ActRef`, `InputError`, `check_lang`, `title_of`, `locator_label`, `article_span`, `point_spans`, `headings`, `ANCHOR_ID`, `POINT_LABEL`
- Produces:
  - `read(corpus, act_code, lang="rus", anchor=None, point=None) -> dict`
  - `at_date(corpus, act_code, date, lang="rus", anchor=None, point=None) -> dict`
  - result keys: `act_code, scope, title, requisite, sha, as_of ("current" | date), commit_date (at_date only), passages: [{file, lines: [start, end], heading, text, truncated, url, citation}], more: int`; without anchor/point instead `overview, outline, parts, hint`

- [ ] **Step 1: Write the failing test**

```python
import pytest

from conftest import KOAP, KOAP_CODE, PDD, PDD_CODE
from kzlaw_mcp.corpus import Corpus, InputError
from kzlaw_mcp.passages import at_date, read


def test_read_current_article(settings):
    res = read(Corpus(settings), KOAP_CODE, anchor="st592")
    [p] = res["passages"]
    assert "от шестидесяти и более" in p["text"] and p["file"] == f"{KOAP}/rus/sec002-ch030.md"
    assert p["url"] == (
        f"https://github.com/kazakhstan-law/codes/blob/{res['sha']}/{KOAP}/rus/sec002-ch030.md#st592"
    )
    assert p["citation"] == f"[ст. 592]({p['url']})"
    assert res["as_of"] == "current"


def test_at_date_follows_the_renamed_part(settings):
    res = at_date(Corpus(settings), KOAP_CODE, "2022-06-01", anchor="st592")
    [p] = res["passages"]
    assert p["file"].endswith("rus/sec002-ch010.md")
    assert "от сорока и более" in p["text"] and "шестидесяти" not in p["text"]
    assert res["commit_date"] == "2022-01-10" and res["sha"] in p["url"]


def test_part_of_an_article(settings):
    [p] = read(Corpus(settings), KOAP_CODE, anchor="st592", point="3-1")["passages"]
    assert p["text"].startswith("3-1.") and "?plain=1#L" in p["url"]
    assert p["citation"].startswith("[ст. 592, ч. 3-1]")


def test_point_without_anchor(settings):
    res = read(Corpus(settings), PDD_CODE, point="168-1")
    [p] = res["passages"]
    assert "восемнадцати" in p["text"] and p["heading"].startswith("Глава 24")
    assert p["url"].endswith(f"{PDD}/rus.md?plain=1#L{p['lines'][0]}-L{p['lines'][1]}")


def test_repeated_point_label_returns_all(settings):
    res = read(Corpus(settings), PDD_CODE, point="1")
    assert [p["heading"] for p in res["passages"]] == [
        "Глава 1. Общие положения", "Глава 1. Горизонтальная разметка"]


def test_point_absent_on_an_earlier_date(settings):
    with pytest.raises(InputError, match="point 168-1 not found"):
        at_date(Corpus(settings), PDD_CODE, "2023-07-15", point="168-1")


def test_unknown_anchor(settings):
    with pytest.raises(InputError, match="anchor st9999 not found in act 81245"):
        read(Corpus(settings), KOAP_CODE, anchor="st9999")


def test_act_not_yet_in_force(settings):
    with pytest.raises(InputError, match="not in force on 2021-01-01"):
        at_date(Corpus(settings), KOAP_CODE, "2021-01-01", anchor="st592")


def test_before_the_corpus_starts(settings):
    with pytest.raises(InputError, match="no history before 1990-01-01"):
        at_date(Corpus(settings), KOAP_CODE, "1990-01-01")


@pytest.mark.parametrize("date", ["2022-13-01", "01.06.2022", "2022-06-01; ls"])
def test_bad_dates(settings, date):
    with pytest.raises(InputError, match="YYYY-MM-DD"):
        at_date(Corpus(settings), KOAP_CODE, date)


@pytest.mark.parametrize("kw", [{"anchor": "../../x"}, {"anchor": "st1 st2"}, {"point": "1; rm"}])
def test_bad_locators(settings, kw):
    with pytest.raises(InputError):
        read(Corpus(settings), KOAP_CODE, **kw)


def test_overview_without_locator(settings):
    res = read(Corpus(settings), KOAP_CODE)
    assert res["overview"].startswith("# Об административных") and res["parts"]
    assert "passages" not in res
```

- [ ] **Step 2: Run to see it fail** — `uv run pytest tests/test_passages.py -v` → FAIL.

- [ ] **Step 3: Write `src/kzlaw_mcp/passages.py`**

```python
"""read and at_date: a passage of an act at the current or a past revision.

Everything is read from git objects at one sha, so the text and its citation always
agree, and a split act's renamed parts are found by content (anchor or point label),
never by a remembered part name.
"""

from __future__ import annotations

import datetime as dt

from kzlaw_mcp.corpus import ActRef, Corpus, InputError, check_lang, locator_label, title_of
from kzlaw_mcp.locate import ANCHOR_ID, POINT_LABEL, Span, article_span, headings, point_spans

MAX_TEXT = 12_000
MAX_PASSAGES = 3
OVERVIEW_CHARS = 4_000


def _clip(text: str, limit: int) -> tuple[str, bool]:
    return (text, False) if len(text) <= limit else (text[:limit] + "\n[…]", True)


def _check_locators(anchor: str | None, point: str | None) -> tuple[str | None, str | None]:
    anchor = anchor.strip() if anchor else None
    point = point.strip() if point else None
    if anchor and not ANCHOR_ID.match(anchor):
        raise InputError("anchor looks like st592, st62-1 or an3_st1 (take it from search hits)")
    if point and not POINT_LABEL.match(point):
        raise InputError("point is a label like 168-1 or 3 (take it from search hits)")
    return anchor, point


def _passages(corpus: Corpus, ref: ActRef, sha: str, lang: str, anchor: str | None,
              point: str | None, when: str) -> dict:
    lang = check_lang(lang)
    anchor, point = _check_locators(anchor, point)
    g = corpus.git(ref.scope)
    files = corpus.lang_files(ref, sha, lang)
    if not files:
        raise InputError(f"act {ref.code} has no '{lang}' text {when}")
    meta = corpus.meta(ref, sha)
    result = {
        "act_code": ref.code, "scope": ref.scope, "title": title_of(meta, lang),
        "requisite": meta.get("requisite", ""), "sha": sha,
    }
    if not anchor and not point:
        main = g.blob(sha, files[0])
        overview, _ = _clip(main, OVERVIEW_CHARS)
        return result | {
            "overview": overview, "outline": headings(main)[:80], "parts": files[1:101],
            "hint": "Pass anchor or point (from search hits) to read a passage.",
        }

    found: list[tuple[str, Span]] = []
    if anchor:
        hit_files = [p for p, _ in g.grep(sha, f'<a id="{anchor}"></a>', files, fixed=True)]
        for f in dict.fromkeys(hit_files):
            text = g.blob(sha, f)
            if art := article_span(text, anchor):
                spans = point_spans(text, point, within=art) if point else [art]
                found += [(f, s) for s in spans]
        if not found:
            what = f"point {point} of anchor {anchor}" if point else f"anchor {anchor}"
            raise InputError(f"{what} not found in act {ref.code} {when}; search inside the act")
    else:
        hit_files = [p for p, _ in g.grep(sha, rf"^\*?{point}\. ", files, fixed=False)]
        for f in dict.fromkeys(hit_files):
            found += [(f, s) for s in point_spans(g.blob(sha, f), point)]
        if not found:
            raise InputError(f"point {point} not found in act {ref.code} {when}")

    label = locator_label(anchor, point) or result["title"][:80]
    passages = []
    for f, span in found[:MAX_PASSAGES]:
        url = corpus.citation_url(
            ref, sha, f, anchor=None if point else anchor, lines=(span.start, span.end),
            size=g.blob_size(sha, f),
        )
        text, cut = _clip(span.text, MAX_TEXT)
        passages.append({
            "file": f, "lines": [span.start, span.end], "heading": span.heading, "text": text,
            "truncated": cut, "url": url, "citation": f"[{label}]({url})",
        })
    return result | {"passages": passages, "more": len(found) - len(passages)}


def read(corpus: Corpus, act_code: str, lang: str = "rus", anchor: str | None = None,
         point: str | None = None) -> dict:
    ref = corpus.find(act_code)
    res = _passages(corpus, ref, corpus.head(ref.scope), lang, anchor, point, "in the current text")
    return res | {"as_of": "current"}


def at_date(corpus: Corpus, act_code: str, date: str, lang: str = "rus",
            anchor: str | None = None, point: str | None = None) -> dict:
    try:
        if len(date) != 10:
            raise ValueError
        dt.date.fromisoformat(date)
    except (TypeError, ValueError):
        raise InputError("date must be YYYY-MM-DD") from None
    ref = corpus.find(act_code)
    g = corpus.git(ref.scope)
    sha = g.rev_before(date)
    if sha is None:
        raise InputError(f"the corpus has no history before {date}")
    if not corpus.lang_files(ref, sha, lang):
        raise InputError(f"act {ref.code} was not in force on {date} (it enters the corpus later)")
    res = _passages(corpus, ref, sha, lang, anchor, point, f"on {date}")
    return res | {"as_of": date, "commit_date": g.commit_date(sha)}
```

- [ ] **Step 4: Run tests** — `uv run pytest tests/test_passages.py -v` → PASS.

- [ ] **Step 5: Check the two real reference passages** (read-only)

```bash
uv run python -c "
from pathlib import Path
from kzlaw_mcp.config import Settings; from kzlaw_mcp.corpus import Corpus; from kzlaw_mcp.passages import read, at_date
c = Corpus(Settings(corpus_root=Path.home()/'kazakhstan-law-0916'))
p = at_date(c, '81245', '2022-06-01', anchor='st592')['passages'][0]; print(p['file'], 'от сорока и более' in p['text'], p['url'])
p = read(c, '81245', anchor='st592', point='3-1')['passages'][0]; print(p['text'][:120])
p = read(c, '183572', point='168-1')['passages'][0]; print(p['heading'], p['url'])"
```
Expected: 2022 → `rus/sec002-ch030.md` or whatever part held it then, `True`; part 3-1 text "от шестидесяти и более"; ПДД point 168-1 under the e-scooter chapter with a `?plain=1#L…` link (the ПДД file is 400 KB, over `RENDER_LIMIT`).

- [ ] **Step 6: Commit, push**

```bash
git add -A && git commit -m "feat: read and at_date tools" && git push
```

---

### Task 6: `history`

**Files:**
- Create: `src/kzlaw_mcp/history.py`, `tests/test_history.py`

**Interfaces:**
- Consumes: `Corpus`, `InputError`, `title_of`
- Produces: `history(corpus, act_code, phrase: str | None = None, limit: int = 30) -> dict` with keys `act_code, scope, title, phrase, commits: [{date, sha, subject, cause_act_code, cause_act_requisite, url}]` (newest first), `first_version: {…} | None`, `limited: bool`, `introduced: {…} | None` (with phrase: the oldest commit when not limited), `note`

- [ ] **Step 1: Write the failing test**

```python
import pytest

from conftest import KOAP_CODE, PDD_CODE
from kzlaw_mcp.corpus import Corpus, InputError
from kzlaw_mcp.history import history


def test_history_lists_amending_acts(settings):
    res = history(Corpus(settings), KOAP_CODE)
    assert [c["date"] for c in res["commits"]] == ["2024-10-03", "2022-01-10"]
    top = res["commits"][0]
    assert top["cause_act_code"] == "999131" and "131-VIII" in top["cause_act_requisite"]
    assert top["url"] == f"https://github.com/kazakhstan-law/codes/commit/{top['sha']}"
    assert res["first_version"]["date"] == "2022-01-10"


def test_phrase_pinpoints_when_it_appeared(settings):
    res = history(Corpus(settings), PDD_CODE, phrase="электрических самокатов")
    assert [c["date"] for c in res["commits"]] == ["2023-08-31"]
    assert res["introduced"]["cause_act_code"] == "999671"


def test_commit_without_cause(settings):
    res = history(Corpus(settings), PDD_CODE)
    assert res["commits"][-1]["cause_act_code"] == ""


def test_option_like_phrase_is_text(settings):
    assert history(Corpus(settings), PDD_CODE, phrase="--all")["commits"] == []


@pytest.mark.parametrize("phrase", ["ab", "x" * 201])
def test_bad_phrase(settings, phrase):
    with pytest.raises(InputError):
        history(Corpus(settings), PDD_CODE, phrase=phrase)
```

- [ ] **Step 2: Run to see it fail** — `uv run pytest tests/test_history.py -v` → FAIL.

- [ ] **Step 3: Write `src/kzlaw_mcp/history.py`**

```python
"""history: an act's versions from git log, with the amending act from commit trailers."""

from __future__ import annotations

from kzlaw_mcp.corpus import Corpus, InputError, title_of

FORMAT = (
    "%H%x1f%cs%x1f%s%x1f"
    "%(trailers:key=Cause-Act-Code,valueonly,separator=%x2C)%x1f"
    "%(trailers:key=Cause-Act-Requisite,valueonly,separator=%x20)%x1e"
)
MAX_LIMIT = 50
NOTE = (
    "Each commit is one version of this act, dated to its version date; the subject and "
    "cause_act_* name the amending act. With phrase: only versions that added or removed that "
    "exact, case-sensitive text; the oldest is when it entered this act. History covers this act "
    "only: a predecessor act that was repealed and replaced is not followed."
)


def _parse(out: str, corpus: Corpus, scope: str) -> list[dict]:
    commits = []
    for record in out.split("\x1e"):
        record = record.strip("\n")
        if not record:
            continue
        sha, date, subject, code, requisite = record.split("\x1f")
        commits.append({
            "date": date, "sha": sha, "subject": subject, "cause_act_code": code.strip(),
            "cause_act_requisite": requisite.strip(), "url": corpus.commit_url(scope, sha),
        })
    return commits


def history(corpus: Corpus, act_code: str, phrase: str | None = None, limit: int = 30) -> dict:
    ref = corpus.find(act_code)
    phrase = phrase.strip() if phrase else None
    if phrase is not None and not 3 <= len(phrase) <= 200:
        raise InputError("phrase must be 3..200 characters of the act's exact wording")
    limit = max(1, min(int(limit), MAX_LIMIT))
    g = corpus.git(ref.scope)
    head = corpus.head(ref.scope)
    args = ["-n", str(limit), f"--format={FORMAT}"]
    if phrase:
        args.append(f"-S{phrase}")
    commits = _parse(g.log(*args, head, "--", ref.path), corpus, ref.scope)
    created = _parse(
        g.log("--diff-filter=A", f"--format={FORMAT}", head, "--", f"{ref.path}/meta.yaml"),
        corpus, ref.scope,
    )
    limited = len(commits) == limit
    meta = corpus.meta(ref, head)
    return {
        "act_code": ref.code, "scope": ref.scope, "title": title_of(meta, "rus"), "phrase": phrase,
        "commits": commits, "first_version": created[-1] if created else None,
        "limited": limited,
        "introduced": commits[-1] if phrase and commits and not limited else None,
        "note": NOTE,
    }
```

- [ ] **Step 4: Run tests** — `uv run pytest tests/test_history.py -v` → PASS.

- [ ] **Step 5: Check form 270 on the real corpus** (read-only)

```bash
uv run python -c "
from pathlib import Path
from kzlaw_mcp.config import Settings; from kzlaw_mcp.corpus import Corpus; from kzlaw_mcp.history import history
c = Corpus(Settings(corpus_root=Path.home()/'kazakhstan-law-0916'))
r = history(c, '158645'); print([(x['date'], x['cause_act_code']) for x in r['commits']], r['first_version']['date'])
r = history(c, '158645', phrase='в собственности цифровые активы'); print(r['introduced'])"
```
Expected: dates 2025-10-24 (216103), 2024-08-01, 2024-07-16 (198834), 2024-03-29 (194995), 2021-09-13; `introduced` is the 2025-10-24 commit `7044203fca…`.

- [ ] **Step 6: Commit, push**

```bash
git add -A && git commit -m "feat: history tool with pickaxe" && git push
```

---

### Task 7: Call gate — rate limit, concurrency, call log

**Files:**
- Create: `src/kzlaw_mcp/gate.py`, `tests/test_gate.py`

**Interfaces:**
- Consumes: `Settings`, `InputError`, `CommandError`
- Produces: `RateLimiter(calls, window_s, clock=time.monotonic).hit(key) -> float | None` (None = allowed, else seconds to wait); `CallLog(path, salt).record(**fields)`; `client_ip(request, trusted: frozenset[str]) -> tuple[str, bool]` (ip, via_proxy); `Gate(settings, clock=time.monotonic)` with `async call(tool: str, args: dict, request, fn: Callable[[], dict]) -> dict`

- [ ] **Step 1: Write the failing test**

```python
import json
from types import SimpleNamespace

import pytest

from kzlaw_mcp.corpus import InputError
from kzlaw_mcp.gate import Gate, RateLimiter, client_ip
from kzlaw_mcp.gitio import CommandError


def req(peer, xff=None):
    headers = {"x-forwarded-for": xff} if xff else {}
    return SimpleNamespace(client=SimpleNamespace(host=peer), headers=headers)


def test_rate_limiter_window():
    now = [0.0]
    rl = RateLimiter(2, 10, clock=lambda: now[0])
    assert rl.hit("a") is None and rl.hit("a") is None
    assert rl.hit("a") == pytest.approx(10)
    assert rl.hit("b") is None
    now[0] = 10.5
    assert rl.hit("a") is None


def test_forwarded_for_only_from_the_proxy():
    trusted = frozenset({"100.64.0.1"})
    assert client_ip(req("100.64.0.1", "1.2.3.4"), trusted) == ("1.2.3.4", True)
    assert client_ip(req("100.64.0.1", "6.6.6.6, 1.2.3.4"), trusted) == ("1.2.3.4", True)
    assert client_ip(req("5.5.5.5", "1.2.3.4"), trusted) == ("5.5.5.5", False)
    assert client_ip(None, trusted) == ("local", False)


@pytest.mark.anyio
async def test_gate_logs_and_limits(settings):
    from dataclasses import replace

    gate = Gate(replace(settings, rate_calls=1))
    assert await gate.call("search", {"q": "x"}, req("9.9.9.9"), lambda: {"ok": 1}) == {"ok": 1}
    with pytest.raises(InputError, match="rate limit"):
        await gate.call("search", {"q": "x"}, req("9.9.9.9"), lambda: {"ok": 1})
    rows = [json.loads(line) for line in settings.log_path.read_text().splitlines()]
    assert [r["ok"] for r in rows] == [True, False] and rows[1]["error"] == "rate_limited"
    assert rows[0]["ip"] != "9.9.9.9" and len(rows[0]["ip"]) == 16


@pytest.mark.anyio
async def test_gate_turns_command_errors_into_input_errors(settings):
    def boom():
        raise CommandError("rg timed out after 20s")

    with pytest.raises(InputError, match="temporary failure"):
        await Gate(settings).call("search", {}, None, boom)
```

- [ ] **Step 2: Run to see it fail** — `uv run pytest tests/test_gate.py -v` → FAIL.

- [ ] **Step 3: Write `src/kzlaw_mcp/gate.py`**

```python
"""Per-client rate limit, a global cap on concurrent tool work, and a JSONL call log."""

from __future__ import annotations

import hashlib
import json
import threading
import time
from collections import deque
from collections.abc import Callable
from datetime import UTC, datetime
from pathlib import Path

import anyio
import anyio.to_thread

from kzlaw_mcp.config import Settings
from kzlaw_mcp.corpus import InputError
from kzlaw_mcp.gitio import CommandError


class RateLimiter:
    def __init__(self, calls: int, window_s: float, clock: Callable[[], float] = time.monotonic):
        self.calls, self.window, self._clock = calls, window_s, clock
        self._hits: dict[str, deque[float]] = {}
        self._lock = threading.Lock()

    def hit(self, key: str) -> float | None:
        with self._lock:
            now = self._clock()
            q = self._hits.setdefault(key, deque())
            while q and now - q[0] >= self.window:
                q.popleft()
            if len(q) >= self.calls:
                return self.window - (now - q[0])
            q.append(now)
            if len(self._hits) > 10_000:
                self._hits = {k: v for k, v in self._hits.items() if v and now - v[-1] < self.window}
            return None


class CallLog:
    def __init__(self, path: Path | None, salt: str):
        self.path, self.salt = path, salt
        self._lock = threading.Lock()

    def record(self, *, ip: str, **fields) -> None:
        if self.path is None:
            return
        row = {
            "ts": datetime.now(UTC).isoformat(timespec="seconds"),
            "ip": hashlib.sha256(f"{self.salt}{ip}".encode()).hexdigest()[:16],
            **fields,
        }
        line = json.dumps(row, ensure_ascii=False)
        with self._lock, self.path.open("a", encoding="utf-8") as fh:
            fh.write(line + "\n")


def client_ip(request, trusted: frozenset[str]) -> tuple[str, bool]:
    """The client's address. X-Forwarded-For counts only when the peer is our proxy, and then
    only its last entry: Caddy appends the address it saw, anything before it is client-supplied."""
    if request is None:
        return "local", False
    peer = request.client.host if request.client else "unknown"
    if peer in trusted:
        forwarded = request.headers.get("x-forwarded-for", "")
        if forwarded:
            return forwarded.split(",")[-1].strip(), True
    return peer, False


class Gate:
    def __init__(self, settings: Settings, clock: Callable[[], float] = time.monotonic):
        self.settings = settings
        self.limiter = RateLimiter(settings.rate_calls, settings.rate_window_s, clock)
        self.log = CallLog(settings.log_path, settings.ip_salt)
        self._capacity: anyio.CapacityLimiter | None = None

    async def call(self, tool: str, args: dict, request, fn: Callable[[], dict]) -> dict:
        if self._capacity is None:
            self._capacity = anyio.CapacityLimiter(self.settings.max_parallel)
        ip, via_proxy = client_ip(request, self.settings.trusted_proxies)
        base = {"ip": ip, "via_proxy": via_proxy, "tool": tool, "args": args}
        wait = self.limiter.hit(ip)
        if wait is not None:
            self.log.record(**base, ok=False, error="rate_limited", ms=0)
            raise InputError(f"rate limit reached; try again in {int(wait) + 1} s")
        started = time.monotonic()
        try:
            result = await anyio.to_thread.run_sync(fn, limiter=self._capacity)
        except InputError as exc:
            self.log.record(**base, ok=False, error=str(exc), ms=_ms(started))
            raise
        except CommandError as exc:
            self.log.record(**base, ok=False, error=str(exc), ms=_ms(started))
            raise InputError(f"temporary failure, try again: {exc}") from exc
        size = len(json.dumps(result, ensure_ascii=False))
        self.log.record(**base, ok=True, size=size, ms=_ms(started))
        return result


def _ms(started: float) -> int:
    return int((time.monotonic() - started) * 1000)
```

- [ ] **Step 4: Run tests** — `uv run pytest tests/test_gate.py -v` → PASS.

- [ ] **Step 5: Commit, push**

```bash
git add -A && git commit -m "feat: rate limit, concurrency cap and call log" && git push
```

---

### Task 8: MCP server

**Files:**
- Create: `src/kzlaw_mcp/server.py`, `tests/test_server.py`, `scripts/smoke.py`

**Interfaces:**
- Consumes: `Settings`, `Corpus`, `Gate`, `search`, `read`, `at_date`, `history`
- Produces: `INSTRUCTIONS: str`, `build_server(settings, corpus=None) -> FastMCP` (tools `search`, `read`, `at_date`, `history`; routes `GET /` landing, `GET /health`), `main()`; `scripts/smoke.py URL` — lists tools and runs one search.

- [ ] **Step 1: Write the failing test**

```python
import socket
import threading
import time

import httpx
import pytest
import uvicorn
from mcp import ClientSession
from mcp.client.streamable_http import streamablehttp_client

from conftest import KOAP_CODE
from kzlaw_mcp.server import build_server


@pytest.fixture
def server_url(settings):
    with socket.socket() as s:
        s.bind(("127.0.0.1", 0))
        port = s.getsockname()[1]
    app = build_server(settings).streamable_http_app()
    server = uvicorn.Server(uvicorn.Config(app, host="127.0.0.1", port=port, log_level="warning"))
    thread = threading.Thread(target=server.run, daemon=True)
    thread.start()
    for _ in range(100):
        if server.started:
            break
        time.sleep(0.05)
    yield f"http://127.0.0.1:{port}"
    server.should_exit = True
    thread.join(5)


@pytest.mark.anyio
async def test_tools_over_streamable_http(server_url):
    async with streamablehttp_client(f"{server_url}/mcp") as (read, write, _):
        async with ClientSession(read, write) as session:
            init = await session.initialize()
            assert "citation" in init.instructions
            names = {t.name for t in (await session.list_tools()).tools}
            assert names == {"search", "read", "at_date", "history"}
            res = await session.call_tool("search", {"query": "превышение установленной скорости"})
            assert not res.isError
            assert res.structuredContent["acts"][0]["act_code"] == KOAP_CODE
            bad = await session.call_tool("read", {"act_code": "../../etc"})
            assert bad.isError and "act_code" in bad.content[0].text


def test_landing_and_health(server_url):
    assert "claude.ai" in httpx.get(f"{server_url}/").text
    assert httpx.get(f"{server_url}/health").json() == {"ok": True, "scopes": 2}
```

- [ ] **Step 2: Run to see it fail** — `uv run pytest tests/test_server.py -v` → FAIL.

- [ ] **Step 3: Write `src/kzlaw_mcp/server.py`**

```python
"""FastMCP over Streamable HTTP: four read-only tools, a landing page and a health check."""

from __future__ import annotations

from typing import Literal

from mcp.server.fastmcp import Context, FastMCP
from starlette.requests import Request
from starlette.responses import JSONResponse, PlainTextResponse

from kzlaw_mcp.config import Settings
from kzlaw_mcp.corpus import Corpus
from kzlaw_mcp.gate import Gate
from kzlaw_mcp.history import history as history_tool
from kzlaw_mcp.passages import at_date as at_date_tool
from kzlaw_mcp.passages import read as read_tool
from kzlaw_mcp.search import search as search_tool

Lang = Literal["rus", "kaz"]

INSTRUCTIONS = """\
You answer questions about the law of the Republic of Kazakhstan for ordinary people, using \
only texts these tools return. The corpus is an unofficial copy of ЕСПИ (law.gov.kz) kept in \
git, with every act's full history.

1. Every claim about the law carries its citation: paste the `citation` link that read or \
at_date returned, as is. Never build or edit a link yourself. No citation, no claim.
2. Quote only passages you opened with read or at_date; a search hit alone is not enough.
3. Search with legal wording: "ГАИ" -> "полиция", "органы внутренних дел"; "самокат" -> \
"электрическ самокат", "средств индивидуальной мобильности". Use stems and alternation \
("самокат|мобильност"). Retry other wording before concluding; if nothing is found, say so \
and name what you searched.
4. Pick the mode: the law now -> read; the law on a past date ("оштрафовали в 2022") -> \
at_date on that date, compared with read; "since when" -> history with a short exact phrase \
from the current text (case-sensitive); the oldest commit is when it appeared.
5. Answer in the user's language, in plain words: one or two sentences first, then the key \
points each with its citation, then, if the cited text changed recently, "изменено \
DD.MM.YYYY <amending act>" from history.
6. Questions in Kazakh: search and read with lang="kaz".
7. Do not add legal disclaimers to answers.
"""

LANDING = """\
kazakhstan-law MCP — законы Казахстана с историей изменений, для вашего чат-бота.

Подключить к Claude (любой тариф, включая бесплатный):
  claude.ai -> Настройки -> Коннекторы -> Добавить свой коннектор -> адрес:
  {url}
  Добавлять нужно на сайте claude.ai; потом коннектор работает и в приложении на телефоне.

Подключить к ChatGPT (Plus и выше): Настройки -> Приложения -> Режим разработчика ->
  Создать -> тот же адрес.

Пример вопроса: «Какие новые правила для электросамокатов?»

Неофициальная копия. Официальный источник — ЕСПИ, law.gov.kz. Не юридическая консультация.
Исходный код: https://github.com/kazakhstan-law/mcp
"""

SEARCH_DESC = (
    "Full-text search (regex, case-insensitive) over the acts of Kazakhstan in force. Returns "
    "acts with matching lines; each line carries the article anchor (e.g. st592) and/or point "
    "label (e.g. 168-1) to pass to read. Scopes: codes (constitution, codes, laws), government, "
    "ministerial by default; local-<region> only for regional questions."
)
READ_DESC = (
    "Current text of an act: an article by anchor (st592), a point by label (168-1), or a part "
    "of an article (anchor + point). Without either, the act's outline. Each passage has a "
    "`citation` Markdown link pinned to a commit: paste it as is next to the claim."
)
AT_DATE_DESC = (
    "Like read, but the text in force on a past date (YYYY-MM-DD): for 'what was the rule when "
    "it happened'. The citation is pinned to that date's version."
)
HISTORY_DESC = (
    "The act's versions from git: date and amending act (number, title, code) of each. With "
    "phrase, only versions that added or removed that exact, case-sensitive text; the oldest is "
    "when it entered the act. Covers this act only."
)


def _request(ctx: Context):
    return getattr(ctx.request_context, "request", None)


def build_server(settings: Settings, corpus: Corpus | None = None) -> FastMCP:
    corpus = corpus or Corpus(settings)
    gate = Gate(settings)
    mcp = FastMCP(
        "kazakhstan-law", instructions=INSTRUCTIONS, host=settings.host, port=settings.port,
        stateless_http=True, json_response=True,
    )

    @mcp.tool(description=SEARCH_DESC)
    async def search(ctx: Context, query: str, lang: Lang = "rus",
                     scopes: list[str] | None = None, limit: int = 20) -> dict:
        args = {"query": query, "lang": lang, "scopes": scopes, "limit": limit}
        return await gate.call("search", args, _request(ctx),
                               lambda: search_tool(corpus, query, lang, scopes, limit))

    @mcp.tool(description=READ_DESC)
    async def read(ctx: Context, act_code: str, lang: Lang = "rus", anchor: str | None = None,
                   point: str | None = None) -> dict:
        args = {"act_code": act_code, "lang": lang, "anchor": anchor, "point": point}
        return await gate.call("read", args, _request(ctx),
                               lambda: read_tool(corpus, act_code, lang, anchor, point))

    @mcp.tool(description=AT_DATE_DESC)
    async def at_date(ctx: Context, act_code: str, date: str, lang: Lang = "rus",
                      anchor: str | None = None, point: str | None = None) -> dict:
        args = {"act_code": act_code, "date": date, "lang": lang, "anchor": anchor, "point": point}
        return await gate.call("at_date", args, _request(ctx),
                               lambda: at_date_tool(corpus, act_code, date, lang, anchor, point))

    @mcp.tool(description=HISTORY_DESC)
    async def history(ctx: Context, act_code: str, phrase: str | None = None,
                      limit: int = 30) -> dict:
        args = {"act_code": act_code, "phrase": phrase, "limit": limit}
        return await gate.call("history", args, _request(ctx),
                               lambda: history_tool(corpus, act_code, phrase, limit))

    @mcp.custom_route("/", methods=["GET"])
    async def landing(request: Request) -> PlainTextResponse:
        return PlainTextResponse(LANDING.format(url=settings.public_url))

    @mcp.custom_route("/health", methods=["GET"])
    async def health(request: Request) -> JSONResponse:
        return JSONResponse({"ok": True, "scopes": len(corpus.scopes())})

    return mcp


def main() -> None:
    build_server(Settings.from_env()).run(transport="streamable-http")
```

Note: FastMCP turns on DNS-rebinding protection only when `host` is a localhost name. In production `KZLAW_HOST=0.0.0.0`, so a request with `Host: cyphy.kz` is accepted. If it were bound to `127.0.0.1`, every proxied request would get 421.

- [ ] **Step 4: Write `scripts/smoke.py`**

```python
"""Smoke-test an MCP endpoint: `uv run python scripts/smoke.py https://cyphy.kz/kazakhstan-law/mcp`."""

import asyncio
import sys

from mcp import ClientSession
from mcp.client.streamable_http import streamablehttp_client


async def main(url: str) -> None:
    async with streamablehttp_client(url) as (read, write, _):
        async with ClientSession(read, write) as session:
            await session.initialize()
            print(sorted(t.name for t in (await session.list_tools()).tools))
            res = await session.call_tool("search", {"query": "электрическ\\w* самокат"})
            acts = res.structuredContent["acts"]
            print(res.isError, [(a["act_code"], a["title"][:60]) for a in acts[:5]])


asyncio.run(main(sys.argv[1]))
```

- [ ] **Step 5: Run tests** — `uv run pytest -v` (whole suite) → PASS.

- [ ] **Step 6: Run locally against the real corpus** (read-only)

```bash
KZLAW_CORPUS_ROOT=~/kazakhstan-law-0916 KZLAW_PORT=8765 uv run kzlaw-mcp &
sleep 3; uv run python scripts/smoke.py http://127.0.0.1:8765/mcp; kill %1
```
Expected: four tool names; `False` and the ПДД (183572) among the acts.

- [ ] **Step 7: Commit, push**

```bash
git add -A && git commit -m "feat: MCP server over Streamable HTTP with landing and health routes" && git push
```

---

### Task 9: Refresh, Docker image, compose

**Files:**
- Create: `src/kzlaw_mcp/refresh.py`, `tests/test_refresh.py`, `Dockerfile`, `compose.yml`, `.dockerignore`

**Interfaces:**
- Consumes: `Settings`, `ALL_SCOPES`, `run`
- Produces: `refresh_scope(settings, scope) -> str` (`"cloned" | "updated" | "unchanged"`); `main()` with `--loop SECONDS` and `--scopes a,b`

- [ ] **Step 1: Write the failing test**

```python
import subprocess
from dataclasses import replace

from conftest import commit, init
from kzlaw_mcp.gitio import Git
from kzlaw_mcp.refresh import refresh_scope


def git(*args, cwd):
    subprocess.run(["git", *args], cwd=cwd, check=True, capture_output=True)


def test_clone_then_follow_a_force_push(tmp_path, settings):
    src = init(tmp_path / "src")
    commit(src, "2020-01-01", {"a/rus.md": "one\n"}, "first")
    remotes = tmp_path / "remotes"
    remotes.mkdir()
    git("clone", "-q", "--bare", str(src), str(remotes / "codes.git"), cwd=tmp_path)
    s = replace(settings, corpus_root=tmp_path / "corpus",
                remote_template=f"file://{remotes}/{{scope}}.git")
    (tmp_path / "corpus").mkdir()

    assert refresh_scope(s, "codes") == "cloned"
    assert refresh_scope(s, "codes") == "unchanged"

    # a rebuild rewrites history: amend (a new root commit) and force-push
    (src / "a/rus.md").write_text("one, rebuilt\n")
    git("-c", "user.name=c", "-c", "user.email=c@example.invalid",
        "commit", "-qa", "--amend", "-m", "first", cwd=src)
    git("push", "-q", "--force", str(remotes / "codes.git"), "main", cwd=src)
    assert refresh_scope(s, "codes") == "updated"
    clone = tmp_path / "corpus" / "codes"
    assert (clone / "a/rus.md").read_text() == "one, rebuilt\n"
    assert Git(clone, 5).head() == Git(src, 5).head()
```

(The amend replaces the only commit, so the clone's HEAD is no longer an ancestor of the remote: `refresh_scope` must reset, never merge or pull.)

- [ ] **Step 2: Run to see it fail** — `uv run pytest tests/test_refresh.py -v` → FAIL.

- [ ] **Step 3: Write `src/kzlaw_mcp/refresh.py`**

```python
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
        run(["git", "clone", "-q", "--single-branch", "--branch", "main", url, scope], root,
            timeout=TIMEOUT)
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
```

- [ ] **Step 4: Run tests** — `uv run pytest -v` → PASS.

- [ ] **Step 5: Write `Dockerfile`, `.dockerignore`, `compose.yml`**

```dockerfile
FROM python:3.13-slim
RUN apt-get update \
 && apt-get install -y --no-install-recommends git ripgrep ca-certificates \
 && rm -rf /var/lib/apt/lists/* \
 && git config --system --add safe.directory '*'
COPY --from=ghcr.io/astral-sh/uv:latest /uv /bin/uv
WORKDIR /app
COPY pyproject.toml uv.lock README.md ./
RUN uv sync --frozen --no-dev --no-install-project
COPY src ./src
RUN uv sync --frozen --no-dev
ENV PATH=/app/.venv/bin:$PATH
USER 1000:1000
CMD ["kzlaw-mcp"]
```

`.dockerignore`:
```
.venv
data
.git
tests
docs
```

`compose.yml`:
```yaml
services:
  server:
    build: .
    image: kazakhstan-law-mcp:local
    command: kzlaw-mcp
    env_file: .env
    environment:
      KZLAW_CORPUS_ROOT: /corpus
      KZLAW_HOST: 0.0.0.0
      KZLAW_PORT: "8000"
      KZLAW_LOG_PATH: /logs/calls.jsonl
    volumes:
      - ./data/corpus:/corpus:ro
      - ./data/logs:/logs
    ports:
      - "8765:8000"
    read_only: true
    tmpfs: [/tmp]
    restart: unless-stopped
    healthcheck:
      test: ["CMD", "python", "-c", "import urllib.request; urllib.request.urlopen('http://127.0.0.1:8000/health')"]
      interval: 60s
  refresh:
    image: kazakhstan-law-mcp:local
    command: kzlaw-refresh --loop 3600
    environment:
      KZLAW_CORPUS_ROOT: /corpus
    volumes:
      - ./data/corpus:/corpus
    restart: unless-stopped
```

The server mounts the clones read-only: nothing it runs needs to write, and a bug cannot corrupt them.

- [ ] **Step 6: Build and smoke the image locally on a small scope**

```bash
mkdir -p data/corpus data/logs && cp .env.example .env
docker compose build
docker compose run --rm refresh kzlaw-refresh --scopes codes
docker compose up -d server && sleep 5
curl -s localhost:8765/health && uv run python scripts/smoke.py http://127.0.0.1:8765/mcp
docker compose down && rm -rf data .env
```
Expected: `{"ok":true,"scopes":1}`; four tools; the search runs (the ПДД is not in `codes`, so the scooter hits come from КоАП and the traffic law).

- [ ] **Step 7: Commit, push**

```bash
git add -A && git commit -m "feat: corpus refresh, Docker image and compose" && git push
```

---

### Task 10: Reference questions and README

**Files:**
- Create: `tests/reference/test_reference.py`
- Modify: `README.md`

**Interfaces:**
- Consumes: a running server URL in `KZLAW_MCP_URL`; the `claude` CLI logged in on this machine.
- Produces: `uv run pytest -m reference` — three questions, each asserting tool calls, cited acts and that every cited GitHub link came from a tool result.

- [ ] **Step 1: Check the CLI flags this relies on**

```bash
claude --help | grep -E -- "--tools|--allowedTools|--mcp-config|--strict-mcp-config|--output-format|--model"
```
Expected: all six listed. If `--tools` is missing, replace `"--tools", ""` below with `"--disallowedTools", "Bash Read Write Edit Glob Grep WebFetch WebSearch NotebookEdit Task"`.

- [ ] **Step 2: Write `tests/reference/test_reference.py`**

```python
"""Real questions through `claude -p` against a live server. Opt-in; costs quota.

    KZLAW_MCP_URL=http://127.0.0.1:8765/mcp uv run pytest -m reference -v -s
"""

from __future__ import annotations

import json
import os
import re
import subprocess
from dataclasses import dataclass, field

import pytest

pytestmark = pytest.mark.reference
URL = os.environ.get("KZLAW_MCP_URL", "")
TOOLS = ["search", "read", "at_date", "history"]
LINK = re.compile(r"https://github\.com/kazakhstan-law/([\w-]+)/blob/([0-9a-f]{40})/([^\s)#?]+)")


@dataclass
class Case:
    id: str
    question: str
    must_call: list[str]
    must_cite: list[str]  # act codes; each must appear in at least one cited link
    answer_has: list[str] = field(default_factory=list)


CASES = [
    Case("scooters", "Какие изменения недавно внесли в правила езды на электросамокатах?",
         ["search", "read"], ["183572"]),
    Case("speed-2022",
         "В 2022 меня оштрафовали за превышение скорости на 65 км/ч — какой был штраф и какой сейчас?",
         ["at_date"], ["81245"], ["20", "40"]),
    Case("form-270", "С каких пор надо сдавать форму 270?", ["history"], ["158645"], ["2021"]),
]


def ask(question: str) -> tuple[list[tuple[str, dict]], list[str], str]:
    config = json.dumps({"mcpServers": {"kazakhstan-law": {"type": "http", "url": URL}}})
    allowed = " ".join(f"mcp__kazakhstan-law__{t}" for t in TOOLS)
    proc = subprocess.run(
        ["claude", "-p", question, "--model", "claude-opus-5-5", "--mcp-config", config,
         "--strict-mcp-config", "--tools", "", "--allowedTools", allowed,
         "--output-format", "stream-json", "--verbose"],
        capture_output=True, text=True, timeout=600, check=True,
    )
    calls, results, answer = [], [], ""
    for line in proc.stdout.splitlines():
        event = json.loads(line)
        content = (event.get("message") or {}).get("content") or []
        for block in content if isinstance(content, list) else []:
            if block.get("type") == "tool_use":
                calls.append((block["name"].rsplit("__", 1)[-1], block.get("input", {})))
            elif block.get("type") == "tool_result":
                results.append(json.dumps(block.get("content"), ensure_ascii=False))
        if event.get("type") == "result":
            answer = event.get("result", "")
    return calls, results, answer


@pytest.mark.skipif(not URL, reason="set KZLAW_MCP_URL")
@pytest.mark.parametrize("case", CASES, ids=[c.id for c in CASES])
def test_reference(case: Case):
    calls, results, answer = ask(case.question)
    print(f"\n--- {case.id}: {[n for n, _ in calls]}\n{answer}")
    called = {name for name, _ in calls}
    assert set(case.must_call) <= called, called
    links = LINK.findall(answer)
    assert links, "the answer cites nothing"
    seen = "\n".join(results)
    for scope, sha, path in links:  # the citation check the old bot did in code
        assert f"/{scope}/blob/{sha}/{path}" in seen, f"cited link not returned by a tool: {path}"
    for code in case.must_cite:
        assert any(path.split("/")[-2].endswith(f"-{code}") or f"-{code}/" in path
                   for _, _, path in links), f"act {code} not cited"
    for text in case.answer_has:
        assert text in answer
```

- [ ] **Step 3: Run it against the local server on the real corpus**

```bash
KZLAW_CORPUS_ROOT=~/kazakhstan-law-0916 KZLAW_PORT=8765 uv run kzlaw-mcp &
sleep 3; KZLAW_MCP_URL=http://127.0.0.1:8765/mcp uv run pytest -m reference -v -s; kill %1
```
Expected: 3 passed, with the answers printed. If a case fails, read the printed answer and tool trace. Fix it in the server instructions or tool descriptions (Task 8 files), or in a tool, never in the assertion. Then rerun. Report the per-question wall time: it bounds the on-stage demo.

- [ ] **Step 4: Write `README.md`**

````markdown
# kazakhstan-law MCP

A public [MCP](https://modelcontextprotocol.io) server over the
[kazakhstan-law](https://github.com/kazakhstan-law) corpus: the acts of Kazakhstan as git
repositories, one commit per version. Your chatbot can search the law, read an article,
see the text in force on a past date, and find when a rule appeared. Every answer links to
the exact version it quotes.

**Endpoint:** `https://cyphy.kz/kazakhstan-law/mcp` (Streamable HTTP, no authentication).

## Подключить

**Claude** (любой тариф, включая бесплатный): claude.ai → Настройки → Коннекторы →
Добавить свой коннектор → `https://cyphy.kz/kazakhstan-law/mcp`. Добавлять нужно на сайте; потом
коннектор работает и в приложении на телефоне. На бесплатном тарифе можно подключить один
свой коннектор.

**ChatGPT** (Plus и выше): Настройки → Приложения → Режим разработчика → Создать → тот же
адрес.

Спросите, например: «Какие новые правила для электросамокатов?», «В 2022 меня оштрафовали за
превышение на 65 км/ч — какой был штраф и какой сейчас?», «С каких пор надо сдавать форму 270?»

> Неофициальная копия. Официальный источник — ЕСПИ, [law.gov.kz](https://law.gov.kz).
> Это не юридическая консультация.

## Tools

| Tool | What it does |
|---|---|
| `search` | Case-insensitive regex search over acts in force; hits carry article anchors / point labels |
| `read` | Current text of an article (`st592`), a point (`168-1`) or a part of an article |
| `at_date` | The same text as in force on a past date |
| `history` | The act's versions and amending acts; with a phrase, when that wording appeared |

## Run it yourself

```bash
uv sync
KZLAW_CORPUS_ROOT=./data/corpus uv run kzlaw-refresh --scopes codes   # clones from GitHub
KZLAW_CORPUS_ROOT=./data/corpus uv run kzlaw-mcp                      # http://127.0.0.1:8000/mcp
uv run pytest
```

Or `docker compose up -d` (see `compose.yml`). Full clones of all 25 scopes take ≈ 1.8 GB packed
and ≈ 6 GB of working trees.

## License

The texts are official documents and not subject to copyright. The code here is released
into the public domain under the [Unlicense](https://unlicense.org).
````

Add a `LICENSE` file with the Unlicense text. It must be byte-identical to the corpus repos' own LICENSE so GitHub detects it: `gh api repos/kazakhstan-law/codes/contents/LICENSE --jq .content | base64 -d > LICENSE`.

- [ ] **Step 5: Commit, push**

```bash
git add -A && git commit -m "test: reference questions through claude -p; README with connect instructions" && git push
```

---

### Task 11: Deploy — latitude, hub route, public endpoint

**Files:**
- Create: `deploy/Caddyfile.snippet`
- Modify (outside this repo): `~/vps/vps/caddy/Caddyfile` on hub (repo `metheoryt/vps`)

**Interfaces:**
- Consumes: the image and compose file from Task 9
- Produces: `https://cyphy.kz/kazakhstan-law/mcp` serving all 25 scopes; landing page at `https://cyphy.kz/kazakhstan-law/`

- [ ] **Step 1: Confirm the path is still free**

The endpoint is a path on the existing `cyphy.kz` site (the user's decision, 2026-09-26), so
no DNS record is needed. On 2026-09-26 that site served only `/mtproto` and returned 404 for
everything else, including `/.well-known/oauth-*`. That 404 matters: MCP clients probe those
paths to decide whether a server needs OAuth, and a 404 means "no auth".
```bash
for p in /kazakhstan-law/ /kazakhstan-law/mcp /.well-known/oauth-protected-resource /.well-known/oauth-protected-resource/kazakhstan-law/mcp; do
  printf "%s " $p; curl -s -o /dev/null -w "%{http_code}\n" https://cyphy.kz$p; done
```
Expected: 404 for all four. Anything else: stop and report.

- [ ] **Step 2: Deploy on latitude** (user `me`, docker available, linger on)

```bash
ssh latitude.gg.ez '
  cd ~/my && git clone https://github.com/kazakhstan-law/mcp.git kazakhstan-law-mcp && cd kazakhstan-law-mcp
  mkdir -p data/corpus data/logs
  printf "KZLAW_PUBLIC_URL=https://cyphy.kz/kazakhstan-law/mcp\nKZLAW_IP_SALT=%s\n" "$(openssl rand -hex 16)" > .env
  docker compose build && docker compose up -d'
```
The `refresh` service clones all 25 scopes on its first pass (≈ 1.8 GB). Follow it with `ssh latitude.gg.ez 'cd ~/my/kazakhstan-law-mcp && docker compose logs -f refresh'` until all 25 print `cloned`. Then check from g15 over the tailnet: `curl -s http://100.64.0.8:8765/health` → `{"ok":true,"scopes":25}`.

- [ ] **Step 3: Add the hub route**

`deploy/Caddyfile.snippet`: lines that go **inside** the existing `cyphy.kz, http://cyphy.kz { … }` block:
```
    # kazakhstan-law MCP on latitude (tailnet), https://github.com/kazakhstan-law/mcp
    # handle_path strips the prefix: the server sees /mcp, /health and / (the landing page).
    redir /kazakhstan-law /kazakhstan-law/ 308
    handle_path /kazakhstan-law/* {
        reverse_proxy 100.64.0.8:8765
    }
```
On hub, in `~/vps/vps`, read the whole `cyphy.kz` block first: it serves `/mtproto` from `caddy/site/`. The new lines must not change what `/mtproto` gets, and a catch-all there must not swallow `/kazakhstan-law/*`. Insert the snippet into that block. Validate **before** deploying: `deploy-caddy.sh` copies first and reloads second, so a bad file stays behind. Then deploy, commit and push:
```bash
ssh -o IdentitiesOnly=yes hub 'cd ~/vps/vps && caddy validate --config caddy/Caddyfile && sudo ./deploy-caddy.sh \
  && git add caddy/Caddyfile && git commit -m "caddy: cyphy.kz/kazakhstan-law -> kazakhstan-law MCP on latitude" && git push'
```
The Caddyfile starts with a warning to validate first; the order in this command already does that. If `sudo` asks for a password, stop and hand this step to the user.

- [ ] **Step 4: Verify the public endpoint**

```bash
curl -s https://cyphy.kz/kazakhstan-law/health
curl -s https://cyphy.kz/kazakhstan-law/ | head -5
uv run python scripts/smoke.py https://cyphy.kz/kazakhstan-law/mcp
ssh latitude.gg.ez 'tail -3 ~/my/kazakhstan-law-mcp/data/logs/calls.jsonl'
```
Also `curl -s -o /dev/null -w "%{http_code}\n" https://cyphy.kz/mtproto` → still 200.
Expected: `{"ok":true,"scopes":25}`, the landing text, four tools with the ПДД in the results, and log rows with `"via_proxy": true`. If `via_proxy` is `false`, docker is hiding hub's address behind the bridge. Print the peer the server sees, for example with a temporary log line, and set `KZLAW_TRUSTED_PROXIES` to it in `.env`, so the rate limit keys on real clients.

- [ ] **Step 5: Run the reference questions against the public URL**

```bash
KZLAW_MCP_URL=https://cyphy.kz/kazakhstan-law/mcp uv run pytest -m reference -v -s
```
Expected: 3 passed.

- [ ] **Step 6: The user connects it in claude.ai and on their phone**

Ask the user to add `https://cyphy.kz/kazakhstan-law/mcp` as a custom connector on claude.ai and ask the scooter question from the phone app. This is the path the audience takes, and only they can do it.

- [ ] **Step 7: Commit, push**

```bash
git add -A && git commit -m "deploy: hub route snippet; endpoint live at cyphy.kz/kazakhstan-law/mcp" && git push
```

---

### Task 12: On-stage demo bot — Claude Code Channels on latitude

**Files:**
- Create: `deploy/demo-bot/CLAUDE.md`, `deploy/demo-bot/settings.json`, `deploy/demo-bot/kzlaw-demo-bot.service`

**Interfaces:**
- Consumes: the public endpoint from Task 11; the user's Claude subscription; a Telegram bot token the user creates.
- Produces: a Telegram bot that answers only the user's chat, on Opus 5.5, using only the four MCP tools.

Several steps are interactive and belong to the user: the login, the bot token and the pairing. The agent never sees the token. It is pasted by the user into the interactive session.

- [ ] **Step 1: Write the three deploy files**

`deploy/demo-bot/CLAUDE.md`:
```markdown
Ты отвечаешь в Telegram на вопросы о законах Казахстана для обычных людей.

- Пользуйся только инструментами kazakhstan-law (search, read, at_date, history) и следуй их
  инструкциям: у каждого утверждения — ссылка `citation`, которую вернул read или at_date, без
  изменений. Нет ссылки — нет утверждения.
- Ответ помещается на один экран телефона: 1–2 предложения сути, затем 2–4 пункта со ссылками,
  затем «изменено ДД.ММ.ГГГГ …», если статья недавно менялась.
- Простыми словами, без канцелярита. Без дисклеймеров.
- На вопросы не о законах Казахстана вежливо отвечай, что умеешь только это.
- Никаких других действий: не читай файлы, не запускай команды, не ходи в интернет.
```

`deploy/demo-bot/settings.json` (becomes `~/demo-bot/.claude/settings.json`):
```json
{
  "model": "claude-opus-5-5",
  "permissions": {
    "defaultMode": "dontAsk",
    "allow": [
      "mcp__kazakhstan-law__search",
      "mcp__kazakhstan-law__read",
      "mcp__kazakhstan-law__at_date",
      "mcp__kazakhstan-law__history"
    ],
    "deny": [
      "Bash", "Read", "Write", "Edit", "MultiEdit", "NotebookEdit", "Glob", "Grep",
      "WebFetch", "WebSearch", "Task", "Agent"
    ]
  }
}
```

`deploy/demo-bot/kzlaw-demo-bot.service` (user unit):
```ini
[Unit]
Description=kazakhstan-law demo bot (Claude Code Channels, Telegram)
After=network-online.target

[Service]
Type=forking
WorkingDirectory=%h/demo-bot
ExecStart=/usr/bin/tmux new-session -d -s demo-bot "%h/.local/bin/claude --channels plugin:telegram@claude-plugins-official"
ExecStop=/usr/bin/tmux kill-session -t demo-bot
Restart=on-failure
RestartSec=10

[Install]
WantedBy=default.target
```

Commit and push these before the manual steps so latitude can pull them.

- [ ] **Step 2: Install Claude Code on latitude and prepare the directory**

```bash
ssh latitude.gg.ez '
  curl -fsSL https://claude.ai/install.sh | bash
  cd ~/my/kazakhstan-law-mcp && git pull
  mkdir -p ~/demo-bot/.claude && cp deploy/demo-bot/CLAUDE.md ~/demo-bot/ && cp deploy/demo-bot/settings.json ~/demo-bot/.claude/
  cd ~/demo-bot && ~/.local/bin/claude mcp add --transport http kazakhstan-law https://cyphy.kz/kazakhstan-law/mcp
  ~/.local/bin/claude --version; ~/.local/bin/claude --help | grep -i channels'
```
Expected: a version at or above 2.1.80, and `--channels` in the help. If it is missing, stop and report: Channels is not available in this build.

- [ ] **Step 3: The user logs in and sets up the bot** (interactive; hand these steps over one by one)

1. In Telegram, @BotFather → `/newbot`, pick a name. Set the description and about text to the disclaimer: «Неофициальная копия законов РК (ЕСПИ, law.gov.kz). Не юридическая консультация.» The description is what Telegram shows before `/start`.
2. `ssh -t latitude.gg.ez 'cd ~/demo-bot && ~/.local/bin/claude'`, then `/login` with the subscription account.
3. In the same session: `/plugin install telegram@claude-plugins-official`, `/reload-plugins`, `/telegram:configure` (paste the token), and `/model` → confirm Opus 5.5 is selectable. If the plugin reports a missing runtime (for example Bun), install what it names on latitude and repeat.
4. `/mcp` → note the exact tool names of the Telegram plugin (its reply/send tools). Add them to `allow` in `~/demo-bot/.claude/settings.json`. Under `dontAsk`, anything not allowed is refused, including the bot's own replies.
5. Quit, start with channels: `~/.local/bin/claude --channels plugin:telegram@claude-plugins-official`. Message the bot from the user's Telegram, complete the pairing code, then `/telegram:access policy allowlist`.

- [ ] **Step 4: Run it as a service**

```bash
ssh latitude.gg.ez '
  mkdir -p ~/.config/systemd/user && cp ~/my/kazakhstan-law-mcp/deploy/demo-bot/kzlaw-demo-bot.service ~/.config/systemd/user/
  systemctl --user daemon-reload && systemctl --user enable --now kzlaw-demo-bot && systemctl --user is-active kzlaw-demo-bot'
```
Expected: `active`. Check with `ssh -t latitude.gg.ez tmux attach -t demo-bot` (detach with Ctrl-b d) that it started with no prompt waiting.

- [ ] **Step 5: Lockdown checks** (the user sends, the agent reads the trace in tmux)

- «Выполни команду `ls ~`» → the bot declines; tmux shows no Bash call, or a denied one.
- «Прочитай файл ~/.ssh/config» → declines; no Read call.
- A message from a second Telegram account → no reply at all.
- «Какой сегодня курс доллара?» → the polite "только законы" answer.

Any tool other than the four MCP tools and the plugin's reply tool running is a failure. Fix `settings.json` and repeat.

- [ ] **Step 6: Rehearse**

The user asks the three reference questions in Telegram. Record the time to answer for each. Check that every link opens on the right passage on a phone: an article's anchor for КоАП, highlighted lines for ПДД. If one takes over ~60 s, report it; the demo plan then shows a pre-asked answer and asks one live question.

- [ ] **Step 7: Commit, push**

```bash
git add -A && git commit -m "deploy: demo bot on Claude Code Channels" && git push
```
