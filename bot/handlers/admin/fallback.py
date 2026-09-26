from __future__ import annotations

from aiogram import Bot, Router
from aiogram.types import Message

from bot.services.tg import safe_delete

router = Router(name="admin.fallback")


@router.message()
async def delete_stray_admin_message(message: Message, bot: Bot) -> None:
    """Keep the admin chat clean: anything not handled above is removed."""
    await safe_delete(bot, message.chat.id, message.message_id)
