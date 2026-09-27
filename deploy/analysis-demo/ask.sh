#!/usr/bin/env bash
# ask.sh <id> <question> — one headless run in the demo workspace; saves the stream and prints time, tools, answer.
set -euo pipefail
id=$1; q=$2; out=~/demo/runs/$id.jsonl
cd ~/demo/kazakhstan-law
start=$(date +%s)
claude -p "$q" --setting-sources project --allowedTools Bash Read Grep Glob Write Edit --disallowedTools WebFetch WebSearch "Bash(git push:*)" "Bash(git checkout:*)" "Bash(git reset:*)" "Bash(git fetch:*)" "Bash(rm:*)" --output-format stream-json --verbose < /dev/null > "$out"
end=$(date +%s)
python3 - "$out" $((end-start)) <<'PY'
import json, sys
calls, answer = [], ""
for line in open(sys.argv[1]):
    e = json.loads(line)
    c = (e.get("message") or {}).get("content") if isinstance(e.get("message"), dict) else None
    for b in c if isinstance(c, list) else []:
        if isinstance(b, dict) and b.get("type") == "tool_use":
            calls.append(b["name"])
    if e.get("type") == "result":
        answer = e.get("result", "")
print(f"time {sys.argv[2]}s, tool calls {len(calls)}: {calls}")
print(answer)
PY
