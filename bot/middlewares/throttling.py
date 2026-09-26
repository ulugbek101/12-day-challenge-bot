from __future__ import annotations

import logging
import time
from collections.abc import Awaitable, Callable
from typing import Any

from aiogram import BaseMiddleware
from aiogram.types import Message, TelegramObject

logger = logging.getLogger(__name__)


class ThrottlingMiddleware(BaseMiddleware):
    """Drops messages from a user arriving faster than `rate` seconds apart.

    Admins are exempt. Albums (several photos sent at once) arrive as separate
    messages within milliseconds; only the first one gets through, which is what
    the screenshot step wants anyway.
    """

    def __init__(self, rate: float = 0.7, exempt: set[int] | None = None) -> None:
        self.rate = rate
        self.exempt = exempt or set()
        self._last_seen: dict[int, float] = {}

    async def __call__(
        self,
        handler: Callable[[TelegramObject, dict[str, Any]], Awaitable[Any]],
        event: TelegramObject,
        data: dict[str, Any],
    ) -> Any:
        if isinstance(event, Message) and event.from_user and event.from_user.id not in self.exempt:
            user_id = event.from_user.id
            now = time.monotonic()
            last = self._last_seen.get(user_id)
            self._last_seen[user_id] = now
            if last is not None and now - last < self.rate:
                logger.debug("Throttled message from user %s", user_id)
                return None
            if len(self._last_seen) > 10_000:
                cutoff = now - 60
                self._last_seen = {k: v for k, v in self._last_seen.items() if v > cutoff}
        return await handler(event, data)
