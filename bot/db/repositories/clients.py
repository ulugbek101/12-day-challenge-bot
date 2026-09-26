from __future__ import annotations

from sqlalchemy import func, select
from sqlalchemy.ext.asyncio import AsyncSession

from bot.db.models import Client, ClientStatus, Language
from bot.services.timefmt import utcnow


async def get_by_telegram_id(session: AsyncSession, telegram_id: int) -> Client | None:
    stmt = select(Client).where(Client.telegram_id == telegram_id)
    return (await session.execute(stmt)).scalar_one_or_none()


async def get_by_id(session: AsyncSession, client_id: int) -> Client | None:
    return await session.get(Client, client_id)


async def get_or_create(
    session: AsyncSession, telegram_id: int, username: str | None
) -> tuple[Client, bool]:
    """Fetch a client by telegram_id, creating one (language unset) if absent.

    Also keeps `username` fresh on every call, since Telegram usernames can change.
    """
    client = await get_by_telegram_id(session, telegram_id)
    now = utcnow()
    if client is None:
        client = Client(
            telegram_id=telegram_id,
            username=username,
            language=None,
            status=ClientStatus.none,
            created_at=now,
            updated_at=now,
        )
        session.add(client)
        await session.flush()
        return client, True

    if client.username != username:
        client.username = username
        client.updated_at = now
    return client, False


async def set_language(session: AsyncSession, client_id: int, language: Language) -> None:
    client = await session.get(Client, client_id)
    if client is None:
        return
    client.language = language
    client.updated_at = utcnow()


async def set_status(session: AsyncSession, client_id: int, status: ClientStatus) -> None:
    client = await session.get(Client, client_id)
    if client is None:
        return
    client.status = status
    client.updated_at = utcnow()


async def set_joined(session: AsyncSession, client_id: int) -> None:
    client = await session.get(Client, client_id)
    if client is None:
        return
    client.joined_at = utcnow()
    client.updated_at = utcnow()


async def count_by_status(session: AsyncSession, status: ClientStatus) -> int:
    stmt = select(func.count()).select_from(Client).where(Client.status == status)
    return (await session.execute(stmt)).scalar_one()
