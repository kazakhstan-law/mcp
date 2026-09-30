"""search: ripgrep over the working trees of the current revision."""

from __future__ import annotations

import json
from pathlib import Path

import yaml

from kzlaw_mcp.config import ALL_SCOPES, DEFAULT_SCOPES
from kzlaw_mcp.corpus import ActRef, Corpus, InputError, check_lang, title_of
from kzlaw_mcp.gitio import CommandError, run
from kzlaw_mcp.locate import line_context

MAX_QUERY = 200
MAX_HITS = 20
PER_FILE = 3
PER_ACT = 5  # a code split into 100 parts must not take every hit
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


def search(
    corpus: Corpus,
    query: str,
    lang: str = "rus",
    scopes: list[str] | None = None,
    limit: int = MAX_HITS,
    act_code: str | None = None,
) -> dict:
    query = (query or "").strip()
    if not 2 <= len(query) <= MAX_QUERY:
        raise InputError(f"query must be 2..{MAX_QUERY} characters")
    lang = check_lang(lang)
    act = corpus.find(act_code) if act_code else None
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
        query,
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
        for rel, lineno, text in sorted(hits)[: min(per_act, limit - used)]:
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
    }
