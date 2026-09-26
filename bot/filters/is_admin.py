from __future__ import annotations

from aiogram.filters import BaseFilter
from aiogram.types import Message, TelegramObject, User

from bot.config import get_settings
from bot.i18n import all_translations


class IsAdmin(BaseFilter):
    async def __call__(self, event: TelegramObject, event_from_user: User | None = None) -> bool:
        return event_from_user is not None and event_from_user.id in get_settings().admins


class ButtonText(BaseFilter):
    """Matches a reply-keyboard tap by label, in any supported language."""

    def __init__(self, msgid: str) -> None:
        self.msgid = msgid

    async def __call__(self, message: Message) -> bool:
        return message.text is not None and message.text in all_translations(self.msgid)
