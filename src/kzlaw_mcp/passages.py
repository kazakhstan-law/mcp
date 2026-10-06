"""read and at_date: a passage of an act at the current or a past revision.

Everything is read from git objects at one sha, so the text and its citation always
agree, and a split act's renamed parts are found by content (anchor or point label),
never by a remembered part name.
"""

from __future__ import annotations

import datetime as dt

from kzlaw_mcp.changes import pending
from kzlaw_mcp.corpus import ActRef, Corpus, InputError, check_lang, locator_label, title_of
from kzlaw_mcp.locate import (
    ANCHOR_ID,
    ANCHOR_LINE,
    POINT_LABEL,
    Span,
    article_span,
    footnote_acts,
    headings,
    point_spans,
)

MAX_TEXT = 12_000
MAX_PASSAGES = 3
OVERVIEW_CHARS = 4_000


def _clip(text: str, limit: int) -> tuple[str, bool]:
    return (text, False) if len(text) <= limit else (text[:limit] + "\n[…]", True)


def _overview(text: str) -> str:
    """The act's head: up to its first article, or whole paragraphs up to the limit."""
    lines = text.split("\n")
    first = next((i for i, ln in enumerate(lines) if ANCHOR_LINE.match(ln)), len(lines))
    head = "\n".join(lines[:first]).rstrip()
    if len(head) <= OVERVIEW_CHARS:
        return head
    cut = head.rfind("\n\n", 0, OVERVIEW_CHARS)
    return head[: cut if cut > 0 else OVERVIEW_CHARS] + "\n[…]"


def _check_locators(anchor: str | None, point: str | None) -> tuple[str | None, str | None]:
    anchor = anchor.strip() if anchor else None
    point = point.strip() if point else None
    if anchor and not ANCHOR_ID.match(anchor):
        raise InputError(
            "anchor looks like st592, an3_st1 or an0_p168-1 (take it from search hits)"
        )
    if point and not POINT_LABEL.match(point):
        raise InputError("point is a label like 168-1 or 3 (take it from search hits)")
    return anchor, point


def _passages(
    corpus: Corpus,
    ref: ActRef,
    sha: str,
    lang: str,
    anchor: str | None,
    point: str | None,
    when: str,
) -> dict:
    lang = check_lang(lang)
    anchor, point = _check_locators(anchor, point)
    g = corpus.git(ref.scope)
    files = corpus.lang_files(ref, sha, lang)
    if not files:
        raise InputError(f"act {ref.code} has no '{lang}' text {when}")
    meta = corpus.meta(ref, sha)
    result = {
        "act_code": ref.code,
        "scope": ref.scope,
        "title": title_of(meta, lang),
        "requisite": meta.get("requisite", ""),
        "sha": sha,
    }
    if not anchor and not point:
        main = g.blob(sha, files[0])
        return (
            result
            | {
                "overview": _overview(main),
                "outline": headings(main)[:80],
                "parts": files[1:101],
            }
            | pending(corpus, ref, sha, files)
            | {
                "hint": "Pass anchor or point (from search hits) to read a passage. pending: "
                "provisions enacted but not in force yet (only a placeholder, the text comes "
                "on `effective` or per the placeholder); history and changes show the rest."
            }
        )

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
    elif point:  # not both empty: that case returned the overview above
        hit_files = [p for p, _ in g.grep(sha, rf"^\*?{point}\. ", files, fixed=False)]
        for f in dict.fromkeys(hit_files):
            found += [(f, s) for s in point_spans(g.blob(sha, f), point)]
        if not found:
            raise InputError(f"point {point} not found in act {ref.code} {when}")

    label = locator_label(anchor, point) or result["title"][:80]
    passages = []
    for f, span in found[:MAX_PASSAGES]:
        url = corpus.citation_url(
            ref,
            sha,
            f,
            anchor=None if point else anchor,
            lines=(span.start, span.end),
            size=g.blob_size(sha, f),
        )
        text, cut = _clip(span.text, MAX_TEXT)
        passages.append(
            {
                "file": f,
                "lines": [span.start, span.end],
                "heading": span.heading,
                "text": text,
                "truncated": cut,
                "url": url,
                "citation": f"[{label}]({url})",
            }
        )
    return result | {"passages": passages, "more": len(found) - len(passages)}


def read(
    corpus: Corpus,
    act_code: str,
    lang: str = "rus",
    anchor: str | None = None,
    point: str | None = None,
) -> dict:
    ref = corpus.find(act_code)
    res = _passages(corpus, ref, corpus.head(ref.scope), lang, anchor, point, "in the current text")
    return res | {"as_of": "current"}


def at_date(
    corpus: Corpus,
    act_code: str,
    date: str,
    lang: str = "rus",
    anchor: str | None = None,
    point: str | None = None,
    earliest: bool = False,
) -> dict:
    try:
        if len(date) != 10:
            raise ValueError
        dt.date.fromisoformat(date)
    except (TypeError, ValueError):
        raise InputError("date must be YYYY-MM-DD") from None
    asked = corpus.find_any(act_code)
    g = corpus.git(asked.scope)
    sha = g.rev_before(date)
    if sha is None:
        raise InputError(f"the corpus has no history before {date}")
    ref, extra = asked, {}
    if not g.ls_tree(sha, f"{ref.path}/meta.yaml"):
        # Before an act replaced a repealed one (a new code for an old), the old one was the law.
        pred = next(
            (p for p in corpus.predecessors(ref) if g.ls_tree(sha, f"{p.ref.path}/meta.yaml")),
            None,
        )
        if pred is not None:
            ref = pred.ref
            extra = {
                "replaced_by": asked.code,
                "note": f"act {asked.code} was not yet in force on {date}; this is the text of "
                f"act {ref.code}, which it later replaced",
            }
        elif replaced := corpus.replaced(asked.code):
            raise InputError(
                f"act {asked.code} was not in force on {date}; it was repealed and replaced by "
                f"act {replaced.successor} (history on {asked.code} shows its dates)"
            )
        elif (repeal := corpus.repeal(ref)) and repeal[1] <= date:
            raise InputError(
                f"act {asked.code} was repealed on {repeal[1]}: pass a date before that "
                f"(history on {asked.code} shows its versions)"
            )
        else:
            first, since = _first_version(corpus, ref)
            adopted = str(corpus.meta(ref, first).get("approved_on") or "")
            if adopted and adopted > date:
                raise InputError(f"act {asked.code} was not adopted yet on {date}: {adopted}")
            if not earliest:
                raise InputError(
                    f"no data before {since}: act {asked.code} was adopted on "
                    f"{adopted or 'an unknown date'}, but the corpus has its text only from "
                    f"{since}. This is not a sign the act was not in force on {date}. Pass "
                    "earliest=true for the earliest text the corpus has, marked approximate"
                )
            res = _passages(corpus, ref, first, lang, anchor, point, f"on {since}")
            texts = [p["text"] for p in res.get("passages", [])] or [res.get("overview", "")]
            return res | {
                "as_of": since,
                "asked": date,
                "commit_date": since,
                "approximate": True,
                "amended_between": _amended_between(texts, date, since),
                "note": f"the corpus has no text of act {asked.code} before {since}: this is "
                f"the earliest it has, not the text on {date}. amended_between: the amending "
                "acts its footnotes name, dated after the asked date; the text on that date "
                "differed by them. Say both when you answer",
            }
    res = _passages(corpus, ref, sha, lang, anchor, point, f"on {date}")
    return res | extra | {"as_of": date, "commit_date": g.commit_date(sha)}


def _first_version(corpus: Corpus, ref: ActRef) -> tuple[str, str]:
    """(sha, date) of the first version the corpus has of the act."""
    g = corpus.git(ref.scope)
    out = g.log("--format=%H %cs", corpus.last_sha(ref), "--", f"{ref.path}/meta.yaml")
    sha, when = out.strip().split("\n")[-1].split()
    return sha, when


def _amended_between(texts: list[str], after: str, until: str) -> list[dict]:
    """Amending acts the footnotes in `texts` name, adopted after `after` and up to `until`."""
    found = footnote_acts([ln for t in texts for ln in t.split("\n")])
    return [{"date": d, "number": n} for d, n in sorted(found) if after < d <= until]
