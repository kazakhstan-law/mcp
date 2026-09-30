"""kzlaw-report: how the server is used, read from the JSONL call log.

The part that feeds the everyday-word dictionary (synonyms.py) is the zero-hit searches and
the reformulations: a search that found nothing, followed in the same conversation by one that
did, is a candidate pair "the words people use" -> "the words the law uses". Entries are added
by hand from this report: a wrong one silently changes answers.

The output holds users' queries: read it in the terminal, do not publish it.
"""

from __future__ import annotations

import argparse
import json
import os
import re
import sys
from collections import Counter, defaultdict
from collections.abc import Iterable
from datetime import UTC, datetime, timedelta
from itertools import pairwise
from pathlib import Path

GAP = timedelta(minutes=10)  # calls from one IP closer than this are one conversation
LOOKAHEAD = 3  # a reformulation is a hit within this many searches after a miss
CLIENTS = [  # product token -> client; the log keeps the token so these can change later
    (re.compile(r"claude|anthropic", re.IGNORECASE), "claude"),
    (re.compile(r"openai|chatgpt|gpt", re.IGNORECASE), "chatgpt"),
    (re.compile(r"cursor", re.IGNORECASE), "cursor"),
    (re.compile(r"^local$"), "local"),
]
_REGEX_NOISE = re.compile(
    r"\.?\{\d*,?\d*\}|\[[^\]]*\][*+?]?|\\[wWsSdDbB][*+?]?|[.][*+?]|[()\[\]^$|?*+{}]|\\"
)


def load(path: Path) -> list[dict]:
    rows = []
    with path.open(encoding="utf-8") as fh:
        for line in fh:
            try:
                row = json.loads(line)
                row["_ts"] = datetime.fromisoformat(row["ts"])
            except (ValueError, KeyError, TypeError):
                continue  # a line cut by a crash mid-write
            rows.append(row)
    return rows


def client_of(token: str | None) -> str:
    if token is None:
        return "?"  # logged before the client field existed
    for pattern, name in CLIENTS:
        if pattern.search(token):
            return name
    return f"other:{token}"


def query_key(query: str) -> str:
    """One key for spellings of the same question: "Курени\\w*" and "курение" differ only in
    the regex the model wrapped around the word."""
    words = _REGEX_NOISE.sub(" ", query.lower().replace("ё", "е")).split()
    return " ".join(words)


def is_search(row: dict) -> bool:
    return row.get("tool") == "search" and row.get("ok") is True


def missed(row: dict) -> bool | None:
    """True when a search found nothing at all; None when the row predates the hits field."""
    if "hits" not in row:
        return None
    return not row["hits"] and not row.get("repealed")


def chains(rows: Iterable[dict]) -> list[list[dict]]:
    """Conversations: one IP's calls, split where the gap between two exceeds GAP."""
    by_ip: dict[str, list[dict]] = defaultdict(list)
    for row in rows:
        by_ip[row.get("ip", "?")].append(row)
    out = []
    for calls in by_ip.values():
        calls.sort(key=lambda r: r["_ts"])
        chain = [calls[0]]
        for prev, row in pairwise(calls):
            if row["_ts"] - prev["_ts"] > GAP:
                out.append(chain)
                chain = []
            chain.append(row)
        out.append(chain)
    out.sort(key=lambda c: c[0]["_ts"])
    return out


def reformulations(conversations: list[list[dict]]) -> Counter:
    """(missed query, query that then found something) pairs, across conversations."""
    pairs: Counter = Counter()
    for chain in conversations:
        searches = [r for r in chain if is_search(r)]
        for i, row in enumerate(searches):
            if missed(row) is not True:
                continue
            for later in searches[i + 1 : i + 1 + LOOKAHEAD]:
                if missed(later) is False:
                    pairs[(_query(row), _query(later) + _rewrite(later))] += 1
                    break
    return pairs


def _query(row: dict) -> str:
    return str((row.get("args") or {}).get("query", ""))


def _rewrite(row: dict) -> str:
    return f"  [rewritten -> {row['rewritten']}]" if row.get("rewritten") else ""


def _where(row: dict) -> str:
    args = row.get("args") or {}
    bits = [f"act {args['act_code']}"] if args.get("act_code") else ["corpus"]
    if args.get("headings_only"):
        bits.append("headings")
    return ", ".join(bits)


def report(rows: list[dict], top: int = 20, show_chains: int = 15) -> str:
    out: list[str] = []

    def section(title: str) -> None:
        out.extend(["", f"## {title}"])

    if not rows:
        return "no calls in the period"
    first, last = rows[0]["_ts"], rows[-1]["_ts"]
    out.append(
        f"{len(rows)} calls, {len({r.get('ip') for r in rows})} IPs, "
        f"{first:%Y-%m-%d %H:%M} .. {last:%Y-%m-%d %H:%M} UTC"
    )

    section("Per day (UTC)")
    days: dict[str, list[dict]] = defaultdict(list)
    for r in rows:
        days[r["ts"][:10]].append(r)
    for day, rs in sorted(days.items()):
        out.append(f"{day}  {len(rs):5} calls  {len({r.get('ip') for r in rs}):3} IPs")

    section("Tools")
    out.append(_counts(Counter(r.get("tool", "?") for r in rows)))
    section("Clients")
    out.append(_counts(Counter(client_of(r.get("client")) for r in rows)))

    searches = [r for r in rows if is_search(r)]
    known = [r for r in searches if missed(r) is not None]
    misses = [r for r in known if missed(r)]
    section("Searches")
    out.append(
        f"{len(searches)} searches; {len(known)} logged with a result, {len(misses)} found "
        f"nothing, {sum(1 for r in known if r.get('rewritten'))} found only after a rewrite, "
        f"{sum(1 for r in known if r.get('relaxed'))} only after relaxing a phrase to stems"
    )

    section("Found nothing, no dictionary entry (candidates for synonyms.py)")
    out.extend(_grouped([r for r in misses if not r.get("tried")], top))
    section("Found nothing, dictionary tried and failed (entry wrong or incomplete)")
    out.extend(_grouped([r for r in misses if r.get("tried")], top, tried=True))

    section("Rewritten by the dictionary")
    rewrites = Counter((query_key(_query(r)), r["rewritten"]) for r in known if r.get("rewritten"))
    out.extend(f"{n:4}  {q}  ->  {to}" for (q, to), n in rewrites.most_common(top))

    section("Relaxed: a phrase that found nothing, retried as stems in any order")
    loose = Counter((_query(r), r["relaxed"]) for r in known if r.get("relaxed"))
    out.extend(f"{n:4}  {q}  ->  {st}" for (q, st), n in loose.most_common(top))

    conversations = chains(rows)
    section(f"Reformulations: a miss, then a hit within {LOOKAHEAD} searches")
    pairs = reformulations(conversations)
    out.extend(f"{n:4}  {a}  =>  {b}" for (a, b), n in pairs.most_common(top))

    section("Errors")
    errors = Counter(
        (r.get("tool", "?"), str(r.get("error", ""))[:120]) for r in rows if not r.get("ok")
    )
    out.extend(f"{n:4}  {tool}: {err}" for (tool, err), n in errors.most_common(top))

    section("Slowest")
    for r in sorted(rows, key=lambda r: -r.get("ms", 0))[:10]:
        args = json.dumps(r.get("args") or {}, ensure_ascii=False)[:120]
        out.append(f"{r.get('ms', 0):6} ms  {r.get('tool')}  {args}")

    section(f"Conversations (calls from one IP, gaps under {GAP.seconds // 60} min)")
    lengths = Counter(min(len(c), 20) for c in conversations)
    out.append(
        f"{len(conversations)} conversations; calls per conversation: "
        + ", ".join(f"{k}{'+' if k == 20 else ''}: {v}" for k, v in sorted(lengths.items()))
    )
    for chain in conversations[-show_chains:]:
        out.append(f"{chain[0]['ts'][:16]}  " + " > ".join(_step(r) for r in chain))
    return "\n".join(out).strip() + "\n"


def _counts(counter: Counter) -> str:
    return "  ".join(f"{k} {v}" for k, v in counter.most_common())


def _grouped(rows: list[dict], top: int, tried: bool = False) -> list[str]:
    groups: dict[str, list[dict]] = defaultdict(list)
    for r in rows:
        groups[query_key(_query(r))].append(r)
    ranked = sorted(groups.items(), key=lambda kv: -len(kv[1]))[:top]
    lines = []
    for key, rs in ranked:
        where = Counter(_where(r) for r in rs).most_common(2)
        line = f"{len(rs):4}  {key or _query(rs[0])}   ({'; '.join(w for w, _ in where)})"
        if tried:
            line += f"   tried: {', '.join(rs[0]['tried'])}"
        lines.append(line)
    return lines


def _step(row: dict) -> str:
    tool = row.get("tool", "?")
    if not row.get("ok"):
        return f"{tool}!"
    if tool == "search":
        mark = {True: "∅", False: "", None: ""}[missed(row)]
        return f"search{mark}"
    return tool


def main(argv: list[str] | None = None) -> None:
    parser = argparse.ArgumentParser(prog="kzlaw-report", description=__doc__.splitlines()[0])
    parser.add_argument("log", nargs="?", default=os.environ.get("KZLAW_LOG_PATH"))
    parser.add_argument("--since", help="first day, YYYY-MM-DD (UTC)")
    parser.add_argument("--until", help="last day, YYYY-MM-DD (UTC)")
    parser.add_argument("--days", type=int, help="the last N days")
    parser.add_argument("--top", type=int, default=20)
    parser.add_argument("--chains", type=int, default=15, help="recent conversations to show")
    ns = parser.parse_args(argv)
    if not ns.log:
        parser.error("give the log path or set KZLAW_LOG_PATH")
    rows = load(Path(ns.log))
    since = ns.since
    if ns.days:
        since = (datetime.now(UTC).date() - timedelta(days=ns.days - 1)).isoformat()
    rows = [
        r
        for r in rows
        if (not since or r["ts"][:10] >= since) and (not ns.until or r["ts"][:10] <= ns.until)
    ]
    rows.sort(key=lambda r: r["_ts"])
    sys.stdout.write(report(rows, ns.top, ns.chains))


if __name__ == "__main__":
    main()
