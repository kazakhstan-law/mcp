"""history: an act's versions from git log, with the amending act from commit trailers."""

from __future__ import annotations

import datetime as dt
import re

from kzlaw_mcp.corpus import ActRef, Corpus, InputError, title_of
from kzlaw_mcp.locate import ANCHOR_LINE, HEADING, PLACEHOLDER

FORMAT = (
    "%H%x1f%cs%x1f%s%x1f"
    "%(trailers:key=Cause-Act-Code,valueonly,separator=%x2C)%x1f"
    "%(trailers:key=Cause-Act-Requisite,valueonly,separator=%x20)%x1e"
)
MAX_LIMIT = 50
MAX_DEPTH = 3
MONTHS = {
    m: i + 1
    for i, m in enumerate(
        [
            "января",
            "февраля",
            "марта",
            "апреля",
            "мая",
            "июня",
            "июля",
            "августа",
            "сентября",
            "октября",
            "ноября",
            "декабря",
        ]
    )
}
PENDING = re.compile(r"[Вв]водится в действие|қолданысқа енгізіледі")
REQUISITE_DATE = re.compile(r"от (\d{1,2}) (\w+) (\d{4}) года")
NOTE = (
    "Each commit is one version of this act, dated to the day it took effect; the subject and "
    "cause_act_* name the amending act, cause_act_date is the day that act was adopted. One "
    "amending act often has several versions: parts take effect on different dates, and a "
    "version on the adoption date may only insert placeholders ('вводится в действие …') for "
    "text that comes later. changes(act_code, sha) shows what a version changed. With phrase: only versions that added or removed that "
    "exact, case-sensitive text; the oldest is when it entered the law. predecessors are the "
    "repealed acts this one replaced (e.g. an earlier code), newest first, with their own "
    "versions: the history continues there, and at_date reads their text on dates before. "
    "total counts all versions (from since, when given); limited: there are more, older ones: "
    "pass next_offset as offset for the next page, or since=YYYY-MM-DD to keep only versions "
    "from that date. introduced.announced: the phrase first came as a heading or placeholder "
    "whose text took effect later, on introduced.date; placeholder true: not in force yet."
)


def requisite_date(requisite: str) -> str | None:
    """The adoption date in a requisite: "Закон РК от 9 января 2026 года № 256-VIII" -> 2026-01-09."""
    m = REQUISITE_DATE.search(requisite)
    if not m or m.group(2) not in MONTHS:
        return None
    return f"{m.group(3)}-{MONTHS[m.group(2)]:02d}-{int(m.group(1)):02d}"


def parse_log(out: str, corpus: Corpus, scope: str) -> list[dict]:
    commits = []
    for record in out.split("\x1e"):
        record = record.strip("\n")
        if not record:
            continue
        sha, date, subject, code, requisite = record.split("\x1f")
        commits.append(
            {
                "date": date,
                "sha": sha,
                "subject": subject,
                "cause_act_code": code.strip(),
                "cause_act_requisite": requisite.strip(),
                "cause_act_date": requisite_date(requisite),
                "url": corpus.commit_url(scope, sha),
            }
        )
    return commits


def _versions(
    corpus: Corpus,
    ref: ActRef,
    phrase: str | None,
    limit: int,
    offset: int = 0,
    since: str | None = None,
) -> dict:
    g = corpus.git(ref.scope)
    head = corpus.head(ref.scope)
    # Corpus commits are dated UTC midnight, so the one on `since` itself is kept.
    window = [f"--since={since}T00:00:00Z"] if since else []
    args = ["-n", str(limit), "--skip", str(offset), f"--format={FORMAT}", *window]
    if phrase:
        args.append(f"-S{phrase}")
    commits = parse_log(g.log(*args, head, "--", ref.path), corpus, ref.scope)
    created = parse_log(
        g.log("--diff-filter=A", f"--format={FORMAT}", head, "--", f"{ref.path}/meta.yaml"),
        corpus,
        ref.scope,
    )
    limited = len(commits) == limit
    out: dict = {"commits": commits, "first_version": created[-1] if created else None}
    if not phrase:  # counting -S matches would run the whole pickaxe again
        out["total"] = total = g.count(*window, head, "--", ref.path)
        limited = offset + len(commits) < total
    return out | {"limited": limited, "next_offset": offset + limit if limited else None}


def _placeholder(corpus: Corpus, ref: ActRef, sha: str, phrase: str) -> str | None:
    """The line saying the provision takes effect later, when `phrase` at `sha` sits in one that
    has no text yet: a heading over nothing but "вводится в действие …", or that line itself."""
    g = corpus.git(ref.scope)
    hits = g.grep_lines(sha, [phrase], [ref.path])
    if not hits:
        return None
    file, lineno, line = hits[0]
    if PLACEHOLDER.match(line.strip()):
        return line
    if not HEADING.match(line):
        return None
    block = []
    for ln in g.blob(sha, file).split("\n")[lineno:]:
        if HEADING.match(ln) or ANCHOR_LINE.match(ln):
            break
        if ln.strip():
            block.append(ln)
    body = [ln for ln in block if not ln.lstrip().startswith(">")]
    if body and not all(PLACEHOLDER.match(ln.strip()) for ln in body):
        return None
    return next((ln for ln in block if PENDING.search(ln)), None)


def _took_effect(corpus: Corpus, ref: ActRef, sha: str, line: str) -> dict | None:
    """The first version after `sha` that removed the placeholder `line`: its text came then."""
    g = corpus.git(ref.scope)
    log = g.log(
        "--reverse",
        f"--format={FORMAT}",
        f"-S{line}",
        f"{sha}..{corpus.last_sha(ref)}",
        "--",
        ref.path,
    )
    found = parse_log(log, corpus, ref.scope)
    return found[0] if found else None


def history(
    corpus: Corpus,
    act_code: str,
    phrase: str | None = None,
    limit: int = 30,
    offset: int = 0,
    since: str | None = None,
) -> dict:
    ref = corpus.find_any(act_code)
    phrase = phrase.strip() if phrase else None
    if phrase is not None and not 3 <= len(phrase) <= 200:
        raise InputError("phrase must be 3..200 characters of the act's exact wording")
    if since is not None:
        try:
            if len(since) != 10:
                raise ValueError
            dt.date.fromisoformat(since)
        except (TypeError, ValueError):
            raise InputError("since must be YYYY-MM-DD") from None
    limit = max(1, min(int(limit), MAX_LIMIT))
    offset = max(0, int(offset))
    own = _versions(corpus, ref, phrase, limit, offset, since)
    replaced = corpus.replaced(ref.code)

    predecessors, refs, chain, seen = [], [], [ref], {ref.code}
    while chain and len(predecessors) < MAX_DEPTH:
        for pred in corpus.predecessors(chain.pop(0)):
            if pred.ref.code in seen or len(predecessors) >= MAX_DEPTH:
                continue
            seen.add(pred.ref.code)
            chain.append(pred.ref)
            refs.append(pred.ref)
            predecessors.append(
                {
                    "act_code": pred.ref.code,
                    "title": pred.title.get("rus", ""),
                    "requisite": pred.requisite,
                    "link": pred.link,
                    "replaced_by": pred.successor,
                    **_versions(corpus, pred.ref, phrase, limit, offset, since),
                }
            )

    # The oldest match across the chain: a phrase carried over from a repealed code entered the
    # law when it entered that code, not when the successor was enacted with it.
    introduced = None
    if phrase and since is None:
        runs = [(ref, own), *zip(refs, predecessors, strict=True)]
        if not any(r["limited"] for _, r in runs):
            found = [(a, c) for a, r in runs for c in r["commits"]]
            if found:
                act, introduced = min(found, key=lambda f: f[1]["date"])
                # A version may carry only the heading of a provision that takes effect later:
                # the phrase entered the law when the text did, not the placeholder.
                if line := _placeholder(corpus, act, introduced["sha"], phrase):
                    announced = introduced
                    effect = _took_effect(corpus, act, announced["sha"], line)
                    introduced = (effect or announced) | {
                        "placeholder": effect is None,
                        "announced": {k: announced[k] for k in ("date", "sha", "url")},
                    }

    return {
        "act_code": ref.code,
        "scope": ref.scope,
        "title": replaced.title.get("rus", "")
        if replaced
        else title_of(corpus.meta(ref, corpus.last_sha(ref)), "rus"),
        "repealed_and_replaced_by": replaced.successor if replaced else None,
        "repealed_on": repeal[1] if (repeal := corpus.repeal(ref)) else None,
        "phrase": phrase,
        **own,
        "introduced": introduced,
        "predecessors": predecessors,
        "note": NOTE,
    }
