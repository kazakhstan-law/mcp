"""search: ripgrep over the working trees of the current revision."""

from __future__ import annotations

import json
import re
from pathlib import Path

import yaml

from kzlaw_mcp.config import ALL_SCOPES, DEFAULT_SCOPES
from kzlaw_mcp.corpus import ActRef, Corpus, InputError, check_lang, title_of
from kzlaw_mcp.gitio import CommandError, run
from kzlaw_mcp.locate import line_context
from kzlaw_mcp.synonyms import any_order, legal_wordings, relaxed, stems

MAX_QUERY = 200
MAX_HITS = 20
PER_FILE = 3
PER_ACT = 5  # a code split into 100 parts must not take every hit
MAX_LINE = 300
NO_HITS = (
    "No matches. Each line searched is one paragraph: 'A.*B' finds A and B only in the same "
    "paragraph, so search separate concepts separately or join them with '|'. Do not quote "
    "wording from memory: editions differ ('предупредив' in one, 'уведомив' in the next), so "
    "search one or two distinctive words. A stem matches inside a word but not across its "
    "ending: 'банкротств\\w* граждан', not 'банкротств граждан'."
)
HINT = "Open a passage with read(act_code, anchor=...) or read(act_code, point=...)."
REWRITTEN_HINT = (
    "The query as sent found nothing: the law does not use those words. These hits are for "
    "the legal wording in rewritten.to; name it when you answer. rewritten.also: other legal "
    "wordings for the same words, to search when these hits are not it. " + HINT
)
RELAXED_HINT = (
    "The query as sent found nothing. These hits have every stem in relaxed.stems in one "
    "paragraph, in any order: check that they answer the question before citing. Next time "
    "search two or three stems, not a phrase or a long regex. " + HINT
)
NEAREST_NOTE = (
    "nearest_headings: article headings in this act sharing a word stem with the query; open "
    "one with read(act_code, anchor=...), or read(act_code) for the whole outline."
)
MAX_NEAREST = 10
MAX_REPEALED = 20
REPEALED_HINT = (
    "This act is repealed: the hits are from its last version, as_of. Open a passage with "
    "at_date(act_code, date=as_of, anchor=...)."
)
REPEALED_NOTE = (
    "repealed: acts no longer in force whose title matches the query, with the day each was "
    "repealed. Search inside one with search(act_code=...), read it with at_date on a date "
    "before repealed_on, see its versions with history."
)


def _search_repealed_act(
    corpus: Corpus, ref: ActRef, query: str, lang: str, limit: int, repeal: tuple[str, str]
) -> dict:
    """search inside an act that is no longer in force: its last version, from git objects."""
    g = corpus.git(ref.scope)
    sha = g.rev_parse(f"{repeal[0]}^")
    assert sha is not None
    files = corpus.lang_files(ref, sha, lang)
    if not files:
        raise InputError(f"act {ref.code} has no '{lang}' text")
    try:
        found = g.search(sha, query, files, limit + 1)
    except CommandError as exc:
        raise InputError(f"search failed (is the regex valid?): {exc}") from exc
    meta = corpus.meta(ref, sha)
    texts: dict[str, list[str]] = {}
    hits = []
    for rel, lineno, text in sorted(found, key=_heading_first)[:limit]:
        if rel not in texts:
            texts[rel] = g.blob(sha, rel).split("\n")
        ctx = line_context(texts[rel], lineno)
        hits.append(
            {
                "file": rel,
                "line": lineno,
                "anchor": ctx.anchor,
                "point": ctx.point,
                "heading": ctx.heading,
                "text": text.strip()[:MAX_LINE],
                "url": corpus.citation_url(
                    ref,
                    sha,
                    rel,
                    anchor=ctx.anchor,
                    lines=(lineno, lineno),
                    size=g.blob_size(sha, rel),
                ),
            }
        )
    acts = (
        [
            {
                "act_code": ref.code,
                "scope": ref.scope,
                "title": title_of(meta, lang),
                "requisite": meta.get("requisite", ""),
                "repealed_on": repeal[1],
                # the act's own last version: its parent commit can share the repeal's date
                "as_of": g.log("-1", "--format=%cs", sha, "--", ref.path).strip(),
                "hits": hits,
            }
        ]
        if hits
        else []
    )
    return {
        "query": query,
        "lang": lang,
        "scopes": [ref.scope],
        "act_code": ref.code,
        "missing_scopes": [],
        "sha": {ref.scope: sha},
        "truncated": len(found) > limit,
        "acts": acts,
        "hint": REPEALED_HINT if acts else NO_HITS,
    }


def _repealed_titles(corpus: Corpus, query: str, lang: str, scopes: list[str]) -> dict:
    try:
        pattern = re.compile(query, re.IGNORECASE)
    except re.error:
        return {"repealed": [], "repealed_note": "the query is not a valid regex for titles"}
    found = []
    for scope in scopes:
        acts = corpus.repealed_in(scope)
        for code, info in corpus.repealed_titles(scope).items():
            title = info["title"].get(lang) or info["title"].get("rus") or ""
            if pattern.search(title):
                found.append(
                    {
                        "act_code": code,
                        "scope": scope,
                        "title": title,
                        "requisite": info["requisite"],
                        "repealed_on": acts[code].date,
                    }
                )
    found.sort(key=lambda a: a["repealed_on"], reverse=True)
    return {
        "repealed": found[:MAX_REPEALED],
        "repealed_more": max(0, len(found) - MAX_REPEALED),
        "repealed_note": REPEALED_NOTE,
    }


def _heading_first(hit: tuple[str, int, str]) -> tuple[bool, str, int]:
    """Inside one act an article whose heading matches outranks every line that mentions it."""
    rel, lineno, text = hit
    return (not text.lstrip().startswith("#"), rel, lineno)


def _headings_only(query: str) -> str:
    return rf"^#{{1,6}}\s.*(?:{query})"


def _act_dir(rel: str, lang: str) -> str:
    parent, name = rel.rsplit("/", 1)
    if name == f"{lang}.md":
        return parent
    return parent.rsplit("/", 1)[0]  # <act>/<lang>/<part>.md


def search(
    corpus: Corpus,
    query: str,
    lang: str = "rus",
    scopes: list[str] | None = None,
    limit: int = MAX_HITS,
    act_code: str | None = None,
    include_repealed: bool = False,
    headings_only: bool = False,
) -> dict:
    # The corpus writes "учет", not "учёт": ripgrep's case folding does not join the two.
    query = (query or "").strip().replace("ё", "е").replace("Ё", "Е")
    if not 2 <= len(query) <= MAX_QUERY:
        raise InputError(f"query must be 2..{MAX_QUERY} characters")
    lang = check_lang(lang)

    def run(q: str, only_headings: bool = headings_only, n: int = limit) -> dict:
        return _search(corpus, q, lang, scopes, n, act_code, include_repealed, only_headings)

    res = run(query)
    if res["acts"] or res.get("repealed"):
        return res
    extra: dict = {}
    legal = legal_wordings(query) if lang == "rus" else []
    for n, wording in enumerate(legal):
        again = run(wording)
        if again["acts"]:
            rewritten = {"from": query, "to": wording, "also": legal[n + 1 :]}
            return again | {"rewritten": rewritten, "hint": REWRITTEN_HINT}
    if legal:
        extra["tried"] = legal
    # A phrase or a long regex that found nothing: its words, in any order, in one paragraph.
    for found in relaxed(query):
        again = run(any_order(found))
        if again["acts"]:
            loose = {"from": query, "stems": found}
            return again | extra | {"query": query, "relaxed": loose, "hint": RELAXED_HINT}
    if act_code and (found := stems(query)):
        near = run("|".join(found), True, MAX_HITS)
        hits = [h for a in near["acts"] for h in a["hits"]]
        hits.sort(key=lambda h: -sum(s in h["text"].lower() for s in found))
        if hits:
            extra["nearest_headings"] = [
                {"anchor": h["anchor"], "point": h["point"], "heading": h["text"]}
                for h in hits[:MAX_NEAREST]
            ]
            extra["hint"] = f"{res['hint']} {NEAREST_NOTE}"
    return res | extra


def _search(
    corpus: Corpus,
    query: str,
    lang: str,
    scopes: list[str] | None,
    limit: int,
    act_code: str | None,
    include_repealed: bool,
    headings_only: bool,
) -> dict:
    pattern = _headings_only(query) if headings_only else query
    act = None
    if act_code:
        try:
            act = corpus.find(act_code)
        except InputError:
            gone = corpus.find_any(act_code)  # raises for a code that never was an act
            repeal = corpus.repeal(gone)
            assert repeal is not None
            limit = max(1, min(int(limit), MAX_HITS))
            res = _search_repealed_act(corpus, gone, pattern, lang, limit, repeal)
            return res | {"query": query}
    if act:
        scopes = [act.scope]
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
    # Inside one act every hit is its own: the per-file and per-act caps only spread hits
    # across acts. One hit over the limit tells truncation apart from an exact fit.
    per_file, per_act = (limit + 1, limit) if act else (PER_FILE, PER_ACT)
    root: Path = corpus.settings.corpus_root
    args = [
        "rg",
        "--json",
        "--ignore-case",
        "--max-count",
        str(per_file),
        "--max-columns",
        "2000",
        "--glob",
        f"**/{lang}.md",
        "--glob",
        f"**/{lang}/*.md",
        "-e",
        pattern,
        "--",
        *([f"{act.scope}/{act.path}"] if act else wanted),
    ]
    try:
        out = run(
            args, root, timeout=corpus.settings.subprocess_timeout_s, max_bytes=4_000_000, ok=(0, 1)
        )
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

    heads = {s: corpus.head(s) for s in wanted}
    order = {s: i for i, s in enumerate(wanted)}

    def title_hit(act_dir: str, hits: list[tuple[str, int, str]]) -> bool:
        return any(rel == f"{act_dir}/{lang}.md" and line == 1 for rel, line, _ in hits)

    # Acts whose title matches come first, in any scope. The rest take turns by scope, so a
    # scope with many weak matches cannot push another scope's acts out of the limit; inside a
    # scope, more matching lines rank higher.
    by_rank = sorted(by_act.items(), key=lambda kv: (order[kv[0][0]], -len(kv[1]), kv[0][1]))
    ranked = [kv for kv in by_rank if title_hit(kv[0][1], kv[1])]
    queues = {s: [kv for kv in by_rank if kv[0][0] == s and kv not in ranked] for s in wanted}
    while any(queues.values()):
        for s in wanted:
            if queues[s]:
                ranked.append(queues[s].pop(0))
    acts, used, file_lines = [], 0, {}
    for (scope, act_dir), hits in ranked:
        if used >= limit:
            break
        meta = yaml.safe_load((root / scope / act_dir / "meta.yaml").read_text("utf-8")) or {}
        items = []
        picked = sorted(hits, key=_heading_first) if act else sorted(hits)
        for rel, lineno, text in picked[: min(per_act, limit - used)]:
            if rel not in file_lines:
                file_lines[rel] = (root / scope / rel).read_text("utf-8").split("\n")
            ctx = line_context(file_lines[rel], lineno)
            url = corpus.citation_url(
                ActRef(str(meta.get("act_code", "")), scope, act_dir),
                heads[scope],
                rel,
                anchor=ctx.anchor,
                lines=(lineno, lineno),
                size=(root / scope / rel).stat().st_size,
            )
            items.append(
                {
                    "file": rel,
                    "line": lineno,
                    "anchor": ctx.anchor,
                    "point": ctx.point,
                    "heading": ctx.heading,
                    "text": text[:MAX_LINE],
                    "url": url,
                }
            )
        used += len(items)
        acts.append(
            {
                "act_code": str(meta.get("act_code", "")),
                "scope": scope,
                "title": title_of(meta, lang),
                "requisite": meta.get("requisite", ""),
                "hits": items,
            }
        )
    return {
        "query": query,
        "lang": lang,
        "scopes": wanted,
        **({"act_code": act.code} if act else {}),
        "missing_scopes": missing,
        "sha": heads,
        "truncated": out.truncated
        or len(acts) < len(ranked)
        or sum(len(h) for _, h in ranked) > used,
        "acts": acts,
        "hint": HINT if acts else NO_HITS,
    } | (_repealed_titles(corpus, query, lang, wanted) if include_repealed and not act else {})
