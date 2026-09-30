import socket
import threading
import time

import httpx
import pytest
import uvicorn
from mcp import ClientSession
from mcp.client.streamable_http import streamable_http_client

from conftest import KOAP_CODE
from kzlaw_mcp.server import build_server


@pytest.fixture
def server_url(settings):
    with socket.socket() as s:
        s.bind(("127.0.0.1", 0))
        port = s.getsockname()[1]
    app = build_server(settings).streamable_http_app()
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
async def test_tools_over_streamable_http(server_url):
    async with (
        streamable_http_client(f"{server_url}/mcp") as (read, write, _),
        ClientSession(read, write) as session,
    ):
        init = await session.initialize()
        assert "citation" in init.instructions
        names = {t.name for t in (await session.list_tools()).tools}
        assert names == {"search", "read", "at_date", "history", "changes"}
        res = await session.call_tool("search", {"query": "превышение установленной скорости"})
        assert not res.isError
        assert res.structuredContent["acts"][0]["act_code"] == KOAP_CODE
        bad = await session.call_tool("read", {"act_code": "../../etc"})
        assert bad.isError and "act_code" in bad.content[0].text


def test_landing_and_health(server_url):
    assert "claude.ai" in httpx.get(f"{server_url}/").text
    assert httpx.get(f"{server_url}/health").json() == {"ok": True, "scopes": 2}
