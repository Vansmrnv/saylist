"""Single process: business bot polling + MCP/admin HTTP server + expiry loop."""
import asyncio
import logging

import uvicorn
from aiogram import Bot, Dispatcher
from aiogram.client.default import DefaultBotProperties

import admin
import business_bot
import config
import core
import db
import stt
from mcp_server import mcp

log = logging.getLogger("main")


async def run_business_bot(bot: Bot) -> None:
    dp = Dispatcher()
    dp.include_router(business_bot.router)
    me = await bot.get_me()
    log.info("business bot: https://t.me/%s", me.username)
    # Skip button presses left over from a previous run.
    await bot.delete_webhook(drop_pending_updates=True)
    await dp.start_polling(bot, handle_signals=False)


async def main() -> None:
    db.init_db()
    if not config.ANTHROPIC_API_KEY:
        log.warning("ANTHROPIC_API_KEY is not set: every LLM call will fail")
    if not stt.available():
        log.warning("OPENAI_API_KEY is not set: voice notes are disabled, text still works")

    bot = None
    if config.BUSINESS_BOT_TOKEN:
        bot = Bot(config.BUSINESS_BOT_TOKEN, default=DefaultBotProperties(parse_mode="HTML"))
    else:
        log.warning("BUSINESS_BOT_TOKEN is not set: running without the Telegram bot")
    core.init(bot)

    admin.register(mcp)
    server = uvicorn.Server(uvicorn.Config(mcp.streamable_http_app(), host="0.0.0.0", port=config.PORT,
                                           log_level="warning"))
    log.info("MCP endpoint: http://localhost:%d/mcp   admin: http://localhost:%d/admin", config.PORT, config.PORT)

    tasks = [asyncio.create_task(server.serve()), asyncio.create_task(core.expiry_loop())]
    if bot:
        tasks.append(asyncio.create_task(run_business_bot(bot)))
    try:
        # uvicorn handles Ctrl+C; when it stops (or anything crashes) stop everything.
        done, _ = await asyncio.wait(tasks, return_when=asyncio.FIRST_COMPLETED)
        for t in done:
            if t.exception():
                log.error("task crashed", exc_info=t.exception())
    finally:
        for t in tasks:
            t.cancel()
        await asyncio.gather(*tasks, return_exceptions=True)
        if bot:
            await bot.session.close()


if __name__ == "__main__":
    try:
        asyncio.run(main())
    except KeyboardInterrupt:
        pass
