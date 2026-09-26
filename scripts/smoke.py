"""Smoke-test an MCP endpoint: `uv run python scripts/smoke.py https://cyphy.kz/kazakhstan-law/mcp`."""

import asyncio
import sys

from mcp import ClientSession
from mcp.client.streamable_http import streamable_http_client


async def main(url: str) -> None:
    async with streamable_http_client(url) as (read, write, _):
        async with ClientSession(read, write) as session:
            await session.initialize()
            print(sorted(t.name for t in (await session.list_tools()).tools))
            res = await session.call_tool("search", {"query": "электрическ\\w* самокат"})
            acts = res.structuredContent["acts"]
            print(res.isError, [(a["act_code"], a["title"][:60]) for a in acts[:5]])


asyncio.run(main(sys.argv[1]))
