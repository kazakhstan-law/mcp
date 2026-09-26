"""Real questions through `claude -p` against a live server. Opt-in; costs quota.

KZLAW_MCP_URL=http://127.0.0.1:8765/mcp uv run pytest -m reference -v -s
"""

from __future__ import annotations

import json
import os
import re
import subprocess
from dataclasses import dataclass, field

import pytest

pytestmark = pytest.mark.reference
URL = os.environ.get("KZLAW_MCP_URL", "")
TOOLS = ["search", "read", "at_date", "history"]
LINK = re.compile(
    r"https://github\.com/kazakhstan-law/([\w-]+)/blob/([0-9a-f]{40})/([^\s)#?]+)([^\s)]*)"
)


@dataclass
class Case:
    id: str
    question: str
    must_call: list[str]
    must_cite: list[str]  # act codes; each must appear in at least one cited link
    answer_has: list[str] = field(default_factory=list)


CASES = [
    Case(
        "scooters",
        "Какие изменения недавно внесли в правила езды на электросамокатах?",
        ["search", "read"],
        ["183572"],
    ),
    Case(
        "speed-2022",
        "В 2022 меня оштрафовали за превышение скорости на 65 км/ч — какой был штраф и какой сейчас?",
        ["at_date"],
        ["81245"],
        ["20", "40"],
    ),
    Case("form-270", "С каких пор надо сдавать форму 270?", ["history"], ["158645"], ["2021"]),
]


def ask(question: str) -> tuple[list[tuple[str, dict]], list[str], str]:
    config = json.dumps({"mcpServers": {"kazakhstan-law": {"type": "http", "url": URL}}})
    allowed = " ".join(f"mcp__kazakhstan-law__{t}" for t in TOOLS)
    proc = subprocess.run(
        [
            "claude",
            "-p",
            question,
            "--model",
            "claude-opus-5-5",
            "--mcp-config",
            config,
            "--strict-mcp-config",
            "--tools",
            "",
            "--allowedTools",
            allowed,
            "--output-format",
            "stream-json",
            "--verbose",
        ],
        capture_output=True,
        text=True,
        timeout=600,
        check=True,
    )
    calls, results, answer = [], [], ""
    for line in proc.stdout.splitlines():
        event = json.loads(line)
        content = (event.get("message") or {}).get("content") or []
        for block in content if isinstance(content, list) else []:
            if block.get("type") == "tool_use":
                calls.append((block["name"].rsplit("__", 1)[-1], block.get("input", {})))
            elif block.get("type") == "tool_result":
                results.append(json.dumps(block.get("content"), ensure_ascii=False))
        if event.get("type") == "result":
            answer = event.get("result", "")
    return calls, results, answer


@pytest.mark.skipif(not URL, reason="set KZLAW_MCP_URL")
@pytest.mark.parametrize("case", CASES, ids=[c.id for c in CASES])
def test_reference(case: Case):
    calls, results, answer = ask(case.question)
    print(f"\n--- {case.id}: {[n for n, _ in calls]}\n{answer}")
    called = {name for name, _ in calls}
    assert set(case.must_call) <= called, called
    links = LINK.findall(answer)
    assert links, "the answer cites nothing"
    seen = "\n".join(results)
    for scope, sha, path, tail in links:  # the whole link, line range included, verbatim
        url = f"/{scope}/blob/{sha}/{path}{tail}"
        assert url in seen, f"cited link not returned by a tool: {path}{tail}"
    for code in case.must_cite:
        assert any(
            path.split("/")[-2].endswith(f"-{code}") or f"-{code}/" in path
            for _, _, path, _ in links
        ), f"act {code} not cited"
    for text in case.answer_has:
        assert text in answer
