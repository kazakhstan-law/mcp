"""history: an act's versions from git log, with the amending act from commit trailers."""

from __future__ import annotations

from kzlaw_mcp.corpus import Corpus, InputError, title_of

FORMAT = (
    "%H%x1f%cs%x1f%s%x1f"
    "%(trailers:key=Cause-Act-Code,valueonly,separator=%x2C)%x1f"
    "%(trailers:key=Cause-Act-Requisite,valueonly,separator=%x20)%x1e"
)
MAX_LIMIT = 50
NOTE = (
    "Each commit is one version of this act, dated to its version date; the subject and "
    "cause_act_* name the amending act. With phrase: only versions that added or removed that "
    "exact, case-sensitive text; the oldest is when it entered this act. History covers this act "
    "only: a predecessor act that was repealed and replaced is not followed."
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


def history(corpus: Corpus, act_code: str, phrase: str | None = None, limit: int = 30) -> dict:
    ref = corpus.find(act_code)
    phrase = phrase.strip() if phrase else None
    if phrase is not None and not 3 <= len(phrase) <= 200:
        raise InputError("phrase must be 3..200 characters of the act's exact wording")
    limit = max(1, min(int(limit), MAX_LIMIT))
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
    limited = len(commits) == limit
    meta = corpus.meta(ref, head)
    return {
        "act_code": ref.code,
        "scope": ref.scope,
        "title": title_of(meta, "rus"),
        "phrase": phrase,
        "commits": commits,
        "first_version": created[-1] if created else None,
        "limited": limited,
        "introduced": commits[-1] if phrase and commits and not limited else None,
        "note": NOTE,
    }
