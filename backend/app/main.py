import asyncio
import contextlib
import logging
from collections.abc import AsyncIterator, Coroutine
from contextlib import asynccontextmanager
from typing import Any

from aiogram import Bot, Dispatcher
from aiogram.client.default import DefaultBotProperties
from fastapi import FastAPI

from app import telegram_bot, web
from app.core import stt
from app.core.config import get_settings
from app.core.db import get_sessionmaker
from app.mcp_server import build_mcp
from app.modules import jobs, load_all, messaging

log = logging.getLogger("main")


async def _poll(bot: Bot) -> None:
    dp = Dispatcher()
    dp.include_router(telegram_bot.router)
    me = await bot.get_me()
    log.info("business bot: https://t.me/%s", me.username)
    await bot.delete_webhook(drop_pending_updates=True)  # skip taps left from a previous run
    await dp.start_polling(bot, handle_signals=False)


async def _expiry_loop() -> None:
    while True:
        try:
            async with get_sessionmaker()() as session, session.begin():
                await jobs.expire_stale(session)
        except Exception:
            log.exception("expiry loop error")
        await asyncio.sleep(30)


def _workers() -> list[Coroutine[Any, Any, None]]:
    settings = get_settings()
    if not settings.anthropic_api_key:
        log.warning("ANTHROPIC_API_KEY is not set: every LLM call will fail")
    if not stt.available():
        log.warning("OPENAI_API_KEY is not set: voice notes are disabled, text still works")
    bot = None
    if settings.business_bot_token:
        bot = Bot(settings.business_bot_token, default=DefaultBotProperties(parse_mode="HTML"))
    else:
        log.warning("BUSINESS_BOT_TOKEN is not set: no Telegram bot, outbox rows stay pending")
    workers = [messaging.run_worker(get_sessionmaker(), bot), _expiry_loop()]
    if bot:
        workers.append(_poll(bot))
    return workers


def create_app() -> FastAPI:
    load_all()
    mcp = build_mcp()
    mcp_app = mcp.streamable_http_app()  # serves /mcp

    @asynccontextmanager
    async def lifespan(app: FastAPI) -> AsyncIterator[None]:
        logging.basicConfig(  # force: FastMCP configured logging already
            level=logging.INFO,
            format="%(asctime)s %(levelname)-7s %(name)s: %(message)s",
            datefmt="%H:%M:%S",
            force=True,
        )
        logging.getLogger("aiogram.event").setLevel(logging.WARNING)
        logging.getLogger("httpx").setLevel(logging.WARNING)
        async with mcp.session_manager.run():
            tasks = (
                [asyncio.create_task(w) for w in _workers()] if get_settings().run_workers else []
            )
            yield
            for task in tasks:
                task.cancel()
            for task in tasks:
                with contextlib.suppress(BaseException):
                    await task

    app = FastAPI(title="saylist", lifespan=lifespan)

    @app.get("/health")
    async def health() -> dict[str, str]:
        return {"status": "ok"}

    app.include_router(web.router)
    app.mount("/", mcp_app)  # last: everything not matched above, i.e. /mcp
    return app


app = create_app()
