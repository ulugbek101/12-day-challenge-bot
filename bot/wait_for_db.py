"""Block until MySQL accepts connections (used by docker-entrypoint.sh).

python -m bot.wait_for_db [timeout_seconds]
"""
from __future__ import annotations

import asyncio
import sys
import time

from sqlalchemy import text

from bot.config import ConfigError, get_settings
from bot.db.engine import create_engine


async def wait(timeout: float) -> bool:
    settings = get_settings()
    deadline = time.monotonic() + timeout
    attempt = 0
    while True:
        attempt += 1
        engine = create_engine(settings.database_url)
        try:
            async with engine.connect() as conn:
                await conn.execute(text("SELECT 1"))
            print(f"Database {settings.db_host}:{settings.db_port} is ready", flush=True)
            return True
        except Exception as exc:  # noqa: BLE001 - any connect error means "not ready yet"
            if time.monotonic() >= deadline:
                print(f"Database not reachable after {timeout:.0f}s: {type(exc).__name__}", file=sys.stderr)
                return False
            print(f"Waiting for database {settings.db_host}:{settings.db_port} (attempt {attempt})...", flush=True)
        finally:
            await engine.dispose()
        await asyncio.sleep(2)


def main() -> None:
    timeout = float(sys.argv[1]) if len(sys.argv) > 1 else 90
    try:
        get_settings()
    except ConfigError as exc:
        print(f"Configuration error: {exc}", file=sys.stderr)
        raise SystemExit(1) from None
    raise SystemExit(0 if asyncio.run(wait(timeout)) else 1)


if __name__ == "__main__":
    main()
