"""Localized messages to clients and admin notices ("… — Open")."""
from __future__ import annotations

import logging
from collections.abc import Callable

from aiogram import Bot
from aiogram.exceptions import TelegramAPIError
from aiogram.types import InlineKeyboardMarkup, LinkPreviewOptions
from sqlalchemy.ext.asyncio import AsyncSession

from bot.config import get_settings
from bot.db.models import Client
from bot.db.repositories import clients as clients_repo
from bot.i18n import in_locale
from bot.keyboards.admin import notice_open
from bot.services.tg import describe_error, with_retry

logger = logging.getLogger(__name__)

MessageBuilder = Callable[[], tuple[str, InlineKeyboardMarkup | None]]


def client_locale(client: Client | None) -> str | None:
    return client.language.value if client is not None and client.language is not None else None


async def send_to_client(bot: Bot, client: Client, build: MessageBuilder) -> str | None:
    """Send a message built in the client's own language. Returns an error string on failure."""
    with in_locale(client_locale(client)):
        text, markup = build()
    try:
        await with_retry(
            lambda: bot.send_message(
                client.telegram_id,
                text,
                reply_markup=markup,
                link_preview_options=LinkPreviewOptions(is_disabled=True),
            )
        )
    except TelegramAPIError as exc:
        logger.warning("Could not message client %s (tg %s): %s", client.id, client.telegram_id, exc.message)
        return describe_error(exc)
    return None


async def notify_admins(bot: Bot, session: AsyncSession, *, client_id: int, build: Callable[[], str]) -> int:
    """Send every admin a short notice (in their language) with an "Open" button.

    Returns how many admins actually received it.
    """
    delivered = 0
    for admin_id in get_settings().admins:
        admin_row = await clients_repo.get_by_telegram_id(session, admin_id)
        with in_locale(client_locale(admin_row)):
            text = build()
            markup = notice_open(client_id)
        try:
            await with_retry(lambda: bot.send_message(admin_id, text, reply_markup=markup))
            delivered += 1
        except TelegramAPIError:
            logger.exception("Could not deliver admin notice to %s (client %s)", admin_id, client_id)
    return delivered
