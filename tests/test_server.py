import socket
import threading
import time

import httpx
import pytest
import uvicorn
from fastmcp import Client

from conftest import KOAP_CODE
from kzlaw_mcp.server import build_server


@pytest.fixture
def server_url(settings):
    with socket.socket() as s:
        s.bind(("127.0.0.1", 0))
        port = s.getsockname()[1]
    app = build_server(settings).http_app(stateless_http=True, json_response=True)
    server = uvicorn.Server(uvicorn.Config(app, host="127.0.0.1", port=port, log_level="warning"))
    thread = threading.Thread(target=server.run, daemon=True)
    thread.start()
    for _ in range(100):
        if server.started:
            break
        time.sleep(0.05)
    yield f"http://127.0.0.1:{port}"
    server.should_exit = True
    thread.join(5)


@pytest.mark.anyio
@pytest.mark.parametrize("mode", ["legacy", "auto"])  # the initialize handshake; server/discover
async def test_tools_over_streamable_http(server_url, mode):
    async with Client(f"{server_url}/mcp", mode=mode) as client:
        assert "citation" in (client.instructions or "")
        tools = {t.name: t for t in await client.list_tools()}
        readers = {"search", "read", "at_date", "history", "changes"}
        assert set(tools) == readers | {"feedback"}
        # unmarked tools make ChatGPT ask the user before every call
        assert all(tools[n].annotations.read_only_hint is True for n in readers)
        assert tools["feedback"].annotations.read_only_hint is False
        assert tools["feedback"].annotations.destructive_hint is False
        res = await client.call_tool("search", {"query": "превышение установленной скорости"})
        assert res.structured_content is not None
        assert res.structured_content["acts"][0]["act_code"] == KOAP_CODE
        bad = await client.call_tool_mcp("read", {"act_code": "../../etc"})
        assert bad.is_error
        assert bad.content[0].text.startswith("act_code")
        sent = await client.call_tool("feedback", {"kind": "not_found", "message": "нет ничего"})
        assert sent.structured_content == {"recorded": True, "truncated": False}


def test_landing_and_health(server_url):
    assert "claude.ai" in httpx.get(f"{server_url}/").text
    assert httpx.get(f"{server_url}/health").json() == {"ok": True, "scopes": 2}
