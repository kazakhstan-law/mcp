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
from dataclasses import dataclass

from kzlaw_mcp.corpus import ActRef, Corpus, InputError, check_lang, locator_label, title_of
from kzlaw_mcp.history import FORMAT, parse_log
from kzlaw_mcp.locate import ANCHOR_ID, ANCHOR_LINE, HEADING, POINT_START, line_context

ACT_DIR = re.compile(r"^.*?-[0-9]+(?=/)")
SHA = re.compile(r"^[0-9a-f]{7,40}$")
MAX_ITEMS = 60
MAX_ITEM_TEXT = 4_000
MAX_TOTAL_TEXT = 30_000
MAX_ANCHOR_TEXT = 12_000
MAX_AMENDED = 100
MAX_PENDING = 30
MAX_PENDING_TRACED = 10
PENDING_NEEDLES = ["вводится в действие", "Вводится в действие", "қолданысқа енгізіледі"]
EFFECTIVE = re.compile(r"(?:с (\d{2})\.(\d{2})\.(\d{4})|(\d{2})\.(\d{2})\.(\d{4}) бастап)")
# A provision whose text is not in force yet: the act keeps only its number and the date or
# condition it takes effect on. In Russian the line starts with it; in Kazakh it ends so.
PLACEHOLDER = re.compile(
    r"^(?:#+\s+)?(?:\*\*)?(?:Статья\s+[0-9-]+\.\s+|[0-9-]+-бап\.\s+|[0-9-]+[.)]\s+)?"
    r"(?:[Вв]водится в действие\s.*|.{0,80}қолданысқа енгізіледі\s*[-–]\s*ҚР\s.*)$"
)
NOTE = (
    "items: the articles (or points) this version added, removed or modified, compared with "
    "the previous version; diff lines start with '-' (old) or '+' (new). stage 'announced': "
    "it inserted a placeholder ('вводится в действие …') whose text comes into force later; "
    "'took_effect': a placeholder was replaced by the text now in force. footnote_only: "
    "only the footnotes changed. Cite with the item's citation (new text) or before_citation (old), as is."
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


def _stage(removed: list[str], added: list[str]) -> str | None:
    def any_placeholder(lines: list[str]) -> bool:
        return any(PLACEHOLDER.match(ln.strip()) for ln in lines)

    if any_placeholder(removed):
        return "took_effect"
    if any_placeholder(added):
        return "announced"
    return None


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


def amended_by(corpus: Corpus, code: str) -> dict | None:
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
    titles: dict[str, str] = {}
    for a in acts[:MAX_AMENDED]:
        if a["act_code"] not in titles:
            titles[a["act_code"]] = _title(corpus, a["act_code"])
        a["title"] = titles[a["act_code"]]
    return {
        "act_code": code,
        "amending_act": info,
        "acts_changed": acts[:MAX_AMENDED],
        "more": max(0, len(acts) - MAX_AMENDED),
        "note": (
            "This is an amending act: the corpus has no text of it, only the versions it made "
            "of other acts (one entry per act and date; a law taking effect in stages has "
            "several dates). Call changes(act_code, sha) on an entry to see what it changed "
            "there; its official text is at amending_act.link."
        ),
    }


def changes(
    corpus: Corpus,
    act_code: str,
    sha: str | None = None,
    date: str | None = None,
    lang: str = "rus",
    anchor: str | None = None,
) -> dict:
    lang = check_lang(lang)
    anchor = anchor.strip() if anchor else None
    if anchor and not ANCHOR_ID.match(anchor):
        raise InputError("anchor looks like st592 or an0_p168-1 (take it from read or search)")
    if date is not None:
        try:
            if len(date) != 10:
                raise ValueError
            dt.date.fromisoformat(date)
        except (TypeError, ValueError):
            raise InputError("date must be YYYY-MM-DD") from None
    try:
        ref = corpus.find_any(act_code)
    except InputError:
        code = str(act_code).strip()
        if code.isdigit() and (amended := amended_by(corpus, code)):
            return amended
        raise

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
    before, old_sizes, old_rest = _side(corpus, ref, old, names)
    after, new_sizes, new_rest = _side(corpus, ref, new, names)
    keys = list(after) + [k for k in before if k not in after]
    if anchor:
        keys = [k for k in keys if k == anchor]

    items, footnote_only, spent = [], [], 0
    for key in keys:
        a, b = before.get(key), after.get(key)
        if a and b and a.body == b.body:
            if a.footnotes != b.footnotes:
                footnote_only.append(b.label)
            continue
        cur = b or a
        assert cur is not None
        budget = MAX_ANCHOR_TEXT if anchor else min(MAX_ITEM_TEXT, MAX_TOTAL_TEXT - spent)
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
        if stage := _stage(removed, added):
            item["stage"] = stage
        if budget > 200:
            text, cut = _clip(lines, budget)
            item["diff" if a and b else "text"] = text
            item["truncated"] = cut
            spent += len(text)
        else:
            item["omitted"] = "text budget spent: call changes again with this anchor"
        if b:
            url = _url(corpus, ref, new, b, new_sizes)
            item["citation"] = f"[{b.label}]({url})"
        if a:
            item["before_citation"] = (
                f"[{a.label}, ред. до {version['date']}]({_url(corpus, ref, old, a, old_sizes)})"
            )
        items.append(item)
    if old_rest != new_rest and not anchor:
        diff = [
            ln
            for ln in difflib.unified_diff(old_rest, new_rest, n=1, lineterm="")
            if not ln.startswith(("---", "+++", "@@"))
        ]
        text, cut = _clip(diff, max(500, min(MAX_ITEM_TEXT, MAX_TOTAL_TEXT - spent)))
        items.append(
            {
                "label": "вне статей",
                "heading": None,
                "status": "modified",
                "diff": text,
                "truncated": cut,
                "note": "text outside any article (chapter headings, unnumbered provisions); "
                "read the act to cite it",
            }
        )

    return result | {
        "items": items[:MAX_ITEMS],
        "more": max(0, len(items) - MAX_ITEMS),
        "footnote_only": footnote_only,
        "note": NOTE,
    }
