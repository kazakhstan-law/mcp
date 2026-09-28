"""history: an act's versions from git log, with the amending act from commit trailers."""

from __future__ import annotations

from kzlaw_mcp.corpus import ActRef, Corpus, InputError, title_of

FORMAT = (
    "%H%x1f%cs%x1f%s%x1f"
    "%(trailers:key=Cause-Act-Code,valueonly,separator=%x2C)%x1f"
    "%(trailers:key=Cause-Act-Requisite,valueonly,separator=%x20)%x1e"
)
MAX_LIMIT = 50
MAX_DEPTH = 3
NOTE = (
    "Each commit is one version of this act, dated to its version date; the subject and "
    "cause_act_* name the amending act. With phrase: only versions that added or removed that "
    "exact, case-sensitive text; the oldest is when it entered the law. predecessors are the "
    "repealed acts this one replaced (e.g. an earlier code), newest first, with their own "
    "versions: the history continues there, and at_date reads their text on dates before."
)


def _parse(out: str, corpus: Corpus, scope: str) -> list[dict]:
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
                "url": corpus.commit_url(scope, sha),
            }
        )
    return commits


def _versions(corpus: Corpus, ref: ActRef, phrase: str | None, limit: int) -> dict:
    g = corpus.git(ref.scope)
    head = corpus.head(ref.scope)
    args = ["-n", str(limit), f"--format={FORMAT}"]
    if phrase:
        args.append(f"-S{phrase}")
    commits = _parse(g.log(*args, head, "--", ref.path), corpus, ref.scope)
    created = _parse(
        g.log("--diff-filter=A", f"--format={FORMAT}", head, "--", f"{ref.path}/meta.yaml"),
        corpus,
        ref.scope,
    )
    return {
        "commits": commits,
        "first_version": created[-1] if created else None,
        "limited": len(commits) == limit,
    }


def history(corpus: Corpus, act_code: str, phrase: str | None = None, limit: int = 30) -> dict:
    ref = corpus.find_any(act_code)
    phrase = phrase.strip() if phrase else None
    if phrase is not None and not 3 <= len(phrase) <= 200:
        raise InputError("phrase must be 3..200 characters of the act's exact wording")
    limit = max(1, min(int(limit), MAX_LIMIT))
    own = _versions(corpus, ref, phrase, limit)
    replaced = corpus.replaced(ref.code)

    predecessors, chain, seen = [], [ref], {ref.code}
    while chain and len(predecessors) < MAX_DEPTH:
        for pred in corpus.predecessors(chain.pop(0)):
            if pred.ref.code in seen or len(predecessors) >= MAX_DEPTH:
                continue
            seen.add(pred.ref.code)
            chain.append(pred.ref)
            predecessors.append(
                {
                    "act_code": pred.ref.code,
                    "title": pred.title.get("rus", ""),
                    "requisite": pred.requisite,
                    "link": pred.link,
                    "replaced_by": pred.successor,
                    **_versions(corpus, pred.ref, phrase, limit),
                }
            )

    # The oldest match across the chain: a phrase carried over from a repealed code entered the
    # law when it entered that code, not when the successor was enacted with it.
    introduced = None
    if phrase:
        runs = [own, *predecessors]
        if not any(r["limited"] for r in runs):
            found = [c for r in runs for c in r["commits"]]
            introduced = min(found, key=lambda c: c["date"]) if found else None

    return {
        "act_code": ref.code,
        "scope": ref.scope,
        "title": replaced.title.get("rus", "")
        if replaced
        else title_of(corpus.meta(ref, corpus.head(ref.scope)), "rus"),
        "repealed_and_replaced_by": replaced.successor if replaced else None,
        "phrase": phrase,
        **own,
        "introduced": introduced,
        "predecessors": predecessors,
        "note": NOTE,
    }
