#!/usr/bin/env bash
# ask-mcp.sh <id> <question> — the bot's path: only the four MCP tools of the public endpoint.
set -euo pipefail
id=$1; q=$2; out=~/demo/runs/$id.jsonl
cd ~/demo/mcp-run
cfg='{"mcpServers":{"kazakhstan-law":{"type":"http","url":"https://cyphy.kz/kazakhstan-law/mcp"}}}'
start=$(date +%s)
claude -p "$q" --model claude-opus-5-5 --setting-sources project --mcp-config "$cfg" --strict-mcp-config --tools "" \
  --allowedTools mcp__kazakhstan-law__search mcp__kazakhstan-law__read mcp__kazakhstan-law__at_date mcp__kazakhstan-law__history \
  --output-format stream-json --verbose < /dev/null > "$out"
end=$(date +%s)
python3 - "$out" $((end-start)) <<'PY'
import json, sys
calls, answer = [], ""
for line in open(sys.argv[1]):
    e = json.loads(line)
    m = e.get("message")
    c = m.get("content") if isinstance(m, dict) else None
    for b in c if isinstance(c, list) else []:
        if b.get("type") == "tool_use":
            calls.append(b["name"].rsplit("__", 1)[-1])
    if e.get("type") == "result":
        answer = e.get("result", "")
print(f"time {sys.argv[2]}s, tool calls {len(calls)}: {calls}")
print(answer)
PY
