"""LLM calls. `structured`: Claude returns JSON matching a pydantic model's schema (structured
outputs), we validate it and retry once. `tool_step`: one step of a tool-use loop that the
caller drives. Prompts live in the modules."""

import json
import logging
from dataclasses import dataclass
from typing import Any

import anthropic
from anthropic.types import Message
from anthropic.types.beta import BetaMessage
from pydantic import BaseModel, ValidationError

from app.core.config import get_settings, now_local

log = logging.getLogger("llm")

# Models that accept the server-side refusal fallback beta.
_FALLBACK_MODELS = {"claude-sonnet-5-5", "claude-opus-5-5", "claude-opus-5", "claude-fable-5-1"}

_client: anthropic.AsyncAnthropic | None = None


class LLMError(Exception):
    pass


def _get_client() -> anthropic.AsyncAnthropic:
    global _client
    if _client is None:
        _client = anthropic.AsyncAnthropic(api_key=get_settings().anthropic_api_key or None)
    return _client


def strict_schema(model: type[BaseModel]) -> dict[str, Any]:
    """Pydantic JSON schema -> structured-outputs schema: every property required,
    no extra properties, no titles or defaults."""

    def fix(node: Any) -> Any:
        if isinstance(node, dict):
            node.pop("title", None)
            node.pop("default", None)
            if node.get("type") == "object" and "properties" in node:
                node["required"] = list(node["properties"])
                node["additionalProperties"] = False
            for value in node.values():
                fix(value)
        elif isinstance(node, list):
            for value in node:
                fix(value)
        return node

    result: dict[str, Any] = fix(model.model_json_schema())
    return result


def time_context() -> str:
    now = now_local()
    return (
        f"Current local date and time: {now:%A %Y-%m-%d %H:%M} ({get_settings().timezone}). "
        "Use 24-hour HH:MM times. Days of week are mon, tue, wed, thu, fri, sat, sun."
    )


async def _create(**kwargs: Any) -> Message | BetaMessage:
    model = get_settings().llm_model
    if model in _FALLBACK_MODELS:
        beta: BetaMessage = await _get_client().beta.messages.create(
            model=model, betas=["server-side-fallback-2026-07-01"], fallbacks="default", **kwargs
        )
        return beta
    message: Message = await _get_client().messages.create(model=model, **kwargs)
    return message


async def structured[T: BaseModel](task: str, instructions: str, content: str, model: type[T]) -> T:
    """One call that must return `model`. Every input and output is logged."""
    system = f"{instructions}\n\n{time_context()}"
    schema = strict_schema(model)
    log.info("[%s] INPUT:\n%s", task, content)
    error: Exception | None = None
    for attempt in (1, 2):
        resp = await _create(
            max_tokens=16000,
            system=system,
            messages=[{"role": "user", "content": content}],
            output_config={
                "effort": get_settings().llm_effort,
                "format": {"type": "json_schema", "schema": schema},
            },
        )
        text = next((b.text for b in resp.content if b.type == "text"), "")
        log.info("[%s] OUTPUT (attempt %d, stop=%s):\n%s", task, attempt, resp.stop_reason, text)
        try:
            return model.model_validate_json(text)
        except ValidationError as e:
            error = e
            log.warning(
                "[%s] invalid output, %s", task, "retrying" if attempt == 1 else "giving up"
            )
    raise LLMError(f"{task}: invalid output after retry: {error}")


@dataclass(frozen=True)
class ToolCall:
    id: str
    name: str
    input: dict[str, Any]


@dataclass(frozen=True)
class ToolStep:
    """One model response in a tool-use loop.

    `content` is the assistant message exactly as returned (thinking blocks included), as plain
    dicts: append it to the history unchanged, because thinking blocks are bound to the
    conversation that produced them.
    """

    content: list[dict[str, Any]]
    texts: list[str]
    tool_calls: list[ToolCall]
    stop_reason: str | None


def _block_dict(block: Any) -> dict[str, Any]:
    if block.type == "text":
        return {"type": "text", "text": block.text}
    if block.type == "tool_use":
        return {"type": "tool_use", "id": block.id, "name": block.name, "input": block.input}
    data: dict[str, Any] = block.model_dump(mode="json", exclude_none=True)
    return data


async def tool_step(
    task: str, system: str, messages: list[dict[str, Any]], tools: list[dict[str, Any]]
) -> ToolStep:
    """One call with tools. The caller runs the tools and calls again with their results.
    A refusal or a truncated response raises `LLMError`. Every input and output is logged."""
    log.info("[%s] INPUT:\n%s", task, json.dumps(messages[-1], ensure_ascii=False)[:4000])
    resp = await _create(
        max_tokens=16000,
        system=system,
        messages=messages,
        tools=tools,
        output_config={"effort": get_settings().llm_effort},
    )
    content = [_block_dict(b) for b in resp.content]
    log.info(
        "[%s] OUTPUT (stop=%s):\n%s",
        task,
        resp.stop_reason,
        json.dumps(content, ensure_ascii=False)[:4000],
    )
    if resp.stop_reason in ("refusal", "max_tokens"):
        raise LLMError(f"{task}: stopped with {resp.stop_reason}")
    return ToolStep(
        content=content,
        texts=[b.text for b in resp.content if b.type == "text" and b.text.strip()],
        tool_calls=[
            ToolCall(id=b.id, name=b.name, input=dict(b.input))
            for b in resp.content
            if b.type == "tool_use"
        ],
        stop_reason=resp.stop_reason,
    )
