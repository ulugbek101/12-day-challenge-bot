"""Test fixtures. Runs against a real MySQL database (no sqlite substitute).

Point TEST_DATABASE_URL at a disposable MySQL 8 instance; defaults to the
throwaway container used during development:
    docker run -d --name stylist_test_mysql \\
        -e MYSQL_ROOT_PASSWORD=test_root_pw -e MYSQL_DATABASE=stylist_test \\
        -e MYSQL_USER=stylist -e MYSQL_PASSWORD=test_pw \\
        -p 127.0.0.1:3307:3306 mysql:8 \\
        --character-set-server=utf8mb4 --collation-server=utf8mb4_unicode_ci
"""
from __future__ import annotations

import logging
import os
from collections.abc import AsyncIterator
from dataclasses import dataclass, field
from pathlib import Path
from typing import Any

import pytest
import pytest_asyncio
from sqlalchemy import text
from sqlalchemy.ext.asyncio import AsyncEngine, AsyncSession, async_sessionmaker

TEST_DATABASE_URL = os.environ.get(
    "TEST_DATABASE_URL",
    "mysql+asyncmy://stylist:test_pw@127.0.0.1:3307/stylist_test?charset=utf8mb4",
)

# Settings used by the app under test. Real environment variables take precedence
# over .env in pydantic-settings, so a developer's local .env never leaks in.
ADMIN_1, ADMIN_2 = 900001, 900002
CHANNEL_ID = -1001234567890
os.environ.update(
    {
        "BOT_TOKEN": "123456:TEST-TOKEN",
        "ADMINS": f"{ADMIN_1}, {ADMIN_2}",
        "CHANNEL_ID": str(CHANNEL_ID),
        "DB_HOST": "127.0.0.1",
        "DB_PORT": "3307",
        "DB_USER": "stylist",
        "DB_PASSWORD": "test_pw",
        "DB_NAME": "stylist_test",
        "TZ": "Asia/Tashkent",
        "DEFAULT_LANGUAGE": "ru",
        "PAYMENT_PAGE_URL": "https://example.com/pay",
        "SUPPORT_USERNAME": "stylist_support",
        "INVITE_LINK_TTL_HOURS": "24",
        "LOG_LEVEL": "INFO",
    }
)

from bot.db.engine import create_engine, create_session_factory  # noqa: E402
from bot.db.models import Base  # noqa: E402

LOCALES = Path(__file__).resolve().parent.parent / "bot" / "locales"


def _compile_translations() -> None:
    from babel.messages.mofile import write_mo
    from babel.messages.pofile import read_po

    for po in LOCALES.glob("*/LC_MESSAGES/messages.po"):
        with po.open("rb") as fh:
            catalog = read_po(fh)
        with po.with_suffix(".mo").open("wb") as fh:
            write_mo(fh, catalog)


@pytest_asyncio.fixture(scope="session")
async def engine() -> AsyncIterator[AsyncEngine]:
    eng = create_engine(TEST_DATABASE_URL)
    async with eng.begin() as conn:
        # Rebuild from scratch so the test schema always matches the current models.
        await conn.run_sync(Base.metadata.drop_all)
        await conn.run_sync(Base.metadata.create_all)
    yield eng
    await eng.dispose()


async def _truncate_all(engine: AsyncEngine) -> None:
    async with engine.begin() as conn:
        await conn.execute(text("SET FOREIGN_KEY_CHECKS=0"))
        for table in reversed(Base.metadata.sorted_tables):
            await conn.execute(text(f"TRUNCATE TABLE `{table.name}`"))
        await conn.execute(text("SET FOREIGN_KEY_CHECKS=1"))


@pytest_asyncio.fixture
async def session_factory(engine: AsyncEngine) -> AsyncIterator[async_sessionmaker[AsyncSession]]:
    """Clean tables before each DB test, so every test starts from an empty schema."""
    await _truncate_all(engine)
    yield create_session_factory(engine)


@pytest_asyncio.fixture
async def session(session_factory: async_sessionmaker[AsyncSession]) -> AsyncIterator[AsyncSession]:
    async with session_factory() as s:
        yield s


# ------------------------------------------------------------------ end-to-end app


class _ErrorCollector(logging.Handler):
    def __init__(self) -> None:
        super().__init__(level=logging.ERROR)
        self.records: list[logging.LogRecord] = []

    def emit(self, record: logging.LogRecord) -> None:
        self.records.append(record)


@dataclass
class App:
    """The real dispatcher wired to a fake Telegram API and the test database."""

    dp: Any
    bot: Any
    tg: Any  # tests.fakes.FakeSession
    session_factory: async_sessionmaker[AsyncSession]
    errors: _ErrorCollector
    expected_errors: list[str] = field(default_factory=list)

    async def feed(self, update: dict[str, Any]) -> None:
        await self.dp.feed_raw_update(self.bot, update)


@pytest_asyncio.fixture(scope="session")
async def _wired(engine: AsyncEngine) -> AsyncIterator[tuple[Any, Any, Any, _ErrorCollector]]:
    from aiogram import Bot
    from aiogram.client.default import DefaultBotProperties
    from aiogram.enums import ParseMode

    from bot.__main__ import build_dispatcher
    from bot.i18n import setup_i18n
    from tests.fakes import FakeSession

    _compile_translations()
    i18n = setup_i18n("ru")
    tg = FakeSession()
    bot = Bot("123456:TEST-TOKEN", session=tg, default=DefaultBotProperties(parse_mode=ParseMode.HTML))
    dp = build_dispatcher(create_session_factory(engine), i18n, throttle_rate=0)

    collector = _ErrorCollector()
    logging.getLogger("bot.handlers.errors").addHandler(collector)
    yield dp, bot, tg, collector


@pytest_asyncio.fixture
async def app(_wired, session_factory) -> AsyncIterator[App]:  # noqa: ANN001
    from bot.services import debounce

    dp, bot, tg, collector = _wired
    tg.reset()
    tg.clear_failures()
    tg.bot_is_admin = True
    collector.records.clear()
    debounce.reset()
    application = App(dp=dp, bot=bot, tg=tg, session_factory=session_factory, errors=collector)
    yield application
    unexpected = [r for r in collector.records if r.exc_info]
    if unexpected:
        import traceback

        details = "\n".join("".join(traceback.format_exception(*r.exc_info)) for r in unexpected)
        pytest.fail(f"Handler raised an unhandled exception:\n{details}")
