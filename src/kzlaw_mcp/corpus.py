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


@dataclass(frozen=True)
class Repealed:
    """An act repealed without a successor that names it: its files were deleted at `sha`.

    Its text is in the history only, up to `sha`'s parent; `date` is when the repeal took effect.
    """

    ref: ActRef
    date: str
    sha: str


def _load_meta(text: str) -> dict:
    loader = getattr(yaml, "CSafeLoader", yaml.SafeLoader)
    return yaml.load(text, Loader=loader) or {}


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
    def __init__(self, settings: Settings) -> None:
        self.settings = settings
        self._index: dict[str, ActRef] = {}
        self._replaced: dict[str, Predecessor] = {}
        self._heads: dict[str, str] = {}
        self._checked = float("-inf")
        self._lock = threading.Lock()
        # Built on first use, per scope and head: listing every deletion takes seconds.
        self._repealed: dict[str, tuple[str, dict[str, Repealed]]] = {}
        self._titles: dict[str, tuple[str, dict[str, dict]]] = {}
        self._repealed_lock = threading.Lock()

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
        if rep := self.repealed(code):
            title = title_of(self.repealed_meta(rep), "rus")
            raise InputError(
                f"act {code} ({title}) was repealed on {rep.date} and is not the law now. Its "
                f"text is in the history: search(act_code='{code}') searches its last version, "
                f"at_date(act_code='{code}', date before {rep.date}) reads it, history lists its "
                "versions"
            )
        raise InputError(
            f"act {code} is not in the corpus (only acts in force are indexed). An amending act "
            f"('О внесении изменений…') is kept only as the versions it made: changes(act_code="
            f"'{code}') lists the acts it changed. Otherwise use search"
        )

    def find_any(self, act_code: str) -> ActRef:
        """Like find, but also a repealed act: one an act in force replaced, or any other."""
        code = str(act_code).strip()
        self._refresh()
        if pred := self._replaced.get(code):
            return pred.ref
        if code not in self._index and ACT_CODE.match(code) and (rep := self.repealed(code)):
            return rep.ref
        return self.find(code)

    def repealed(self, code: str) -> Repealed | None:
        """A repealed act that no act in force names as replaced; None for any other code."""
        code = str(code).strip()
        self._refresh()
        if code in self._index or code in self._replaced:
            return None
        for scope in self.scopes():
            if rep := self.repealed_in(scope).get(code):
                return rep
        return None

    def repealed_in(self, scope: str) -> dict[str, Repealed]:
        head = self.head(scope)
        with self._repealed_lock:
            cached = self._repealed.get(scope)
            if cached and cached[0] == head:
                return cached[1]
        out = self.git(scope).log(
            "--diff-filter=D",
            "--format=%x1e%H%x1f%cs",
            "--name-only",
            head,
            "--",
            ":(glob)**/meta.yaml",
            max_bytes=64_000_000,
            strict=True,
        )
        found: dict[str, Repealed] = {}
        for record in out.split("\x1e"):
            header, _, names = record.strip("\n").partition("\n")
            if not header:
                continue
            sha, date = header.split("\x1f")
            for name in names.split("\n"):
                m = CODE_IN_PATH.search(name)
                # newest first: an act deleted twice (moved, then repealed) keeps its repeal
                if m and m.group(1) not in found:
                    found[m.group(1)] = Repealed(
                        ActRef(m.group(1), scope, name.rsplit("/", 1)[0]), date, sha
                    )
        with self._lock:
            live = set(self._index) | set(self._replaced)
        found = {c: r for c, r in found.items() if c not in live}
        with self._repealed_lock:
            self._repealed[scope] = (head, found)
        return found

    def repealed_meta(self, rep: Repealed) -> dict:
        return self.meta(rep.ref, f"{rep.sha}^")

    def repealed_titles(self, scope: str) -> dict[str, dict]:
        """code -> {title, requisite} of every repealed act in `scope`, from one cat-file."""
        head = self.head(scope)
        with self._repealed_lock:
            cached = self._titles.get(scope)
            if cached and cached[0] == head:
                return cached[1]
        acts = list(self.repealed_in(scope).values())
        blobs = self.git(scope).blobs([f"{r.sha}^:{r.ref.path}/meta.yaml" for r in acts])
        titles = {}
        for rep, blob in zip(acts, blobs, strict=True):
            if blob is None:
                continue
            # title and requisite come first; the rest of meta.yaml only costs parse time
            meta = _load_meta(blob.split("\nform:", 1)[0])
            titles[rep.ref.code] = {
                "title": meta.get("title") or {},
                "requisite": meta.get("requisite", ""),
            }
        with self._repealed_lock:
            self._titles[scope] = (head, titles)
        return titles

    def replaced(self, code: str) -> Predecessor | None:
        self._refresh()
        return self._replaced.get(code)

    def last_sha(self, ref: ActRef) -> str:
        """The last commit at which the act's files exist: HEAD, or the parent of its repeal."""
        repeal = self.repeal(ref)
        return f"{repeal[0]}^" if repeal else self.head(ref.scope)

    def repeal(self, ref: ActRef) -> tuple[str, str] | None:
        """(sha, date) of the commit that deleted the act's files; None while it is in force."""
        head = self.head(ref.scope)
        if self.git(ref.scope).ls_tree(head, f"{ref.path}/meta.yaml"):
            return None
        gone = self.git(ref.scope).log("-1", "--format=%H %cs", head, "--", f"{ref.path}/meta.yaml")
        sha, date = gone.split()
        return sha, date

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
