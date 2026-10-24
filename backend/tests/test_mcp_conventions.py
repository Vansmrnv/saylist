"""ADR 0005, enforced: every MCP tool follows the naming, description and envelope rules."""

import re
from typing import Any

from mcp.types import Tool

from app.mcp_server import build_mcp

READ_SUFFIXES = ("_list", "_get")
SPECIAL = {"whoami"}
NAME = re.compile(r"^[a-z]+(_[a-z]+)+$")


async def _tools() -> list[Tool]:
    return await build_mcp().list_tools()


def _props(tool: Tool) -> dict[str, Any]:
    props: dict[str, Any] = tool.inputSchema.get("properties", {})
    return props


async def test_names_are_entity_verb() -> None:
    bad = [t.name for t in await _tools() if t.name not in SPECIAL and not NAME.match(t.name)]
    assert not bad, f"rename to <entity>_<verb>: {bad}"


async def test_every_tool_has_a_docstring_description() -> None:
    bad = [t.name for t in await _tools() if not (t.description or "").strip()]
    assert not bad, f"write the description as the handler's docstring: {bad}"


async def test_writes_take_a_list() -> None:
    bad = []
    for tool in await _tools():
        if tool.name in SPECIAL or tool.name.endswith(READ_SUFFIXES):
            continue
        props = _props(tool)
        if len(props) != 1 or next(iter(props.values())).get("type") != "array":
            bad.append(tool.name)
    assert not bad, f"write tools take exactly one list parameter: {bad}"


async def test_whoami_exists_and_lists_every_tool() -> None:
    mcp = build_mcp()
    names = {t.name for t in await mcp.list_tools()}
    assert "whoami" in names
    _, result = await mcp.call_tool("whoami", {})
    assert isinstance(result, dict)
    assert {t["name"] for t in result["tools"]} == names
