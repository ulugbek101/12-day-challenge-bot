from __future__ import annotations

from collections.abc import Awaitable, Callable
from typing import Any

from aiogram import BaseMiddleware
from aiogram.types import Chat, TelegramObject, User
from sqlalchemy.ext.asyncio import AsyncSession, async_sessionmaker

from bot.db.repositories import clients as clients_repo


class DbSessionMiddleware(BaseMiddleware):
    """One session per update: committed if the handler succeeds, rolled back otherwise."""

    def __init__(self, session_factory: async_sessionmaker[AsyncSession]) -> None:
        self.session_factory = session_factory

    async def __call__(
        self,
        handler: Callable[[TelegramObject, dict[str, Any]], Awaitable[Any]],
        event: TelegramObject,
        data: dict[str, Any],
    ) -> Any:
        async with self.session_factory() as session:
            data["session"] = session
            try:
                result = await handler(event, data)
            except Exception:
                await session.rollback()
                raise
            await session.commit()
            return result


class ClientMiddleware(BaseMiddleware):
    """Loads (or creates, for private chats) the sender's clients row into data["client"].

    Runs before i18n so the user's saved language is known. Channel join requests
    come from arbitrary people and never create rows here.
    """

    async def __call__(
        self,
        handler: Callable[[TelegramObject, dict[str, Any]], Awaitable[Any]],
        event: TelegramObject,
        data: dict[str, Any],
    ) -> Any:
        user: User | None = data.get("event_from_user")
        chat: Chat | None = data.get("event_chat")
        session: AsyncSession = data["session"]

        client = None
        if user is not None and not user.is_bot:
            if chat is None or chat.type == "private":
                client, _ = await clients_repo.get_or_create(session, user.id, user.username)
            else:
                client = await clients_repo.get_by_telegram_id(session, user.id)
        data["client"] = client
        return await handler(event, data)
