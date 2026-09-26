"""Opening the panel, main menu, settings, and "Open" on admin notices."""
from __future__ import annotations

import logging

from aiogram import Bot, F, Router
from aiogram.filters import Command
from aiogram.fsm.context import FSMContext
from aiogram.types import CallbackQuery, Message
from aiogram.utils.i18n import gettext as _
from sqlalchemy.ext.asyncio import AsyncSession

from bot.db.repositories import clients as clients_repo
from bot.filters.is_admin import ButtonText
from bot.keyboards.callbacks import MenuCb, NoticeCb
from bot.keyboards.reply import BTN_ADMIN_PANEL, BTN_SETTINGS
from bot.services import panel, screens
from bot.services.tg import safe_delete

logger = logging.getLogger(__name__)
router = Router(name="admin.menu")


@router.message(Command("admin"))
@router.message(ButtonText(BTN_ADMIN_PANEL))
async def open_panel(message: Message, bot: Bot, session: AsyncSession, state: FSMContext) -> None:
    await safe_delete(bot, message.chat.id, message.message_id)
    await state.set_state(None)
    await panel.show(bot, session, message.from_user.id, await screens.main_menu(session), fresh=True)


@router.message(ButtonText(BTN_SETTINGS))
async def open_settings(message: Message, bot: Bot, session: AsyncSession, state: FSMContext) -> None:
    await safe_delete(bot, message.chat.id, message.message_id)
    await state.set_state(None)
    await panel.show(bot, session, message.from_user.id, screens.settings_screen())


@router.callback_query(MenuCb.filter(F.a == "home"))
async def home(callback: CallbackQuery, bot: Bot, session: AsyncSession) -> None:
    await callback.answer()
    await panel.show(bot, session, callback.from_user.id, await screens.main_menu(session))


@router.callback_query(MenuCb.filter(F.a == "settings"))
async def settings(callback: CallbackQuery, bot: Bot, session: AsyncSession) -> None:
    await callback.answer()
    await panel.show(bot, session, callback.from_user.id, screens.settings_screen())


@router.callback_query(NoticeCb.filter())
async def open_notice(callback: CallbackQuery, callback_data: NoticeCb, bot: Bot, session: AsyncSession) -> None:
    """The tapped notice becomes this admin's panel; the previous panel is deleted."""
    await callback.answer()
    admin_id = callback.from_user.id
    client = await clients_repo.get_by_id(session, callback_data.cid)
    await panel.adopt(bot, session, admin_id, callback.message)
    if client is None:
        await panel.show(bot, session, admin_id, await screens.main_menu(session, notice=_("Client not found.")))
        return
    screen = await screens.client_card(session, client.id, screens.status_code(client.status), 1)
    if screen is None:
        screen = await screens.main_menu(session, notice=_("Client not found."))
    await panel.show(bot, session, admin_id, screen)
    logger.info("Admin %s opened notice for client %s", admin_id, client.id)
