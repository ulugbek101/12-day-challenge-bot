from __future__ import annotations

from aiogram import Bot, Router
from aiogram.types import CallbackQuery
from sqlalchemy.ext.asyncio import AsyncSession

from bot.keyboards.callbacks import ListCb
from bot.services import panel, screens

router = Router(name="admin.lists")


@router.callback_query(ListCb.filter())
async def show_list(callback: CallbackQuery, callback_data: ListCb, bot: Bot, session: AsyncSession) -> None:
    await callback.answer()
    if callback_data.st not in screens.STATUS_BY_CODE:
        return
    screen = await screens.status_list(session, callback_data.st, callback_data.p)
    await panel.show(bot, session, callback.from_user.id, screen)
