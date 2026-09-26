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
