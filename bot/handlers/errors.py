from __future__ import annotations

import logging

from aiogram import Router
from aiogram.exceptions import TelegramAPIError
from aiogram.types import ErrorEvent

logger = logging.getLogger(__name__)
router = Router(name="errors")


@router.errors()
async def on_error(event: ErrorEvent) -> bool:
    """Log every unhandled error with its traceback and keep polling alive."""
    logger.error(
        "Unhandled error while processing update %s", event.update.update_id, exc_info=event.exception
    )
    callback = event.update.callback_query
    if callback is not None:
        try:
            await callback.answer()  # stop the button's loading spinner
        except TelegramAPIError:
            pass
    return True
