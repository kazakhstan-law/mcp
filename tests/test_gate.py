import json
from types import SimpleNamespace

import pytest

from kzlaw_mcp.corpus import InputError
from kzlaw_mcp.gate import Gate, RateLimiter, client_ip
from kzlaw_mcp.gitio import CommandError


def req(peer, xff=None):
    headers = {"x-forwarded-for": xff} if xff else {}
    return SimpleNamespace(client=SimpleNamespace(host=peer), headers=headers)


def test_rate_limiter_window():
    now = [0.0]
    rl = RateLimiter(2, 10, clock=lambda: now[0])
    assert rl.hit("a") is None and rl.hit("a") is None
    assert rl.hit("a") == pytest.approx(10)
    assert rl.hit("b") is None
    now[0] = 10.5
    assert rl.hit("a") is None


def test_forwarded_for_only_from_the_proxy():
    trusted = frozenset({"100.64.0.1"})
    assert client_ip(req("100.64.0.1", "1.2.3.4"), trusted) == ("1.2.3.4", True)
    assert client_ip(req("100.64.0.1", "6.6.6.6, 1.2.3.4"), trusted) == ("1.2.3.4", True)
    assert client_ip(req("5.5.5.5", "1.2.3.4"), trusted) == ("5.5.5.5", False)
    assert client_ip(None, trusted) == ("local", False)


@pytest.mark.anyio
async def test_gate_logs_and_limits(settings):
    from dataclasses import replace

    gate = Gate(replace(settings, rate_calls=1))
    assert await gate.call("search", {"q": "x"}, req("9.9.9.9"), lambda: {"ok": 1}) == {"ok": 1}
    with pytest.raises(InputError, match="rate limit"):
        await gate.call("search", {"q": "x"}, req("9.9.9.9"), lambda: {"ok": 1})
    rows = [json.loads(line) for line in settings.log_path.read_text().splitlines()]
    assert [r["ok"] for r in rows] == [True, False] and rows[1]["error"] == "rate_limited"
    assert rows[0]["ip"] != "9.9.9.9" and len(rows[0]["ip"]) == 16


@pytest.mark.anyio
async def test_gate_turns_command_errors_into_input_errors(settings):
    def boom():
        raise CommandError("rg timed out after 20s")

    with pytest.raises(InputError, match="temporary failure"):
        await Gate(settings).call("search", {}, None, boom)


def test_default_rate_fits_a_conversation():
    from kzlaw_mcp.config import Settings

    # one question takes 5-20 tool calls (measured on the reference questions)
    assert Settings(corpus_root=None).rate_calls >= 300


@pytest.mark.anyio
async def test_log_rows_stay_small(settings):
    from dataclasses import replace

    gate = Gate(replace(settings, rate_calls=1))
    big = {"query": "я" * 5000, "scopes": ["x" * 5000] * 1000}
    await gate.call("search", big, req("9.9.9.9"), lambda: {"ok": 1})
    with pytest.raises(InputError):
        await gate.call("search", big, req("9.9.9.9"), lambda: {"ok": 1})
    rows = [json.loads(line) for line in settings.log_path.read_text().splitlines()]
    assert len(json.dumps(rows[0], ensure_ascii=False)) < 2000
    assert "args" not in rows[1]  # a rate-limited caller cannot write its payload


@pytest.mark.anyio
async def test_unexpected_errors_are_logged_and_hidden(settings):
    def boom():
        raise FileNotFoundError("/corpus/codes/secret/path")

    with pytest.raises(InputError, match="internal error") as exc:
        await Gate(settings).call("read", {}, None, boom)
    assert "/corpus" not in str(exc.value)
    [row] = [json.loads(line) for line in settings.log_path.read_text().splitlines()]
    assert row["ok"] is False and row["error"] == "FileNotFoundError"


def test_logging_without_a_salt_is_refused(settings):
    from dataclasses import replace

    with pytest.raises(ValueError, match="KZLAW_IP_SALT"):
        Gate(replace(settings, ip_salt=""))


@pytest.mark.anyio
async def test_gate_logs_what_a_search_found(settings):
    r = req("9.9.9.9")
    r.headers["user-agent"] = "Claude-User/1.0 (+https://www.anthropic.com)"
    result = {
        "acts": [{"hits": [1, 2]}, {"hits": [3]}],
        "rewritten": {"from": "курение", "to": "потреблени\\w* табачн\\w*"},
        "truncated": True,
    }
    await Gate(settings).call("search", {"query": "курение"}, r, lambda: result)
    await Gate(settings).call("search", {"query": "x"}, None, lambda: {"acts": [], "tried": ["a"]})
    await Gate(settings).call("read", {}, None, lambda: {"oddly": "shaped"})
    rows = [json.loads(line) for line in settings.log_path.read_text().splitlines()]
    assert rows[0]["client"] == "Claude-User"
    assert rows[0]["acts"] == 2 and rows[0]["hits"] == 3 and rows[0]["truncated"] is True
    assert rows[0]["rewritten"] == "потреблени\\w* табачн\\w*"
    assert rows[1]["client"] == "local" and rows[1]["hits"] == 0 and rows[1]["tried"] == ["a"]
    assert rows[2]["ok"] is True and "hits" not in rows[2]


def test_outcome_never_raises_on_odd_results():
    from kzlaw_mcp.gate import outcome

    assert outcome("search", None) == {}
    assert outcome("search", {"acts": None, "rewritten": "x"}) == {"acts": 0, "hits": 0}
    assert outcome("search", {"acts": ["not a dict"]})["hits"] == 0


@pytest.mark.anyio
async def test_feedback_goes_to_its_own_file(settings):
    gate = Gate(settings)
    r = req("9.9.9.9")
    r.headers["user-agent"] = "openai-mcp/1.0"
    out = gate.feedback(r, "not_found", "  нет ст. 999 КоАП " + "я" * 3000, "123")
    assert out == {"recorded": True, "truncated": True}
    [row] = [
        json.loads(x)
        for x in settings.log_path.with_name("feedback.jsonl").read_text().splitlines()
    ]
    assert row["kind"] == "not_found" and row["act_code"] == "123" and row["client"] == "openai-mcp"
    assert row["message"].startswith("нет ст. 999") and len(row["message"]) == 2000
    assert row["ip"] != "9.9.9.9"
    with pytest.raises(InputError, match="empty"):
        gate.feedback(r, "other", "   ", None)


def test_feedback_without_a_log_is_not_stored(settings):
    from dataclasses import replace

    out = Gate(replace(settings, log_path=None)).feedback(None, "other", "x", None)
    assert out["recorded"] is False
