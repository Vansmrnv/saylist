"""MCP server for AI assistants (Claude, ChatGPT) acting for a customer. Conventions: ADR 0005.
Thin: each tool opens a transaction per item and calls the jobs contract."""

from typing import Any

from mcp.server.fastmcp import Context, FastMCP
from mcp.server.transport_security import TransportSecuritySettings
from pydantic import BaseModel, Field
from starlette.requests import Request

from app.core.config import get_settings
from app.core.db import get_sessionmaker
from app.core.llm import LLMError
from app.modules import businesses, jobs

INSTRUCTIONS = (
    "Books local tradespeople (electricians, plumbers, locksmiths, handymen, cleaners, AC "
    "technicians) for the user, so that nobody has to phone anybody. Before creating a request, "
    "collect everything the tradesperson needs to arrive without calling: the exact address "
    "(street and house number, flat and floor), how to get in (gate code, which bell, parking), "
    "when, what the job is, and the user's name and phone. Then: job_request_create (a draft), "
    "read it back, job_request_confirm, and give the user the tracking link."
)


class JobRef(BaseModel):
    job_id: int


class JobCancel(BaseModel):
    job_id: int
    reason: str = Field(default="", description="Optional, shown to the business.")


def _allowed(tool: str) -> bool:
    """Who may call what. Anyone may use every tool today: there are no customer accounts."""
    return True


def _base_url(ctx: Context[Any, Any, Any]) -> str:
    configured = get_settings().public_url.rstrip("/")
    if configured:
        return configured
    request = ctx.request_context.request
    if isinstance(request, Request):
        proto = request.headers.get("x-forwarded-proto", request.url.scheme)
        host = request.headers.get(
            "x-forwarded-host", request.headers.get("host", request.url.netloc)
        )
        return f"{proto}://{host}"
    return "http://localhost:8000"


def _job(view: jobs.JobView | None, ctx: Context[Any, Any, Any]) -> dict[str, Any] | None:
    if view is None:
        return None
    data = view.model_dump(mode="json")
    data["tracking_url"] = f"{_base_url(ctx)}/t/{view.token}"
    del data["token"]
    return data


def _result(result: jobs.WriteResult, ctx: Context[Any, Any, Any]) -> dict[str, Any]:
    return {"outcome": result.outcome, "why": result.why, "job": _job(result.job, ctx)}


def _error(why: str) -> dict[str, Any]:
    return {"outcome": jobs.Outcome.REFUSED, "why": why, "job": None}


def _rows(rows: list[Any]) -> dict[str, Any]:
    return {"rows": rows, "returned": len(rows), "truncated": False, "next_offset": None}


def build_mcp() -> FastMCP:
    mcp = FastMCP(
        "saylist",
        instructions=INSTRUCTIONS,
        stateless_http=True,
        json_response=True,
        # Reached through an ngrok/cloudflared tunnel, so the Host header is not localhost.
        transport_security=TransportSecuritySettings(enable_dns_rebinding_protection=False),
    )

    @mcp.tool()
    async def whoami() -> dict[str, Any]:
        """Lists every tool and whether you may use it. No sign-in is needed: you act for the
        customer you are talking to."""
        tools = await mcp.list_tools()
        return {
            "caller": "an assistant acting for a customer",
            "tools": [{"name": t.name, "allowed": _allowed(t.name)} for t in tools],
        }

    @mcp.tool()
    async def trade_list() -> dict[str, Any]:
        """Lists the kinds of tradespeople that can be booked."""
        return _rows(
            [{"trade": t.value, "label": businesses.trade_label(t)} for t in businesses.Trade]
        )

    @mcp.tool()
    async def job_request_create(
        requests: list[jobs.JobRequestIn], ctx: Context[Any, Any, Any]
    ) -> dict[str, Any]:
        """Step 1 of 2: checks a job request and finds the local businesses free at that time,
        with each one's price. Sends nothing yet.

        Collect every field from the customer first. The address must be exact: street name and
        house number plus flat/floor (a village or district alone is INVALID), and access_notes
        must say how to get in without phoning. On INVALID, `why` says what to ask the customer;
        ask, then call again. On DONE, read the draft (address, time, quotes) back to the
        customer, then call job_request_confirm with job.job_id. On REFUSED nobody is free:
        suggest another time."""
        results = []
        for request in requests:
            try:
                async with get_sessionmaker()() as session, session.begin():
                    result = await jobs.draft_request(session, request, channel="assistant")
                results.append(_result(result, ctx))
            except LLMError:
                results.append(_error("Could not read the request just now. Call again."))
        return {"results": results}

    @mcp.tool()
    async def job_request_confirm(
        requests: list[JobRef], ctx: Context[Any, Any, Any]
    ) -> dict[str, Any]:
        """Step 2 of 2: sends a confirmed draft to the businesses. The first to accept books a
        concrete arrival time. Give the customer job.tracking_url: it shows live when the business
        is booked, on the way (with ETA) and at the door. Tell them they can also ask you; use
        job_request_get to check."""
        results = []
        for ref in requests:
            async with get_sessionmaker()() as session, session.begin():
                result = await jobs.confirm_request(session, ref.job_id)
            results.append(_result(result, ctx))
        return {"results": results}

    @mcp.tool()
    async def job_request_get(job_ids: list[int], ctx: Context[Any, Any, Any]) -> dict[str, Any]:
        """Gets the live status of jobs: status_text says it in one sentence (e.g. "Nikos is on the
        way, arriving around 16:20"). Once booked it includes the business name, phone, booked time
        and price. The timeline lists every step."""
        async with get_sessionmaker()() as session:
            views = await jobs.get_jobs(session, job_ids)
        return _rows([_job(v, ctx) for v in views])

    @mcp.tool()
    async def job_request_cancel(
        requests: list[JobCancel], ctx: Context[Any, Any, Any]
    ) -> dict[str, Any]:
        """Cancels jobs for the customer. Possible until the business is at the door; the business
        is told immediately."""
        results = []
        for item in requests:
            async with get_sessionmaker()() as session, session.begin():
                result = await jobs.cancel_request(session, item.job_id, item.reason)
            results.append(_result(result, ctx))
        return {"results": results}

    return mcp
