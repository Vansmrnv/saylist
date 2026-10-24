"""MCP server (streamable HTTP, stateless) so Claude or ChatGPT can place
requests for a client. Served at /mcp."""
import asyncio
import logging

from mcp.server.fastmcp import FastMCP
from mcp.server.transport_security import TransportSecuritySettings

import config
import core
import llm

log = logging.getLogger("mcp")

mcp = FastMCP(
    "Local Tradespeople",
    instructions=(
        "Books local tradespeople (electricians, plumbers, locksmiths, handymen, cleaners, AC technicians) "
        "for the user. Collect what they need, when, where, their name and phone, then call send_request. "
        "Use check_request to see whether a business accepted."
    ),
    stateless_http=True,
    json_response=True,
    # Reached through an ngrok/cloudflared tunnel, so the Host header is not localhost.
    transport_security=TransportSecuritySettings(enable_dns_rebinding_protection=False),
)


@mcp.tool(description=(
    "Sends a service request to local businesses who are available at that time. Ask the user for their "
    "name and phone number before calling. After calling, tell the user how many businesses received it "
    "and that they can ask you to check for a confirmation.\n\n"
    "trade: what kind of tradesperson, in plain words (e.g. 'electrician'). when: when they need it, in the "
    "user's words (e.g. 'any weekday after 4pm', 'tomorrow morning', 'asap'). area: town or district of the "
    "job. description: short description of the problem."
))
async def send_request(trade: str, when: str, area: str, description: str, client_name: str,
                       client_phone: str) -> dict:
    log.info("send_request(trade=%r, when=%r, area=%r, description=%r, client=%r %r)",
             trade, when, area, description, client_name, client_phone)
    try:
        extracted = await llm.extract_client_request(
            f"Client: I need a {trade} {when}, in {area}. {description}"
        )
    except Exception:
        log.exception("extraction failed")
        return {"status": "error", "message": "Something went wrong reading the request. Please try again."}

    if not extracted.when_json:
        return {"status": "needs_info", "message": "Couldn't work out the time. Ask the user when they need it."}
    request = {
        "trade": extracted.trade or "other",
        "when_text": extracted.when_text or when,
        "when_json": extracted.when_json.model_dump(),
        "area": area,
        "description": description,
    }
    try:
        result = await core.create_and_dispatch("claude", client_name, client_phone, request)
    except Exception:
        log.exception("dispatch failed")
        return {"status": "error", "message": "Something went wrong sending the request. Please try again."}

    label = core.trade_label(request["trade"]).lower()
    if result["sent_to"]:
        message = (f"Sent to {result['sent_to']} {label}(s) for: {request['when_text']}. "
                   f"Each one sees their own price. The first to accept gets the job; "
                   f"requests expire after {config.REQUEST_TIMEOUT_MINUTES:g} minutes.")
    else:
        message = f"No {label} is available for: {request['when_text']}. Suggest the user tries another time."
    return {**result, "trade": request["trade"], "when": request["when_text"], "message": message}


@mcp.tool(description=(
    "Checks whether a business accepted a request sent with send_request. Returns the status "
    "(open, accepted, no_match, expired) and, if accepted, the business name, phone and price. "
    "If it is still open, it waits up to 15 seconds for an answer before returning."
))
async def check_request(request_id: int) -> dict:
    for _ in range(15):
        status = core.get_status(request_id)
        if not status or status["status"] != "open":
            break
        await asyncio.sleep(1)
    if not status:
        return {"status": "not_found", "message": f"No request with id {request_id}."}
    messages = {
        "open": f"Still waiting: {status['waiting']} business(es) haven't answered yet.",
        "accepted": "Accepted! Share the business name, phone and price with the user.",
        "no_match": "Nobody is available for this request. Suggest another time.",
        "expired": "Nobody accepted in time. Suggest sending it again or trying another time.",
    }
    return {**status, "message": messages.get(status["status"], "")}


@mcp.tool(description="Lists the trades that can be booked.")
async def list_trades() -> list[str]:
    return config.TRADES
