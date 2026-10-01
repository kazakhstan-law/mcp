import json

from kzlaw_mcp.report import chains, client_of, load, query_key, reformulations, report


def row(ts, tool="search", ip="a", query=None, **fields):
    r = {"ts": f"2026-10-01T{ts}:00+00:00", "ip": ip, "tool": tool, "ok": True, **fields}
    if query is not None:
        r["args"] = {"query": query, "act_code": None}
    return r


def write(tmp_path, rows):
    path = tmp_path / "calls.jsonl"
    path.write_text("".join(json.dumps(r, ensure_ascii=False) + "\n" for r in rows) + "{cut")
    return load(path)


def test_misses_rewrites_and_old_rows(tmp_path):
    rows = write(
        tmp_path,
        [
            row("10:00", query="старый запрос"),  # before the hits field: unknown, not a miss
            row("10:01", query="Самогон\\w*", hits=0, acts=0),
            row("10:02", query="самогон", hits=0, acts=0),
            row("10:03", query="курение", hits=4, acts=1, rewritten="потреблени\\w* табачн\\w*"),
            row("10:04", query="психучет", hits=0, acts=0, tried=["психиатрическ\\w*"]),
            row("10:05", query="только отменённые", hits=0, acts=0, repealed=2),
        ],
    )
    text = report(sorted(rows, key=lambda r: r["_ts"]))
    candidates = text.split("## Found nothing, no dictionary")[1].split("##")[0]
    assert "   2  самогон" in candidates and "старый" not in candidates
    assert "отмен" not in candidates and "психучет" not in candidates
    assert "психучет" in text.split("dictionary tried and failed")[1].split("##")[0]
    assert "курение  ->  потреблени" in text
    assert "6 searches; 5 logged with a result, 3 found nothing, 1 found only after" in text


def test_chains_split_at_the_gap_and_pair_reformulations(tmp_path):
    rows = write(
        tmp_path,
        [
            row("10:00", query="самогон", hits=0),
            row("10:01", tool="read"),
            row("10:02", query="алкогольн\\w* продукци\\w* домашн", hits=3),
            row("10:30", query="самогон", hits=0),  # a new conversation: nothing follows it
            row("10:00", ip="b", query="самогон", hits=0),
        ],
    )
    conversations = chains(rows)
    assert [len(c) for c in conversations] == [3, 1, 1]
    assert reformulations(conversations) == {("самогон", "алкогольн\\w* продукци\\w* домашн"): 1}


def test_query_key_and_clients():
    assert query_key("Курени\\w*|вейп.*") == query_key("курени вейп")
    assert query_key("учёт") == "учет"
    assert query_key("стандартн.{0,20}вычет") == "стандартн вычет"
    assert query_key("пен[ьия].*несвоевременн") == "пен несвоевременн"
    assert (
        client_of("Claude-User") == "claude" and client_of("python-httpx") == "other:python-httpx"
    )
    assert client_of(None) == "?"


def test_feedback_comes_first(tmp_path, capsys):
    from kzlaw_mcp.report import main

    write(tmp_path, [row("10:00", query="x", hits=1, acts=1)])
    note = {
        "ts": "2026-10-01T10:01:00+00:00",
        "kind": "wrong",
        "act_code": "123",
        "client": "Claude-User",
        "message": "ставка\nустарела",
    }
    (tmp_path / "feedback.jsonl").write_text(json.dumps(note, ensure_ascii=False) + "\n")
    main([str(tmp_path / "calls.jsonl")])
    text = capsys.readouterr().out
    assert text.startswith("1 calls")
    assert "## Feedback (1)" in text and "wrong act 123  [claude]" in text
    assert "ставка устарела" in text
    assert text.index("## Feedback") < text.index("## Per day")
    assert report([], feedback=[load(tmp_path / "feedback.jsonl")[0]]).startswith("## Feedback")
