from __future__ import annotations

from aiogram import Router

from bot.handlers import channel, common, errors
from bot.handlers.admin import build_admin_router
from bot.handlers.user import submission


def setup_routers() -> Router:
    """Order matters: common (/start, language) for everyone, then the admin router
    (IsAdmin-filtered, ends in a catch-all), then the client flow (also ends in one)."""
    root = Router(name="root")
    root.include_routers(
        errors.router,
        channel.router,
        common.router,
        build_admin_router(),
        submission.router,
    )
    return root
