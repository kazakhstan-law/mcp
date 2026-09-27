"""Find an article, a point, or the context of a line inside one rendered act file.

Pure functions over text. Articles carry explicit anchors (`<a id="st592"></a>` on its own
line, then the heading). An order has no articles, so from the 2026-09-27 corpus build its
outermost points carry one instead (`<a id="an0_p168-1"></a>` above `168-1. …`); a build
before that has none, and a point is then found by its label alone — a line starting with
`168-1. `, or italic when repealed (`*167. Исключен …*`). Annexes restart point numbering,
so a label can repeat in one file; the `an0_` qualifier is what separates them.
"""

from __future__ import annotations

import re
from dataclasses import dataclass

ANCHOR_LINE = re.compile(r'^<a id="([^"]+)"></a>$')
_N = r"[0-9]+(?:-[0-9]+)*"
ANCHOR_ID = re.compile(rf"^(?:an{_N}_)*(?:st{_N}(?:_p{_N})?(?:_sp{_N})?|p{_N})$")
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
