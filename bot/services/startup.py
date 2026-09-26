from __future__ import annotations

import logging

from aiogram import Bot
from aiogram.exceptions import TelegramAPIError
from aiogram.types import ChatMemberAdministrator, ChatMemberOwner
from aiogram.utils.i18n import gettext as _

from bot.config import get_settings
from bot.i18n import in_locale

logger = logging.getLogger(__name__)


async def check_channel_rights(bot: Bot) -> str | None:
    """Verify the bot is a channel admin allowed to invite users. Returns a problem
    description, or None if everything is fine."""
    settings = get_settings()
    try:
        me = await bot.get_me()
        member = await bot.get_chat_member(settings.channel_id, me.id)
    except TelegramAPIError as exc:
        return f"cannot access channel {settings.channel_id}: {exc.message}"

    if isinstance(member, ChatMemberOwner):
        return None
    if not isinstance(member, ChatMemberAdministrator):
        return f"the bot is not an administrator of channel {settings.channel_id}"
    if not member.can_invite_users:
        return f"the bot lacks the 'Invite users via link' right in channel {settings.channel_id}"
    return None


async def report_channel_problem(bot: Bot, problem: str) -> None:
    logger.error("CHANNEL SETUP PROBLEM: %s. Invite links will not work until this is fixed.", problem)
    with in_locale(None):
        text = _(
            "⚠️ Bot setup problem: {problem}.\n"
            "Add the bot to the channel as an administrator with the “Invite users via link” right."
        ).format(problem=problem)
    for admin_id in get_settings().admins:
        try:
            await bot.send_message(admin_id, text, parse_mode=None)
        except TelegramAPIError as exc:
            logger.warning("Could not notify admin %s about the channel problem: %s", admin_id, exc.message)
