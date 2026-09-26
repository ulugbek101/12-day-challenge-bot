from __future__ import annotations

from typing import Any

from aiogram.types import TelegramObject
from aiogram.utils.i18n import I18nMiddleware

from bot.db.models import Client


class DbI18nMiddleware(I18nMiddleware):
    """Locale comes from clients.language; before a language is chosen, the default."""

    async def get_locale(self, event: TelegramObject, data: dict[str, Any]) -> str:
        client: Client | None = data.get("client")
        if client is not None and client.language is not None:
            return client.language.value
        return self.i18n.default_locale
