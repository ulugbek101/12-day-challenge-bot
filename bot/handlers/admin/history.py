from __future__ import annotations

from aiogram import Bot, Router
from aiogram.types import CallbackQuery
from aiogram.utils.i18n import gettext as _
from sqlalchemy.ext.asyncio import AsyncSession

from bot.keyboards.callbacks import HistCb
from bot.services import panel, screens

router = Router(name="admin.history")


@router.callback_query(HistCb.filter())
async def show_history(callback: CallbackQuery, callback_data: HistCb, bot: Bot, session: AsyncSession) -> None:
    screen = await screens.history(session, callback_data.cid, callback_data.i, callback_data.src, callback_data.p)
    if screen is None:
        await callback.answer(_("Client not found."), show_alert=True)
        return
    await callback.answer()
    await panel.show(bot, session, callback.from_user.id, screen)
