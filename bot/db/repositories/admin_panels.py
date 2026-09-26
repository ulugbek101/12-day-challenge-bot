from __future__ import annotations

from sqlalchemy.ext.asyncio import AsyncSession

from bot.db.models import AdminPanel
from bot.services.timefmt import utcnow


async def get(session: AsyncSession, admin_telegram_id: int) -> AdminPanel | None:
    return await session.get(AdminPanel, admin_telegram_id)


async def upsert(
    session: AsyncSession,
    *,
    admin_telegram_id: int,
    chat_id: int,
    message_id: int,
    is_media: bool,
) -> None:
    panel = await session.get(AdminPanel, admin_telegram_id)
    if panel is None:
        session.add(
            AdminPanel(
                admin_telegram_id=admin_telegram_id,
                chat_id=chat_id,
                message_id=message_id,
                is_media=is_media,
                updated_at=utcnow(),
            )
        )
    else:
        panel.chat_id = chat_id
        panel.message_id = message_id
        panel.is_media = is_media
        panel.updated_at = utcnow()


async def delete(session: AsyncSession, admin_telegram_id: int) -> None:
    panel = await session.get(AdminPanel, admin_telegram_id)
    if panel is not None:
        await session.delete(panel)
