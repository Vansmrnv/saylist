"""Call the MCP tools like an assistant would: `make try-mcp` (server must be running).

Tries a vague address first (expect INVALID), then the full flow: draft, confirm, get."""

import asyncio
import json
import sys
from typing import Any

from mcp import ClientSession
from mcp.client.streamable_http import streamablehttp_client

REQUEST = {
    "trade": "electrician",
    "when": "any weekday after 4pm",
    "street_address": "Mouttagiaka",
    "unit": "house",
    "city": "Limassol",
    "access_notes": "Gate is open, ring the bell 'Alex'",
    "description": "Kitchen sockets stopped working",
    "customer_name": "Alex Test",
    "customer_phone": "+357 99 123456",
}


async def call(session: ClientSession, tool: str, args: dict[str, Any]) -> Any:
    result = await session.call_tool(tool, args)
    data = json.loads(result.content[0].text)  # type: ignore[union-attr]
    print(f"\n--- {tool} ->\n{json.dumps(data, indent=2, ensure_ascii=False)[:1500]}")
    return data


async def main() -> None:
    url = (sys.argv[1] if len(sys.argv) > 1 else "http://localhost:8000").rstrip("/") + "/mcp"
    async with (
        streamablehttp_client(url) as (read, write, _),
        ClientSession(read, write) as session,
    ):
        await session.initialize()
        print("tools:", [t.name for t in (await session.list_tools()).tools])
        vague = await call(session, "job_request_create", {"requests": [REQUEST]})
        assert vague["results"][0]["outcome"] == "INVALID"
        exact = {**REQUEST, "street_address": "Agias Fylaxeos 45"}
        draft = (await call(session, "job_request_create", {"requests": [exact]}))["results"][0]
        assert draft["outcome"] == "DONE", draft
        job_id = draft["job"]["job_id"]
        await call(session, "job_request_confirm", {"requests": [{"job_id": job_id}]})
        await call(session, "job_request_get", {"job_ids": [job_id]})


if __name__ == "__main__":
    asyncio.run(main())
