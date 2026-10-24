"""Call the MCP tools against a running server: python try_mcp.py [base_url]

Sends the fixture request, then checks its status (check_request waits up to
15 s, so tap Accept in Telegram meanwhile to see it flip to accepted)."""
import asyncio
import json
import sys

from mcp import ClientSession
from mcp.client.streamable_http import streamablehttp_client


async def main():
    url = (sys.argv[1] if len(sys.argv) > 1 else "http://localhost:8000").rstrip("/") + "/mcp"
    async with streamablehttp_client(url) as (read, write, _):
        async with ClientSession(read, write) as session:
            await session.initialize()
            tools = await session.list_tools()
            print("tools:", [t.name for t in tools.tools])

            sent = await session.call_tool("send_request", {
                "trade": "electrician", "when": "any weekday after 4pm", "area": "Limassol",
                "description": "Kitchen sockets stopped working", "client_name": "Maria Test",
                "client_phone": "+357 99 555555",
            })
            result = json.loads(sent.content[0].text)
            print("send_request ->", json.dumps(result, indent=2, ensure_ascii=False))

            checked = await session.call_tool("check_request", {"request_id": result["request_id"]})
            print("check_request ->", checked.content[0].text)


if __name__ == "__main__":
    asyncio.run(main())
