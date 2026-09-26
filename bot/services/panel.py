"""The single-message admin panel.

Every admin screen replaces the previous one in the same message. Telegram can
edit text->text and media->media in place, but cannot turn a photo into a text
message (or vice versa), so those transitions send a new message and delete the
old one. The current panel message per admin is tracked in admin_panels so it
survives restarts.
"""
from __future__ import annotations

import logging
from dataclasses import dataclass

from aiogram import Bot
from aiogram.exceptions import TelegramBadRequest
from aiogram.types import (
    InlineKeyboardMarkup,
    InputMediaDocument,
    InputMediaPhoto,
    LinkPreviewOptions,
    Message,
)
from sqlalchemy.ext.asyncio import AsyncSession

from bot.db.models import ScreenshotKind
from bot.db.repositories import admin_panels as panels_repo
from bot.services.tg import is_not_modified, safe_delete, with_retry

logger = logging.getLogger(__name__)

_NO_PREVIEW = LinkPreviewOptions(is_disabled=True)


@dataclass(frozen=True)
class Media:
    file_id: str
    kind: ScreenshotKind


@dataclass(frozen=True)
class Screen:
    text: str
    markup: InlineKeyboardMarkup | None = None
    media: Media | None = None


def _input_media(screen: Screen) -> InputMediaPhoto | InputMediaDocument:
    assert screen.media is not None
    if screen.media.kind == ScreenshotKind.photo:
        return InputMediaPhoto(media=screen.media.file_id, caption=screen.text)
    return InputMediaDocument(media=screen.media.file_id, caption=screen.text)


async def _send(bot: Bot, chat_id: int, screen: Screen) -> Message:
    if screen.media is None:
        return await with_retry(
            lambda: bot.send_message(
                chat_id, screen.text, reply_markup=screen.markup, link_preview_options=_NO_PREVIEW
            )
        )
    if screen.media.kind == ScreenshotKind.photo:
        return await with_retry(
            lambda: bot.send_photo(chat_id, screen.media.file_id, caption=screen.text, reply_markup=screen.markup)
        )
    return await with_retry(
        lambda: bot.send_document(chat_id, screen.media.file_id, caption=screen.text, reply_markup=screen.markup)
    )


async def show(bot: Bot, session: AsyncSession, admin_id: int, screen: Screen, *, fresh: bool = False) -> None:
    """Display `screen` in the admin's panel, editing in place whenever Telegram allows.

    fresh=True always sends a new panel (and deletes the old one), e.g. for /admin.
    """
    panel = await panels_repo.get(session, admin_id)

    if panel is not None and not fresh:
        try:
            if screen.media is None and not panel.is_media:
                await with_retry(
                    lambda: bot.edit_message_text(
                        text=screen.text,
                        chat_id=panel.chat_id,
                        message_id=panel.message_id,
                        reply_markup=screen.markup,
                        link_preview_options=_NO_PREVIEW,
                    )
                )
                return
            if screen.media is not None and panel.is_media:
                await with_retry(
                    lambda: bot.edit_message_media(
                        media=_input_media(screen),
                        chat_id=panel.chat_id,
                        message_id=panel.message_id,
                        reply_markup=screen.markup,
                    )
                )
                return
        except TelegramBadRequest as exc:
            if is_not_modified(exc):
                return
            logger.info("Panel of admin %s could not be edited (%s); sending a new one", admin_id, exc.message)

    message = await _send(bot, admin_id, screen)
    if panel is not None and panel.message_id != message.message_id:
        await safe_delete(bot, panel.chat_id, panel.message_id)
    await panels_repo.upsert(
        session,
        admin_telegram_id=admin_id,
        chat_id=message.chat.id,
        message_id=message.message_id,
        is_media=screen.media is not None,
    )


async def set_markup(bot: Bot, session: AsyncSession, admin_id: int, markup: InlineKeyboardMarkup) -> None:
    """Swap only the keyboard (used by the "I'm sure / Cancel" confirmation steps)."""
    panel = await panels_repo.get(session, admin_id)
    if panel is None:
        return
    try:
        await with_retry(
            lambda: bot.edit_message_reply_markup(
                chat_id=panel.chat_id, message_id=panel.message_id, reply_markup=markup
            )
        )
    except TelegramBadRequest as exc:
        if not is_not_modified(exc):
            logger.info("Could not edit panel keyboard for admin %s: %s", admin_id, exc.message)


async def adopt(bot: Bot, session: AsyncSession, admin_id: int, message: Message) -> None:
    """Make `message` (e.g. a notice the admin tapped "Open" on) the admin's panel,
    deleting whatever panel they had before."""
    panel = await panels_repo.get(session, admin_id)
    if panel is not None and panel.message_id != message.message_id:
        await safe_delete(bot, panel.chat_id, panel.message_id)
    await panels_repo.upsert(
        session,
        admin_telegram_id=admin_id,
        chat_id=message.chat.id,
        message_id=message.message_id,
        is_media=bool(message.photo or message.document),
    )


async def remove(bot: Bot, session: AsyncSession, admin_id: int) -> None:
    panel = await panels_repo.get(session, admin_id)
    if panel is None:
        return
    await safe_delete(bot, panel.chat_id, panel.message_id)
    await panels_repo.delete(session, admin_id)
