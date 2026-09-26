"""Alembic migrations against a real, separate MySQL database.

Needs the test user to have privileges on MIGRATION_DB (created/dropped here):
    GRANT ALL ON stylist_migr_check.* TO 'stylist'@'%';
"""
import asyncio
import os
import subprocess
import sys
from pathlib import Path

from sqlalchemy import text
from sqlalchemy.engine import make_url
from sqlalchemy.ext.asyncio import create_async_engine

from tests.conftest import TEST_DATABASE_URL

ROOT = Path(__file__).resolve().parent.parent
MIGRATION_DB = os.environ.get("TEST_MIGRATION_DB", "stylist_migr_check")
MIGRATION_URL = make_url(TEST_DATABASE_URL).set(database=MIGRATION_DB).render_as_string(hide_password=False)


def _recreate_database() -> None:
    async def run() -> None:
        engine = create_async_engine(TEST_DATABASE_URL)
        async with engine.begin() as conn:
            await conn.execute(text(f"DROP DATABASE IF EXISTS `{MIGRATION_DB}`"))
            await conn.execute(
                text(f"CREATE DATABASE `{MIGRATION_DB}` CHARACTER SET utf8mb4 COLLATE utf8mb4_unicode_ci")
            )
        await engine.dispose()

    asyncio.run(run())


def _alembic(*args: str) -> subprocess.CompletedProcess[str]:
    return subprocess.run(
        [sys.executable, "-m", "alembic", "-x", f"url={MIGRATION_URL}", *args],
        cwd=ROOT,
        capture_output=True,
        text=True,
        encoding="utf-8",
    )


def test_upgrade_matches_models_and_downgrades_cleanly():
    _recreate_database()

    upgrade = _alembic("upgrade", "head")
    assert upgrade.returncode == 0, upgrade.stderr

    # Fails if the models and the migrations have drifted apart.
    check = _alembic("check")
    assert check.returncode == 0, check.stdout + check.stderr

    downgrade = _alembic("downgrade", "base")
    assert downgrade.returncode == 0, downgrade.stderr

    again = _alembic("upgrade", "head")
    assert again.returncode == 0, again.stderr
