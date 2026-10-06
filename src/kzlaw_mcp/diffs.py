"""Readable diffs for changes: text that moved between articles, renumbered points, and
word-level diffs of long paragraphs.

changes compares an act article by article. When a version inserts points, the text after the
last old point (a section heading and all under it) now follows the last new point instead:
compared by anchor, that reads as "п. 180 lost the section" and "п. 192 added it". Both halves
are the same lines, so they are matched and reported as one move. A point whose text is the
same under a new number is reported as renumbered. A paragraph of a table of road signs or a
long article is one line: a one-word change shows as two 4 KB lines, so it is diffed by words.
"""

from __future__ import annotations

import difflib
import re

# key, item, its text or diff lines, the field name ("text" or "diff"); as in changes.Entry
Entry = tuple[str, dict, list[str], str]

MIN_MOVE_LINES = 3
MIN_MOVE_CHARS = 300
LONG_LINE = 400
WORD_CONTEXT = 8
NUMBER = re.compile(r"^\s*\*?[0-9]+(?:-[0-9]+)*\.\s*")


def _added(entry: Entry) -> list[tuple[int, str]]:
    _, _, lines, field = entry
    if field == "text":
        return [(i, ln) for i, ln in enumerate(lines)] if entry[1]["status"] == "added" else []
    return [(i, ln[1:]) for i, ln in enumerate(lines) if ln.startswith("+")]


def _removed_runs(entry: Entry) -> list[list[tuple[int, str]]]:
    _, item, lines, field = entry
    if field == "text":
        return [list(enumerate(lines))] if item["status"] == "removed" else []
    runs, run = [], []
    for i, ln in enumerate(lines):
        if ln.startswith("-"):
            run.append((i, ln[1:]))
        elif run:
            runs.append(run)
            run = []
    return runs + ([run] if run else [])


MOVE_SHARE = 0.7  # of a removed run's lines found among another entry's added lines


def _region(needle: list[str], hay: list[tuple[int, str]]) -> list[tuple[int, str]] | None:
    """The span of `hay` holding most of `needle`'s lines: where the text moved to."""
    want = set(needle)
    pos = [p for p, (_, t) in enumerate(hay) if t in want]
    if len(pos) < MOVE_SHARE * len(needle):
        return None
    return hay[pos[0] : pos[-1] + 1]


def _changed(lines: list[str], field: str) -> bool:
    return field == "text" and bool(lines) or any(ln[:1] in "+-" for ln in lines)


def moves(entries: list[Entry]) -> tuple[list[Entry], list[dict]]:
    """Entries with text that moved between them taken out, and the moves found.

    A run of removed lines in one entry whose lines mostly reappear among another entry's
    added lines is one move. Edits made to the text as it moved become an entry of their own,
    status 'moved', diffed old place against new. An entry left with no change but the move
    drops out of the list; the move still names it.
    """
    strip: dict[int, set[int]] = {}
    found: list[dict] = []
    edits: dict[int, list[Entry]] = {}  # after entry n: the moved text's own diff
    for x, src in enumerate(entries):
        for run in _removed_runs(src):
            needle = [t for _, t in run]
            if not (len(needle) >= MIN_MOVE_LINES or sum(map(len, needle)) >= MIN_MOVE_CHARS):
                continue
            for y, dst in enumerate(entries):
                if y == x:
                    continue
                avail = [(i, t) for i, t in _added(dst) if i not in strip.get(y, set())]
                if (region := _region(needle, avail)) is None:
                    continue
                strip.setdefault(x, set()).update(i for i, _ in run)
                strip.setdefault(y, set()).update(i for i, _ in region)
                first = next((t.strip() for t in needle if t.strip()), "")
                move = {"from": src[1]["label"], "to": dst[1]["label"], "lines": len(needle)}
                diff = [
                    ln
                    for ln in difflib.unified_diff(needle, [t for _, t in region], n=1, lineterm="")
                    if not ln.startswith(("---", "+++", "@@"))
                ]
                if any(ln[:1] in "+-" for ln in diff):
                    move["edited"] = True
                    item = {
                        "label": f"{move['from']} → {move['to']}",
                        "heading": first[:120],
                        "status": "moved",
                        "note": "text moved from one article to another; the diff is what "
                        "the move also changed in it",
                    }
                    edits.setdefault(y, []).append(("", item, diff, "diff"))
                found.append(move | {"starts": first[:120]})
                break
    out: list[Entry] = []
    for n, (key, item, lines, field) in enumerate(entries):
        gone = strip.get(n)
        if gone:
            lines = [ln for i, ln in enumerate(lines) if i not in gone]
            item = item | {
                "moved_out": [m for m in found if m["from"] == item["label"]],
                "moved_in": [m for m in found if m["to"] == item["label"]],
            }
            item = {k: v for k, v in item.items() if v != []}
        if not gone or _changed(lines, field):
            out.append((key, item, lines, field))
        out += edits.get(n, [])
    return out, found


def _norm(lines: list[str]) -> str:
    text = "\n".join(ln.strip() for ln in lines if ln.strip())
    return NUMBER.sub("", text, count=1)


def renumbered(entries: list[Entry]) -> list[Entry]:
    """A removed point and an added one with the same text: one renumbered item."""
    removed = {
        _norm(lines): n
        for n, (_, item, lines, _) in enumerate(entries)
        if item["status"] == "removed" and _norm(lines)
    }
    merged: dict[int, int] = {}  # added entry -> removed entry
    for n, (_, item, lines, _) in enumerate(entries):
        r = removed.get(_norm(lines)) if item["status"] == "added" else None
        if r is not None and r not in merged.values():
            merged[n] = r
    out = []
    for n, (key, item, lines, field) in enumerate(entries):
        if n in merged.values():
            continue
        if n in merged:
            old = entries[merged[n]][1]
            item = item | {"status": "renumbered", "from": old["label"]}
            if "before_citation" in old:
                item["before_citation"] = old["before_citation"]
            lines = []
        out.append((key, item, lines, field))
    return out


def _word_diff(old: str, new: str) -> str:
    """One line: the changed words in brackets, WORD_CONTEXT words around each change."""
    a, b = old.split(), new.split()
    parts: list[str] = []
    ops = difflib.SequenceMatcher(None, a, b, autojunk=False).get_opcodes()
    for n, (tag, i1, i2, j1, j2) in enumerate(ops):
        if tag == "equal":
            words = a[i1:i2]
            head = words[:WORD_CONTEXT] if n else []
            tail = words[-WORD_CONTEXT:] if n < len(ops) - 1 else []
            if len(words) > len(head) + len(tail):
                parts += [*head, "…", *tail]
            else:
                parts += words
            continue
        if i2 > i1:
            parts.append("[-" + " ".join(a[i1:i2]) + "-]")
        if j2 > j1:
            parts.append("{+" + " ".join(b[j1:j2]) + "+}")
    return "~" + " ".join(parts)


def _alike(old: str, new: str) -> bool:
    if max(len(old), len(new)) <= LONG_LINE:
        return False
    return difflib.SequenceMatcher(None, old.split(), new.split(), autojunk=False).ratio() > 0.5


def word_diffs(lines: list[str]) -> list[str]:
    """In a hunk's '-' lines and the '+' lines after them, the n-th of each, long and alike,
    become one '~' word-diff line; the rest stay as they are."""
    out: list[str] = []
    i = 0
    while i < len(lines):
        if not lines[i].startswith("-"):
            out.append(lines[i])
            i += 1
            continue
        j = i
        while j < len(lines) and lines[j].startswith("-"):
            j += 1
        k = j
        while k < len(lines) and lines[k].startswith("+"):
            k += 1
        minus, plus = lines[i:j], lines[j:k]
        pairs = [n for n in range(min(len(minus), len(plus))) if _alike(minus[n][1:], plus[n][1:])]
        out += [ln for n, ln in enumerate(minus) if n not in pairs]
        out += [_word_diff(minus[n][1:], plus[n][1:]) for n in pairs]
        out += [ln for n, ln in enumerate(plus) if n not in pairs]
        i = k
    return out
