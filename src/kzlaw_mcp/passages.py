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
        overview, _ = _clip(main, OVERVIEW_CHARS)
        return result | {
            "overview": overview,
            "outline": headings(main)[:80],
            "parts": files[1:101],
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
) -> dict:
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
    if not g.ls_tree(sha, f"{ref.path}/meta.yaml"):
        raise InputError(f"act {ref.code} was not in force on {date} (it enters the corpus later)")
    res = _passages(corpus, ref, sha, lang, anchor, point, f"on {date}")
    return res | {"as_of": date, "commit_date": g.commit_date(sha)}
