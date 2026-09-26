from __future__ import annotations

from collections.abc import Awaitable, Callable
from typing import Any

from aiogram import BaseMiddleware, Router
from aiogram.fsm.context import FSMContext
from aiogram.types import TelegramObject

from bot.filters.is_admin import IsAdmin
from bot.handlers.admin import approve, card, fallback, history, lists, menu, reject, search
from bot.states import AdminInput

_INPUT_STATES = {AdminInput.search_query.state, AdminInput.reject_reason.state}


class CancelPendingInputMiddleware(BaseMiddleware):
    """Any panel button press abandons a half-finished text input (search query or
    rejection reason), so a later stray message isn't mistaken for it."""

    async def __call__(
        self,
        handler: Callable[[TelegramObject, dict[str, Any]], Awaitable[Any]],
        event: TelegramObject,
        data: dict[str, Any],
    ) -> Any:
        state: FSMContext | None = data.get("state")
        if state is not None and await state.get_state() in _INPUT_STATES:
            await state.set_state(None)
        return await handler(event, data)


def build_admin_router() -> Router:
    router = Router(name="admin")
    router.message.filter(IsAdmin())
    router.callback_query.filter(IsAdmin())
    # Registered as an *inner* middleware on each child so it only runs for admins
    # (after the IsAdmin root filter), never for clients mid-form.
    for child in (menu, lists, search, card, history, approve, reject):
        child.router.callback_query.middleware(CancelPendingInputMiddleware())
        router.include_router(child.router)
    router.include_router(fallback.router)  # must stay last: deletes unhandled admin messages
    return router
