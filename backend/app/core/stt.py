"""Speech-to-text with OpenAI whisper-1. Optional: without OPENAI_API_KEY voice is disabled."""

import logging

from openai import AsyncOpenAI

from app.core.config import get_settings

log = logging.getLogger("stt")

_client: AsyncOpenAI | None = None


def available() -> bool:
    return bool(get_settings().openai_api_key)


async def transcribe(data: bytes, filename: str = "voice.ogg") -> str:
    global _client
    if _client is None:
        _client = AsyncOpenAI(api_key=get_settings().openai_api_key)
    result = await _client.audio.transcriptions.create(model="whisper-1", file=(filename, data))
    log.info("transcript: %s", result.text)
    return result.text
