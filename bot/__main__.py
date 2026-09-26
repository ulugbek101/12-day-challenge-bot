"""Entrypoint: python -m bot"""
from __future__ import annotations

import asyncio
import logging
import sys

from aiogram import Bot, Dispatcher
from aiogram.client.default import DefaultBotProperties
from aiogram.enums import ParseMode
from aiogram.fsm.storage.base import BaseEventIsolation
from aiogram.fsm.storage.memory import SimpleEventIsolation

from bot.config import ConfigError, get_settings
from bot.db.engine import create_engine, create_session_factory
from bot.fsm.mysql_storage import MySQLStorage
from bot.handlers import setup_routers
from bot.i18n import setup_i18n
from bot.logging_setup import setup_logging
from bot.middlewares.db import ClientMiddleware, DbSessionMiddleware
from bot.middlewares.i18n import DbI18nMiddleware
from bot.middlewares.throttling import ThrottlingMiddleware
from bot.services import expiry
from bot.services.startup import check_channel_rights, report_channel_problem

logger = logging.getLogger("bot")


async def main() -> None:
    try:
        settings = get_settings()
    except ConfigError as exc:
        print(f"Configuration error: {exc}", file=sys.stderr)
        raise SystemExit(1) from None

    setup_logging(settings.log_level)
    logger.info("Starting bot: %d admin(s), channel %s", len(settings.admins), settings.channel_id)

    i18n = setup_i18n(settings.default_language)
    engine = create_engine(settings.database_url)
    session_factory = create_session_factory(engine)

    bot = Bot(settings.bot_token, default=DefaultBotProperties(parse_mode=ParseMode.HTML))
    # Per-user lock around each update: a double tap is processed strictly after the
    # first tap has finished (and committed), never concurrently with it.
    isolation: BaseEventIsolation = SimpleEventIsolation()
    dp = Dispatcher(storage=MySQLStorage(session_factory), events_isolation=isolation)

    dp.update.outer_middleware(DbSessionMiddleware(session_factory))
    dp.update.outer_middleware(ClientMiddleware())
    dp.update.outer_middleware(DbI18nMiddleware(i18n))
    dp.message.outer_middleware(ThrottlingMiddleware(exempt=set(settings.admins)))
    dp.include_router(setup_routers())

    expiry_task: asyncio.Task[None] | None = None

    async def on_startup(bot: Bot) -> None:
        nonlocal expiry_task
        problem = await check_channel_rights(bot)
        if problem:
            await report_channel_problem(bot, problem)
        else:
            logger.info("Channel rights OK: bot can create invite links")
        expiry_task = asyncio.create_task(expiry.expiry_loop(bot, session_factory), name="link-expiry")

    async def on_shutdown() -> None:
        await expiry.stop(expiry_task)
        await engine.dispose()
        logger.info("Shutdown complete")

    dp.startup.register(on_startup)
    dp.shutdown.register(on_shutdown)

    # Long polling. Pending updates are kept: join requests made while the bot was
    # down must still be answered.
    await bot.delete_webhook(drop_pending_updates=False)
    await dp.start_polling(bot, allowed_updates=dp.resolve_used_update_types())


if __name__ == "__main__":
    asyncio.run(main())
