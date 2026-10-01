# kazakhstan-law-mcp — project memory

## Type checking
- ty (`uvx ty check`) reads `./.venv`: run `uv sync` first or every import is unresolved. The
  worktree delegate (`.orca/worktree-setup.sh`) does this for new workspaces.
- ruff enforces ANN on `src` only; `tests/**` is exempt. `src` was ANN-clean on 2026-09-30.
- `src` is ty-clean as of 2026-09-30; keep it that way.

## Search misses (replay of 266 prod searches, 2026-09-30)
- 37 found nothing; almost none were everyday words. The misses are models over-specifying: long
  exact phrases, `.{0,20}` chains, `^#### Статья \d+\.` headings. So synonyms.py is a minor
  lever; the bigger one is steering models to short stems. Done 1ff82d1: SEARCH_DESC asks for
  2-3 stems, and a miss is retried as up to 4 stems in any order (`relaxed`): replay 37 -> 14
  misses. Precision varies (ПД, брак: right article first; ИПН вычеты, 50% штрафа: off-topic),
  so the hint makes the model check the hits.
- kzlaw-report's reformulation pairs are noisy: the "next hit" is often a new topic.

## Feedback tool (2026-10-01)
- `feedback` writes `feedback.jsonl` beside the call log (prod: data/logs/); kzlaw-report prints
  it first. No per-IP cap on messages beyond the shared rate limit. Don't test it on prod: a
  test row lands in the report.
