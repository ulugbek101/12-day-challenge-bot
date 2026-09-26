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

import os
from collections.abc import AsyncIterator

import pytest_asyncio
from sqlalchemy import text
from sqlalchemy.ext.asyncio import AsyncEngine, AsyncSession, async_sessionmaker

from bot.db.engine import create_engine, create_session_factory
from bot.db.models import Base

TEST_DATABASE_URL = os.environ.get(
    "TEST_DATABASE_URL",
    "mysql+asyncmy://stylist:test_pw@127.0.0.1:3307/stylist_test?charset=utf8mb4",
)


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
