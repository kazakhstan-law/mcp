"""The corpus as a set of git clones: act index by code, metadata, files, citation links."""

from __future__ import annotations

import re
import threading
import time
from dataclasses import dataclass
from urllib.parse import quote

import yaml

from kzlaw_mcp.config import ALL_SCOPES, Settings
from kzlaw_mcp.gitio import CommandError, Git

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


@dataclass(frozen=True)
class Predecessor:
    """A repealed act that an act in force replaced (`replaces:` in the successor's meta.yaml).

    Its files are deleted at the repeal, so it has no meta.yaml at HEAD: what is known about it
    comes from the successor's `replaces:` entry, and its text from the history before the repeal.
    """

    ref: ActRef
    successor: str
    title: dict
    requisite: str
    link: str


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
        self._replaced: dict[str, Predecessor] = {}
        self._heads: dict[str, str] = {}
        self._checked = float("-inf")
        self._lock = threading.Lock()

    def scopes(self) -> list[str]:
        """Scopes whose clone has a commit. A clone still in progress has `.git` but no HEAD."""
        self._refresh()
        return [s for s in ALL_SCOPES if s in self._heads]

    def git(self, scope: str) -> Git:
        return Git(self.settings.corpus_root / scope, self.settings.subprocess_timeout_s)

    def head(self, scope: str) -> str:
        self._refresh()
        try:
            return self._heads[scope]
        except KeyError:
            raise InputError(f"scope {scope} is not available right now") from None

    def find(self, act_code: str) -> ActRef:
        code = str(act_code).strip()
        if not ACT_CODE.match(code):
            raise InputError(f"act_code must be the act's numeric code, got {act_code!r}")
        self._refresh()
        try:
            return self._index[code]
        except KeyError:
            pass
        if pred := self._replaced.get(code):
            raise InputError(
                f"act {code} was repealed and replaced by act {pred.successor}: read "
                f"{pred.successor} for the law now; at_date or history on {code} for its past text"
            )
        raise InputError(
            f"act {code} is not in the corpus (only acts in force are indexed); use search"
        )

    def find_any(self, act_code: str) -> ActRef:
        """Like find, but also a repealed act that an act in force replaced."""
        code = str(act_code).strip()
        self._refresh()
        if pred := self._replaced.get(code):
            return pred.ref
        return self.find(code)

    def replaced(self, code: str) -> Predecessor | None:
        self._refresh()
        return self._replaced.get(code)

    def last_sha(self, ref: ActRef) -> str:
        """The last commit at which the act's files exist: HEAD, or the parent of its repeal."""
        head = self.head(ref.scope)
        if self.git(ref.scope).ls_tree(head, f"{ref.path}/meta.yaml"):
            return head
        gone = self.git(ref.scope).log("-1", "--format=%H", head, "--", f"{ref.path}/meta.yaml")
        return f"{gone.strip()}^"

    def predecessors(self, ref: ActRef, sha: str | None = None) -> list[Predecessor]:
        """The acts `ref` replaced, as its meta.yaml names them at `sha` (default: its last)."""
        meta = self.meta(ref, sha or self.last_sha(ref))
        return [
            Predecessor(
                ActRef(str(e["code"]), ref.scope, e["path"]),
                ref.code,
                e.get("title") or {},
                e.get("requisite", ""),
                e.get("link", ""),
            )
            for e in meta.get("replaces") or []
            if e.get("code") and e.get("path")
        ]

    def meta(self, ref: ActRef, sha: str) -> dict:
        return yaml.safe_load(self.git(ref.scope).blob(sha, f"{ref.path}/meta.yaml")) or {}

    def lang_files(self, ref: ActRef, sha: str, lang: str) -> list[str]:
        """`<act>/<lang>.md` first, then its parts `<act>/<lang>/*.md`, as they are at `sha`."""
        main = f"{ref.path}/{lang}.md"
        files = self.git(ref.scope).ls_tree(sha, main, f"{ref.path}/{lang}")
        return sorted(files, key=lambda f: (f != main, f))

    def citation_url(
        self,
        ref: ActRef,
        sha: str,
        file: str,
        *,
        anchor: str | None,
        lines: tuple[int, int] | None,
        size: int,
    ) -> str:
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
            root = self.settings.corpus_root
            for scope in ALL_SCOPES:
                try:
                    if not (root / scope / ".git").exists():
                        raise CommandError(f"{scope} is not cloned")
                    head = self.git(scope).head()
                    if self._heads.get(scope) != head:
                        self._reindex(scope, head)
                        self._heads[scope] = head
                except CommandError:  # missing, or a clone still in progress: skip the scope
                    self._heads.pop(scope, None)
                    self._index = {c: r for c, r in self._index.items() if r.scope != scope}
                    self._replaced = {
                        c: p for c, p in self._replaced.items() if p.ref.scope != scope
                    }
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
        replaced = {c: p for c, p in self._replaced.items() if p.ref.scope != scope}
        for path, _ in g.grep(head, "^replaces:", [":(glob)**/meta.yaml"], fixed=False):
            code = CODE_IN_PATH.search(path)
            succ = index.get(code.group(1)) if code else None
            if succ is None:
                continue
            for pred in self.predecessors(succ, head):
                if pred.ref.code not in index:
                    replaced[pred.ref.code] = pred
        self._index = index
        self._replaced = replaced
