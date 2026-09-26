"""/start, first-time language choice and language changes (users and admins)."""
from __future__ import annotations

import logging

from aiogram import Bot, Router
from aiogram.filters import CommandStart
from aiogram.fsm.context import FSMContext
from aiogram.types import CallbackQuery, Message
from aiogram.utils.i18n import gettext as _
from sqlalchemy.ext.asyncio import AsyncSession

from bot.config import get_settings
from bot.db.models import Client, Language
from bot.db.repositories import clients as clients_repo
from bot.handlers.user.submission import start_submission
from bot.i18n import in_locale
from bot.keyboards.callbacks import LangCb
from bot.keyboards.reply import main_keyboard
from bot.keyboards.user import language_keyboard
from bot.services import panel, screens
from bot.services.tg import safe_delete

logger = logging.getLogger(__name__)
router = Router(name="common")

LANGUAGE_PROMPT = "🌐 Выберите язык\n🌐 Tilni tanlang"  # shown before any language exists


def is_admin(user_id: int) -> bool:
    return user_id in get_settings().admins


@router.message(CommandStart())
async def cmd_start(message: Message, bot: Bot, session: AsyncSession, client: Client, state: FSMContext) -> None:
    admin = is_admin(message.from_user.id)
    await state.clear()
    if client.language is None:
        await message.answer(LANGUAGE_PROMPT, reply_markup=language_keyboard("s"))
        return

    if admin:
        await safe_delete(bot, message.chat.id, message.message_id)
        await message.answer(_("👋 Welcome, admin!"), reply_markup=main_keyboard(is_admin=True))
        await panel.show(bot, session, message.from_user.id, await screens.main_menu(session), fresh=True)
        return

    await message.answer(
        _("👋 Welcome! Use the buttons below to submit your payment or change the language."),
        reply_markup=main_keyboard(is_admin=False),
    )


@router.callback_query(LangCb.filter())
async def on_language(
    callback: CallbackQuery,
    callback_data: LangCb,
    bot: Bot,
    session: AsyncSession,
    client: Client,
    state: FSMContext,
) -> None:
    await callback.answer()
    language = Language(callback_data.lang)
    await clients_repo.set_language(session, client.id, language)
    client.language = language
    admin = is_admin(callback.from_user.id)
    logger.info("Language set: user=%s lang=%s ctx=%s", callback.from_user.id, language.value, callback_data.ctx)

    # The i18n middleware already picked the *old* locale for this update; switch now.
    with in_locale(language.value):
        if callback_data.ctx == "a" and admin:
            await callback.message.answer(_("✅ Language changed."), reply_markup=main_keyboard(is_admin=True))
            await panel.show(bot, session, callback.from_user.id, await screens.main_menu(session))
            return

        if callback_data.ctx == "u":
            await safe_delete(bot, callback.message.chat.id, callback.message.message_id)
            await callback.message.answer(_("✅ Language changed."), reply_markup=main_keyboard(is_admin=admin))
            return

        # First /start: the picker is no longer needed.
        await safe_delete(bot, callback.message.chat.id, callback.message.message_id)
        if admin:
            await callback.message.answer(_("👋 Welcome, admin!"), reply_markup=main_keyboard(is_admin=True))
            await panel.show(bot, session, callback.from_user.id, await screens.main_menu(session), fresh=True)
            return

        await callback.message.answer(
            _("👋 Welcome! Here you can submit your payment to get access to the channel."),
            reply_markup=main_keyboard(is_admin=False),
        )
        await start_submission(bot, session, client, callback.message.chat.id, state)
