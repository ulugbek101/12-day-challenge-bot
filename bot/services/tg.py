"""Small helpers around Telegram API calls: flood-control retry and tolerant deletes."""
from __future__ import annotations

import asyncio
import logging
from collections.abc import Awaitable, Callable
from typing import TypeVar

from aiogram import Bot
from aiogram.exceptions import (
    TelegramAPIError,
    TelegramBadRequest,
    TelegramForbiddenError,
    TelegramRetryAfter,
)

logger = logging.getLogger(__name__)

T = TypeVar("T")


async def with_retry(factory: Callable[[], Awaitable[T]], *, attempts: int = 3) -> T:
    """Run a Bot API call, waiting out TelegramRetryAfter (flood control) between tries."""
    for attempt in range(1, attempts + 1):
        try:
            return await factory()
        except TelegramRetryAfter as exc:
            if attempt == attempts:
                raise
            logger.warning("Flood control: retrying in %s s (attempt %s/%s)", exc.retry_after, attempt, attempts)
            await asyncio.sleep(exc.retry_after)
    raise RuntimeError("unreachable")  # pragma: no cover


def is_not_modified(exc: TelegramBadRequest) -> bool:
    return "message is not modified" in exc.message.lower()


async def safe_delete(bot: Bot, chat_id: int, message_id: int) -> bool:
    """Delete a message, ignoring "not found"/"can't be deleted". Returns True if deleted."""
    try:
        await with_retry(lambda: bot.delete_message(chat_id=chat_id, message_id=message_id))
        return True
    except (TelegramBadRequest, TelegramForbiddenError) as exc:
        logger.debug("Could not delete message %s in chat %s: %s", message_id, chat_id, exc.message)
        return False


def describe_error(exc: TelegramAPIError) -> str:
    """Short human-readable reason, stored in invite_links.send_error and shown to admins."""
    return exc.message[:500]
