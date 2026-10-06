"""changes: what one version of an act changed, article by article; or, for an amending act,
the acts it changed.

The two sides are compared by article anchor, not by line: a split code renames its parts and
an amendment shifts every line after it, so only the anchor names the same article on both
sides. Footnotes (`> *Сноска…*`) are compared apart from the text: every amendment rewrites
them, and counting them would mark every touched article as changed.
"""

from __future__ import annotations

import datetime as dt
import difflib
import re
from collections.abc import Callable
from dataclasses import dataclass

from kzlaw_mcp import diffs
from kzlaw_mcp.corpus import ActRef, Corpus, InputError, check_lang, locator_label, title_of
from kzlaw_mcp.gitio import NULL_BLOB
from kzlaw_mcp.history import FORMAT, parse_log
from kzlaw_mcp.locate import (
    ANCHOR_ID,
    ANCHOR_LINE,
    HEADING,
    PLACEHOLDER,
    POINT_START,
    footnote_acts,
    line_context,
    stage,
    stage_between,
)

ACT_DIR = re.compile(r"^.*?-[0-9]+(?=/)")
SHA = re.compile(r"^[0-9a-f]{7,40}$")
MAX_ITEMS = 40
STATUSES = ("added", "removed", "modified", "renumbered", "moved")
MAX_ITEM_TEXT = 4_000
MAX_TOTAL_TEXT = 20_000
MAX_ANCHOR_TEXT = 12_000
MAX_AMENDED = 100
MAX_PENDING = 30
MAX_PENDING_TRACED = 10
MAX_SUMMARY = 150
SHORT = 10  # a sha prefix: changes takes 7-40 characters
MAX_VERSIONS = 60
MAX_ANCHORS = 50
RANGE = re.compile(r"^st([0-9]+(?:-[0-9]+)*)\.\.st([0-9]+(?:-[0-9]+)*)$")
PENDING_NEEDLES = ["вводится в действие", "Вводится в действие", "қолданысқа енгізіледі"]
EFFECTIVE = re.compile(r"(?:с (\d{2})\.(\d{2})\.(\d{4})|(\d{2})\.(\d{2})\.(\d{4}) бастап)")
NOTE = (
    "items: the articles (or points) this version added, removed or modified, compared with "
    "the previous version; diff lines start with '-' (old) or '+' (new). stage 'announced': "
    "it inserted a placeholder ('вводится в действие …') whose text comes into force later; "
    "'took_effect': a placeholder was replaced by the text now in force. footnote_only: "
    "only the footnotes changed. A '~' diff line is one long paragraph diffed by words: "
    "[-old-] {+new+}, '…' for unchanged words. moved: text that only moved from one article "
    "to another (a section that now follows newly inserted points), left out of their diffs; "
    "status 'renumbered': the same text under a new number (from). cause_acts: the amending acts the item's footnote gained, "
    "the act that made that change. Cite with the item's citation (new text) or before_citation (old), as is. "
    "total and counts cover the whole version; a large one comes in pages: next_offset is the "
    "offset for the next page (null on the last), index lists every item."
)

PERIOD_NOTE = (
    "Period: each item is one article (or point) as it stood the day before since "
    "(before_citation) against the end of the period (citation), with the net diff; "
    "touched_by lists the versions in the period that changed its text, oldest first; "
    "versions: every version of the act in the period, with its amending act (act); "
    "changes(act_code, sha) shows one version alone. An article changed and changed back within the period "
    "is not listed. total and counts cover the whole period; a large one comes in pages: "
    "next_offset is the offset for the next page (null on the last), index lists every item."
)
SUMMARY_NOTE = (
    " summary: no text, diffs or citations; pass anchor=... without summary for one in full."
)


@dataclass(frozen=True)
class Segment:
    key: str
    label: str
    heading: str | None
    file: str
    start: int  # 1-based, inclusive
    end: int
    body: list[str]
    footnotes: list[str]
    anchored: bool


def _label(key: str, anchored: bool, heading: str | None) -> str:
    if anchored:
        if label := locator_label(key, None):
            return label
        if m := re.match(r"^(?:an([0-9-]+)_)?p([0-9-]+)$", key):
            return (f"прил. {m.group(1)}, " if m.group(1) and m.group(1) != "0" else "") + (
                f"п. {m.group(2)}"
            )
        return key
    return f"п. {key.split(chr(0))[1]}"


def _segment(
    file: str, key: str, anchored: bool, heading: str | None, lines: list[str], i: int, j: int
) -> Segment:
    while j > i + 1 and not lines[j - 1].strip():
        j -= 1
    chunk = lines[i:j]
    body = [
        ln
        for ln in chunk
        if ln.strip() and not ln.lstrip().startswith(">") and not ANCHOR_LINE.match(ln)
    ]
    notes = [ln.strip() for ln in chunk if ln.lstrip().startswith(">")]
    return Segment(
        key, _label(key, anchored, heading), heading, file, i + 1, j, body, notes, anchored
    )


def segments(file: str, text: str) -> list[Segment]:
    """The file's top-level articles by anchor; in a file without anchors, its points."""
    lines = text.split("\n")
    anchors = [(i, m.group(1)) for i, ln in enumerate(lines) if (m := ANCHOR_LINE.match(ln))]
    out: list[Segment] = []
    if anchors:
        top: str | None = None
        starts = []
        for i, a in anchors:
            if top and a.startswith(top + "_"):
                continue
            top = a
            starts.append((i, a))
        for n, (i, a) in enumerate(starts):
            stop = starts[n + 1][0] if n + 1 < len(starts) else len(lines)
            level, title, j = None, None, i + 1
            while j < stop:
                if m := HEADING.match(lines[j]):
                    if level is None:
                        level, title = len(m.group(1)), m.group(2)
                    elif len(m.group(1)) <= level:
                        break
                j += 1
            out.append(_segment(file, a, True, title, lines, i, j))
        return out

    heading, seen = None, {}
    i = 0
    while i < len(lines):
        if m := HEADING.match(lines[i]):
            heading = m.group(2)
            i += 1
            continue
        m = POINT_START.match(lines[i])
        if not m:
            i += 1
            continue
        j = i + 1
        while j < len(lines) and not (
            POINT_START.match(lines[j]) or HEADING.match(lines[j]) or ANCHOR_LINE.match(lines[j])
        ):
            j += 1
        # Annexes restart numbering: the heading and the repeat count keep the keys apart.
        base = f"{heading or ''}\0{m.group(1)}"
        seen[base] = seen.get(base, 0) + 1
        out.append(_segment(file, f"{base}\0{seen[base]}", False, heading, lines, i, j))
        i = j
    return out


def _clip(lines: list[str], budget: int) -> tuple[str, bool]:
    text = "\n".join(lines)
    return (text, False) if len(text) <= budget else (text[:budget] + "\n[…]", True)


def _side(
    corpus: Corpus, ref: ActRef, sha: str, names: list[str]
) -> tuple[dict[str, Segment], dict[str, int], list[str]]:
    g = corpus.git(ref.scope)
    segs: dict[str, Segment] = {}
    sizes: dict[str, int] = {}
    rest: list[str] = []  # text outside every article: chapter headings, unanchored provisions
    for f in g.ls_tree(sha, *names):
        text = g.blob(sha, f)
        sizes[f] = len(text.encode("utf-8"))
        lines = text.split("\n")
        covered = [False] * len(lines)
        for s in segments(f, text):
            segs.setdefault(s.key, s)
            covered[s.start - 1 : s.end] = [True] * (s.end - s.start + 1)
        rest += [
            ln
            for ln, c in zip(lines, covered, strict=True)
            if not c and ln.strip() and not ln.lstrip().startswith((">", "↑")) and "](" not in ln
        ]
    return segs, sizes, rest


def _url(corpus: Corpus, ref: ActRef, sha: str, s: Segment, sizes: dict[str, int]) -> str:
    return corpus.citation_url(
        ref,
        sha,
        s.file,
        anchor=s.key if s.anchored else None,
        lines=(s.start, s.end),
        size=sizes[s.file],
    )


def _version(corpus: Corpus, ref: ActRef, sha: str | None, date: str | None) -> dict:
    g = corpus.git(ref.scope)
    if sha:
        sha = sha.strip().lower()
        if not SHA.match(sha):
            raise InputError("sha is a commit sha from history (7-40 hex characters)")
        full = g.rev_parse(sha)
        if full is None:
            raise InputError(f"no commit {sha} in scope {ref.scope}; take the sha from history")
        found = parse_log(
            g.log("-1", f"--format={FORMAT}", full, "--", ref.path), corpus, ref.scope
        )
        if not found or found[0]["sha"] != full:
            raise InputError(
                f"commit {sha} did not change act {ref.code}; history lists its versions"
            )
        return found[0]
    args = ["-1", f"--format={FORMAT}"]
    if date:
        args.append(f"--before={date}T23:59:59Z")
    # A repealed act's last version is the one before its repeal commit.
    found = parse_log(g.log(*args, corpus.last_sha(ref), "--", ref.path), corpus, ref.scope)
    if not found:
        raise InputError(f"act {ref.code} has no version on or before {date}")
    return found[0]


def pending(corpus: Corpus, ref: ActRef, sha: str, files: list[str]) -> dict:
    """Provisions already enacted but not in force yet: their text is a placeholder.

    The placeholder names the amending act and the date or condition; the new text itself
    enters the corpus only on that date. The version that inserted it is the newest one whose
    diff adds or removes the line: the line is still there, so that one added it.
    """
    g = corpus.git(ref.scope)
    found = [
        (f, n, t.strip())
        for f, n, t in g.grep_lines(sha, PENDING_NEEDLES, files)
        if not t.lstrip().startswith((">", "*")) and PLACEHOLDER.match(t.strip())
    ]
    texts: dict[str, list[str]] = {}
    sizes: dict[str, int] = {}
    items = []
    for i, (f, n, t) in enumerate(found[:MAX_PENDING]):
        if f not in texts:
            blob = g.blob(sha, f)
            texts[f], sizes[f] = blob.split("\n"), len(blob.encode("utf-8"))
        ctx = line_context(texts[f], n)
        m = EFFECTIVE.search(t)
        d = [x for x in m.groups() if x] if m else []
        url = corpus.citation_url(ref, sha, f, anchor=ctx.anchor, lines=(n, n), size=sizes[f])
        label = locator_label(ctx.anchor, ctx.point) or (ctx.heading or "")[:80]
        if sub := re.match(r"^([0-9-]+)\)", t):
            label = f"{label}, пп. {sub.group(1)}" if label else f"пп. {sub.group(1)}"
        item: dict = {
            "label": label,
            "anchor": ctx.anchor,
            "point": ctx.point,
            "text": t[:300],
            "effective": f"{d[2]}-{d[1]}-{d[0]}" if d else None,
            "url": url,
        }
        if i < MAX_PENDING_TRACED:
            log = g.log("-1", f"--format={FORMAT}", f"-S{t}", sha, "--", f)
            if intro := parse_log(log, corpus, ref.scope):
                item["announced_in"] = {
                    k: intro[0][k] for k in ("date", "sha", "cause_act_code", "cause_act_requisite")
                }
        items.append(item)
    return {"pending": items, "pending_more": max(0, len(found) - MAX_PENDING)}


def _title(corpus: Corpus, code: str) -> str:
    try:
        ref = corpus.find(code)
    except InputError:
        return ""
    return title_of(corpus.meta(ref, corpus.head(ref.scope)), "rus")


def amended_by(corpus: Corpus, code: str, offset: int = 0) -> dict | None:
    """An amending act, which the corpus keeps only as commit trailers: the acts it changed."""
    fmt = (
        "%x1e%H%x1f%cs%x1f%(trailers:key=Cause-Act-Requisite,valueonly,separator=%x20)%x1f"
        "%(trailers:key=Cause-Act-Title,valueonly,separator=%x20)%x1f"
        "%(trailers:key=Cause-Act-Link,valueonly,separator=%x20)"
    )
    info: dict = {}
    acts: list[dict] = []
    for scope in corpus.scopes():
        g = corpus.git(scope)
        out = g.log(
            f"--grep=^Cause-Act-Code: {code}$",
            f"--format={fmt}",
            "--name-only",
            corpus.head(scope),
        )
        for record in out.split("\x1e"):
            if not record.strip():
                continue
            head_line, _, names = record.partition("\n")
            sha, date, requisite, title, link = head_line.split("\x1f")
            info = info or {
                "requisite": requisite.strip(),
                "title": title.strip(),
                "link": link.strip(),
            }
            # Any file of an act names it: the act's directory ends in its code.
            dirs = dict.fromkeys(m.group(0) for n in names.split() if (m := ACT_DIR.match(n)))
            for act_dir in dirs:
                act_code = act_dir.rsplit("-", 1)[1]
                acts.append(
                    {
                        "act_code": act_code,
                        "scope": scope,
                        "path": act_dir,
                        "date": date,
                        "sha": sha,
                        "url": corpus.commit_url(scope, sha),
                    }
                )
    if not acts:
        return None
    acts.sort(key=lambda a: (a["date"], a["path"]))
    offset = max(0, int(offset))
    page = acts[offset : offset + MAX_AMENDED]
    titles: dict[str, str] = {}
    for a in page:
        if a["act_code"] not in titles:
            titles[a["act_code"]] = _title(corpus, a["act_code"])
        a["title"] = titles[a["act_code"]]
    shown = offset + len(page)
    return {
        "act_code": code,
        "amending_act": info,
        "acts_total": len({a["act_code"] for a in acts}),
        "entries_total": len(acts),
        "offset": offset,
        "next_offset": shown if shown < len(acts) else None,
        "acts_changed": page,
        "note": (
            "This is an amending act: the corpus has no text of it, only the versions it made "
            "of other acts (one entry per act and date; a law taking effect in stages has "
            "several dates). acts_total counts the distinct acts it changed, entries_total the "
            "entries; the entries come in pages of "
            f"{MAX_AMENDED}, next_offset is the next page's offset (null on the last). Call "
            "changes(act_code, sha) on an entry to see what it changed there; its official text "
            "is at amending_act.link."
        ),
    }


def _check_date(name: str, value: str | None) -> None:
    if value is None:
        return
    try:
        if len(value) != 10:
            raise ValueError
        dt.date.fromisoformat(value)
    except (TypeError, ValueError):
        raise InputError(f"{name} must be YYYY-MM-DD") from None


def _st_number(key: str) -> tuple[int, ...] | None:
    m = re.match(r"^st([0-9]+(?:-[0-9]+)*)$", key)
    return tuple(int(n) for n in m.group(1).split("-")) if m else None


def _wanted(
    corpus: Corpus, ref: ActRef, sha: str, lang: str, anchors: list[str], chapter: str | None
) -> Callable[[str, Segment], bool] | None:
    """Which articles to compare: the anchors, st-ranges and part the model asked for."""
    if len(anchors) > MAX_ANCHORS:
        raise InputError(f"anchors takes at most {MAX_ANCHORS} anchors or ranges")
    exact: set[str] = set()
    ranges: list[tuple[tuple[int, ...], tuple[int, ...]]] = []
    for a in (a.strip() for a in anchors):
        if m := RANGE.match(a):
            lo, hi = _st_number(f"st{m.group(1)}"), _st_number(f"st{m.group(2)}")
            assert lo is not None and hi is not None
            ranges.append((lo, hi))
        elif ANCHOR_ID.match(a):
            exact.add(a)
        else:
            raise InputError(
                f"anchors holds anchors (st592, an0_p168-1) or article ranges (st570..st621), "
                f"not {a!r}"
            )
    if chapter is not None:
        chapter = chapter.strip().removesuffix(".md").rsplit("/", 1)[-1]
        parts = sorted(
            {f.rsplit("/", 1)[1][:-3] for f in corpus.lang_files(ref, sha, lang) if "/" in f}
            - {lang}
        )
        if not parts:
            raise InputError(
                f"act {ref.code} is not split into parts: narrow it with anchors instead, "
                "e.g. ['st570..st621']"
            )
        if chapter not in parts:
            raise InputError(
                f"act {ref.code} has no part {chapter!r}; its parts: {', '.join(parts[:80])}"
            )
    if not (exact or ranges or chapter):
        return None

    def want(key: str, seg: Segment) -> bool:
        if chapter and seg.file.rsplit("/", 1)[-1][:-3] != chapter:
            return False
        if not (exact or ranges) or key in exact:
            return True
        n = _st_number(key)
        return n is not None and any(lo <= n and n[: len(hi)] <= hi for lo, hi in ranges)

    return want


Entry = tuple[str, dict, list[str], str]  # key, item, its text or diff lines, the field name


def _compare(
    corpus: Corpus,
    ref: ActRef,
    old: str | None,
    new: str,
    names: list[str],
    before_label: str,
    want: Callable[[str, Segment], bool] | None,
) -> tuple[list[Entry], list[str]]:
    """The articles that differ between commits `old` (None: nothing yet) and `new`."""
    before, old_sizes, old_rest = _side(corpus, ref, old, names) if old else ({}, {}, [])
    after, new_sizes, new_rest = _side(corpus, ref, new, names)
    keys = list(after) + [k for k in before if k not in after]
    if want:
        keys = [k for k in keys if want(k, after.get(k) or before[k])]

    # Every changed item first, text attached later: the page is cut by the text budget, and
    # the index and counts cover all of them, so the model can count and page through the rest.
    entries: list[Entry] = []
    footnote_only: list[str] = []
    for key in keys:
        a, b = before.get(key), after.get(key)
        if a and b and a.body == b.body:
            if a.footnotes != b.footnotes:
                footnote_only.append(b.label)
            continue
        cur = b or a
        assert cur is not None
        item: dict = {"label": cur.label, "heading": cur.heading}
        if cur.anchored:
            item["anchor"] = key
        if a and b:
            diff = [
                ln
                for ln in difflib.unified_diff(a.body, b.body, n=1, lineterm="")
                if not ln.startswith(("---", "+++"))
            ]
            diff = [
                "…" if ln.startswith("@@") else ln
                for n, ln in enumerate(diff)
                if not (n == 0 and ln.startswith("@@"))
            ]
            item["status"] = "modified"
            removed = [ln[1:] for ln in diff if ln.startswith("-")]
            added = [ln[1:] for ln in diff if ln.startswith("+")]
            lines = diff
        elif b:
            item["status"] = "added"
            removed, added, lines = [], b.body, b.body
        else:
            assert a is not None
            item["status"] = "removed"
            removed, added, lines = a.body, [], a.body
        if st := stage(removed, added):
            item["stage"] = st
        # The act a footnote gained here made this change: a version can carry several acts.
        if b and (new_acts := _gained_acts(a, b)):
            item["cause_acts"] = new_acts
        if b:
            url = _url(corpus, ref, new, b, new_sizes)
            item["citation"] = f"[{b.label}]({url})"
        if a and old:
            url = _url(corpus, ref, old, a, old_sizes)
            item["before_citation"] = f"[{a.label}, ред. до {before_label}]({url})"
        entries.append((key, item, lines, "diff" if a and b else "text"))
    if old_rest != new_rest and not want:
        diff = [
            ln
            for ln in difflib.unified_diff(old_rest, new_rest, n=1, lineterm="")
            if not ln.startswith(("---", "+++", "@@"))
        ]
        item = {
            "label": "вне статей",
            "heading": None,
            "status": "modified",
            "note": "text outside any article (chapter headings, unnumbered provisions); "
            "read the act to cite it",
        }
        entries.append(("", item, diff, "diff"))
    return entries, footnote_only


MAX_TOUCHED = 60


def _announces(entry: Entry) -> bool:
    """A change that puts nothing in force: a placeholder, or a bare heading over one."""
    _, item, lines, field = entry
    if item.get("stage") == "announced":
        return True
    if item["status"] == "removed":
        return False
    added = lines if field == "text" else [ln[1:] for ln in lines if ln.startswith("+")]
    gone = [] if field == "text" else [ln for ln in lines if ln.startswith("-")]
    return bool(added) and not gone and all(HEADING.match(ln) or not ln.strip() for ln in added)


def touched(corpus: Corpus, ref: ActRef, sha: str, lang: str = "rus") -> dict:
    """The articles one version changed (anchors), and whether it only inserted placeholders.

    Empty for a version the act's previous one does not precede (its first, or its repeal).
    """
    g = corpus.git(ref.scope)
    old = g.rev_parse(f"{sha}^")
    meta = f"{ref.path}/meta.yaml"
    if old is None or not g.ls_tree(old, meta) or not g.ls_tree(sha, meta):
        return {}
    names = g.diff_names(old, sha, f"{ref.path}/{lang}.md", f"{ref.path}/{lang}")
    entries = _readable(_compare(corpus, ref, old, sha, names, "", None)[0])[0] if names else []
    anchors = [item["anchor"] for _, item, _, _ in entries if "anchor" in item]
    out: dict = {
        "touched_anchors": anchors[:MAX_TOUCHED],
        # A version on an act's adoption day often only announces text that comes later.
        "placeholders_only": bool(entries) and all(_announces(e) for e in entries),
    }
    if len(anchors) > MAX_TOUCHED:
        out["touched_more"] = len(anchors) - MAX_TOUCHED
    if unanchored := sum("anchor" not in item for _, item, _, _ in entries):
        out["touched_unanchored"] = unanchored
    return out


def _readable(entries: list[Entry]) -> tuple[list[Entry], list[dict]]:
    """Moves and renumbering taken out, long paragraphs diffed by words."""
    entries, moved = diffs.moves(entries)
    entries = diffs.renumbered(entries)
    return [
        (k, i, diffs.word_diffs(ln) if f == "diff" else ln, f) for k, i, ln, f in entries
    ], moved


def _gained_acts(a: Segment | None, b: Segment) -> list[dict]:
    old = set(footnote_acts(a.footnotes)) if a else set()
    return [{"date": d, "number": n} for d, n in footnote_acts(b.footnotes) if (d, n) not in old]


CAUSE_NUMBER = re.compile(r"№\s*([0-9]+(?:-[IVXL]+)?)")


def _attribution(version: dict, entries: list[Entry]) -> dict:
    """cause_acts when the footnotes name other acts than the version's, or more than one."""
    acts = {
        (c["date"], c["number"]): c for _, item, _, _ in entries for c in item.get("cause_acts", [])
    }
    m = CAUSE_NUMBER.search(version.get("cause_act_requisite") or "")
    if not acts or (m and {n for _, n in acts} == {m.group(1)}):
        return {}
    return {
        "cause_acts": [acts[k] for k in sorted(acts)],
        "attribution_ambiguous": True,
        "attribution_note": "this version's footnotes name other amending acts than version.act, "
        "or several: the git version records one act per day, but several took effect together. "
        "Name the act from the item's cause_acts (its footnote), not version.act",
    }


def _page(entries: list[Entry], offset: int, one_anchor: bool, summary: bool) -> dict:
    offset = max(0, int(offset))
    page: list[dict] = []
    if summary:
        lean = ("label", "anchor", "status", "stage", "touched_by")
        page = [
            {k: e[1][k] for k in lean if k in e[1]} | {"heading": (e[1]["heading"] or "")[:120]}
            for e in entries[offset : offset + MAX_SUMMARY]
        ]
    else:
        spent = 0
        for _, item, lines, field in entries[offset:]:
            if len(page) >= MAX_ITEMS:
                break
            cap = MAX_ANCHOR_TEXT if one_anchor else MAX_ITEM_TEXT
            room = MAX_TOTAL_TEXT - spent
            # A page ends before an item whose text would not fit, never inside it.
            if page and min(len("\n".join(lines)), cap) > room:
                break
            text, cut = _clip(lines, min(cap, max(room, 500)))
            page.append({**item, field: text, "truncated": cut})
            spent += len(text)
    shown = offset + len(page)
    paged = {
        "items": page,
        "total": len(entries),
        "counts": {s: sum(1 for e in entries if e[1]["status"] == s) for s in STATUSES},
        "offset": offset,
        "next_offset": shown if shown < len(entries) else None,
    }
    if len(page) < len(entries) and not summary:
        paged["index"] = [f"{e[1]['label']}: {e[1]['status']}" for e in entries]
    return paged


def _touched(
    corpus: Corpus, ref: ActRef, since: str, end: str, paths: tuple[str, ...], keys: set[str]
) -> dict[str, list[dict]]:
    """For each key, the versions from `since` to `end` that changed its text, oldest first.

    One `git log --raw` names each version's changed files and their blobs; a file's segments
    are parsed once per blob, since the new side of one version is the old side of the next.
    """
    g = corpus.git(ref.scope)
    records = g.log_files(FORMAT, f"--since={since}T00:00:00Z", end, "--", *paths)
    bodies: dict[str, dict[str, list[str]]] = {NULL_BLOB: {}}
    out: dict[str, list[dict]] = {k: [] for k in keys}
    for header, files in reversed(records):
        need = {b: path for path, pair in files.items() for b in pair if b not in bodies}
        for (blob, path), text in zip(need.items(), g.blobs(list(need)), strict=True):
            bodies[blob] = {s.key: s.body for s in segments(path, text or "")}
        old: dict[str, list[str]] = {}
        new: dict[str, list[str]] = {}
        for o, n in files.values():
            old |= bodies[o]
            new |= bodies[n]
        commit = parse_log(header, corpus, ref.scope)[0]
        for k in keys:
            a, b = old.get(k), new.get(k)
            if a == b:
                continue
            touch = {"date": commit["date"], "sha": commit["sha"][:SHORT]}
            if st := stage_between(a, b):
                touch["stage"] = st
            out[k].append(touch)
    return out


def _period(
    corpus: Corpus,
    ref: ActRef,
    lang: str,
    since: str,
    until: str | None,
    anchors: list[str],
    chapter: str | None,
    offset: int,
    summary: bool,
    one_anchor: bool,
) -> dict:
    g = corpus.git(ref.scope)
    end = _version(corpus, ref, None, until)
    want = _wanted(corpus, ref, end["sha"], lang, anchors, chapter)
    day_before = (dt.date.fromisoformat(since) - dt.timedelta(days=1)).isoformat()
    found = parse_log(
        g.log(
            "-1",
            f"--format={FORMAT}",
            f"--before={day_before}T23:59:59Z",
            end["sha"],
            "--",
            ref.path,
        ),
        corpus,
        ref.scope,
    )
    base = found[0] if found and g.ls_tree(found[0]["sha"], f"{ref.path}/meta.yaml") else None
    versions = (
        parse_log(
            g.log(f"--format={FORMAT}", f"--since={since}T00:00:00Z", end["sha"], "--", ref.path),
            corpus,
            ref.scope,
        )
        if end["date"] >= since
        else []
    )

    def short(v: dict) -> dict:
        return {"date": v["date"], "sha": v["sha"][:SHORT], "act": v["cause_act_requisite"]}

    result: dict = {
        "act_code": ref.code,
        "scope": ref.scope,
        "title": title_of(corpus.meta(ref, end["sha"]), lang),
        "lang": lang,
        "period": {
            "since": since,
            "until": until,
            "from": short(base) if base else None,
            "to": short(end),
        },
        "versions_total": len(versions),
        "versions": [short(v) for v in versions[:MAX_VERSIONS]],
    }
    if not versions:
        return result | {"items": [], "note": "The act has no version in this period."}
    paths = (f"{ref.path}/{lang}.md", f"{ref.path}/{lang}")
    old = base["sha"] if base else None
    names = (
        g.diff_names(old, end["sha"], *paths) if old else corpus.lang_files(ref, end["sha"], lang)
    )
    entries, footnote_only = _compare(corpus, ref, old, end["sha"], names, since, want)
    entries, moved = _readable(entries)
    touched = _touched(corpus, ref, since, end["sha"], paths, {e[0] for e in entries if e[0]})
    for key, item, _, _ in entries:
        if key:
            item["touched_by"] = touched[key]
    note = PERIOD_NOTE + (SUMMARY_NOTE if summary else "")
    return (
        result
        | ({"moved": moved} if moved else {})
        | _page(entries, offset, one_anchor, summary)
        | {"footnote_only": footnote_only, "note": note}
    )


def changes(
    corpus: Corpus,
    act_code: str,
    sha: str | None = None,
    date: str | None = None,
    lang: str = "rus",
    anchor: str | None = None,
    offset: int = 0,
    since: str | None = None,
    until: str | None = None,
    anchors: list[str] | None = None,
    chapter: str | None = None,
    summary: bool = False,
) -> dict:
    lang = check_lang(lang)
    anchor = anchor.strip() if anchor else None
    if anchor and not ANCHOR_ID.match(anchor):
        raise InputError("anchor looks like st592 or an0_p168-1 (take it from read or search)")
    for name, value in (("date", date), ("since", since), ("until", until)):
        _check_date(name, value)
    if since is None and until is not None:
        raise InputError("until closes a period: pass since too")
    if since is not None and (sha or date):
        raise InputError("since/until ask for a period, sha or date for one version: pass one")
    if since and until and until < since:
        raise InputError("until is before since")
    wanted = [*(anchors or []), *([anchor] if anchor else [])]
    one_anchor = bool(anchor) and not anchors and not chapter
    code = str(act_code).strip()
    try:
        ref = corpus.find_any(act_code)
    except InputError:
        if code.isdigit() and (amended := amended_by(corpus, code, offset)):
            return amended
        raise
    # Thousands of repealed acts also amended others (a law that enacts a code amends the
    # rest): asked for no version of their own, they answer with the acts they changed.
    if (
        not (sha or date or since or wanted or chapter)
        and corpus.repealed(code)
        and (amended := amended_by(corpus, code, offset))
    ):
        return amended
    if since is not None:
        return _period(
            corpus, ref, lang, since, until, wanted, chapter, offset, summary, one_anchor
        )

    g = corpus.git(ref.scope)
    version = _version(corpus, ref, sha, date)
    new = version["sha"]
    if not g.ls_tree(new, f"{ref.path}/meta.yaml"):
        replaced = corpus.replaced(ref.code)
        return {
            "act_code": ref.code,
            "scope": ref.scope,
            "version": version,
            "repealed": True,
            "replaced_by": replaced.successor if replaced else None,
            "items": [],
            "note": "This version repealed the act: its text ends here. changes on the act that "
            "replaced it (replaced_by), or on this act's earlier versions from history.",
        }
    want = _wanted(corpus, ref, new, lang, wanted, chapter)
    result: dict = {
        "act_code": ref.code,
        "scope": ref.scope,
        "title": title_of(corpus.meta(ref, new), lang),
        "lang": lang,
        "version": version,
    }
    old = g.rev_parse(f"{new}^")
    if old is None or not g.ls_tree(old, f"{ref.path}/meta.yaml"):
        return result | {
            "previous": None,
            "items": [],
            "note": "This is the act's first version: there is nothing earlier to compare.",
        }
    prev = parse_log(g.log("-1", f"--format={FORMAT}", old, "--", ref.path), corpus, ref.scope)
    # The act's previous version: the same files as the parent, and a sha history lists.
    old = prev[0]["sha"]
    result["previous"] = {k: prev[0][k] for k in ("date", "sha", "subject", "cause_act_requisite")}

    names = g.diff_names(old, new, f"{ref.path}/{lang}.md", f"{ref.path}/{lang}")
    if not names:
        return result | {
            "items": [],
            "note": f"This version changed no '{lang}' text: only its metadata, or the other "
            "language's text.",
        }
    entries, footnote_only = _compare(corpus, ref, old, new, names, version["date"], want)
    entries, moved = _readable(entries)
    note = NOTE + (SUMMARY_NOTE if summary else "")
    return (
        result
        | _attribution(version, entries)
        | ({"moved": moved} if moved else {})
        | _page(entries, offset, one_anchor, summary)
        | {"footnote_only": footnote_only, "note": note}
    )
