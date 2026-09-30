# Analysis demo: Claude Code over the clones

The on-stage half that the MCP server cannot do: Claude Code writes and runs scripts over
full clones of all 25 scope repositories (history, trailers, deletions of repealed acts).
Run from the presenter's laptop, in a terminal, not through the Telegram bot.

Setup (≈ 11 GB with working trees):

```bash
mkdir -p ~/demo/kazakhstan-law/.claude && cd ~/demo/kazakhstan-law
for s in codes government ministerial $(gh api repos/kazakhstan-law/corpus/contents/.gitmodules --jq .content | base64 -d | grep -oP 'url = \.\./\Klocal-[\w-]+(?=\.git)'); do
  git clone -q https://github.com/kazakhstan-law/$s.git $s; done
cp <this dir>/CLAUDE.md . && cp <this dir>/settings.json .claude/
claude    # accept the trust dialog once, or the allow list in settings.json is ignored
```

`settings.json` excludes the presenter's own `~/CLAUDE.md` and `~/.claude/CLAUDE.md`
(absolute paths: edit them for another machine) so no personal instructions reach the demo.
`ask.sh` (clones) and `ask-mcp.sh` (the public endpoint, the bot's five tools) are the
headless rehearsal runners; they save each stream to `~/demo/runs/<id>.jsonl`.

Rehearsal results are in `docs/demo-questions.md`.
