from __future__ import annotations

import logging

from aiogram import Bot, F, Router
from aiogram.fsm.context import FSMContext
from aiogram.types import CallbackQuery, Message
from sqlalchemy.ext.asyncio import AsyncSession

from bot.keyboards.callbacks import MenuCb, SearchCb
from bot.services import panel, screens
from bot.services.tg import safe_delete
from bot.states import AdminInput

logger = logging.getLogger(__name__)
router = Router(name="admin.search")

MIN_QUERY = 2


async def _ask(callback: CallbackQuery, bot: Bot, session: AsyncSession, state: FSMContext) -> None:
    await state.set_state(AdminInput.search_query)
    await panel.show(bot, session, callback.from_user.id, screens.search_prompt())


@router.callback_query(MenuCb.filter(F.a == "search"))
async def start_search(callback: CallbackQuery, bot: Bot, session: AsyncSession, state: FSMContext) -> None:
    await callback.answer()
    await _ask(callback, bot, session, state)


@router.callback_query(SearchCb.filter(F.a == "again"))
async def search_again(callback: CallbackQuery, bot: Bot, session: AsyncSession, state: FSMContext) -> None:
    await callback.answer()
    await _ask(callback, bot, session, state)


@router.callback_query(SearchCb.filter(F.a == "cancel"))
async def cancel_search(callback: CallbackQuery, bot: Bot, session: AsyncSession, state: FSMContext) -> None:
    await callback.answer()
    await state.set_state(None)
    await panel.show(bot, session, callback.from_user.id, await screens.main_menu(session))


@router.callback_query(SearchCb.filter(F.a == "page"))
async def results_page(
    callback: CallbackQuery, callback_data: SearchCb, bot: Bot, session: AsyncSession, state: FSMContext
) -> None:
    await callback.answer()
    query = (await state.get_data()).get("search_query")
    if not query:
        await _ask(callback, bot, session, state)
        return
    await panel.show(bot, session, callback.from_user.id, await screens.search_results(session, query, callback_data.p))


@router.message(AdminInput.search_query)
async def on_query(message: Message, bot: Bot, session: AsyncSession, state: FSMContext) -> None:
    await safe_delete(bot, message.chat.id, message.message_id)
    query = (message.text or "").strip()
    if len(query.lstrip("@")) < MIN_QUERY:
        await panel.show(bot, session, message.from_user.id, screens.search_prompt(too_short=True))
        return
    await state.update_data(search_query=query)
    await state.set_state(None)
    logger.info("Admin %s searched for %r", message.from_user.id, query)
    await panel.show(bot, session, message.from_user.id, await screens.search_results(session, query, 1))
