"""Speech-to-text with OpenAI whisper-1. Optional: without OPENAI_API_KEY the
business bot asks for text instead."""
import logging

from openai import AsyncOpenAI

import config

log = logging.getLogger("stt")

_client: AsyncOpenAI | None = None


def available() -> bool:
    return bool(config.OPENAI_API_KEY)


async def transcribe(data: bytes, filename: str = "voice.ogg") -> str:
    global _client
    if _client is None:
        _client = AsyncOpenAI(api_key=config.OPENAI_API_KEY)
    result = await _client.audio.transcriptions.create(model="whisper-1", file=(filename, data))
    log.info("transcript: %s", result.text)
    return result.text
