"""Background loop: tells admins when a personal link expires without being used.

Clients are deliberately NOT reminded to join; using the link in time is their
responsibility. Admins get a notice so they can issue a new link from the card
if the client asks. Plain asyncio task (no scheduler dependency), every 5 minutes.
"""
from __future__ import annotations

import asyncio
import contextlib
import html
import logging

from aiogram import Bot
from aiogram.utils.i18n import gettext as _
from sqlalchemy.ext.asyncio import AsyncSession, async_sessionmaker

from bot.db.repositories import invite_links as invite_repo
from bot.db.repositories import submissions as submissions_repo
from bot.services.notifications import notify_admins

logger = logging.getLogger(__name__)

CHECK_INTERVAL_SECONDS = 300


async def notify_expired_links(bot: Bot, session: AsyncSession) -> int:
    """Notify admins about links that expired unused. Marked done once at least one
    admin got the notice; if every admin delivery failed, it's retried next loop."""
    notified = 0
    for invite in await invite_repo.list_newly_expired(session):
        submission = await submissions_repo.get_latest_for_client(session, invite.client_id)
        name = submission.full_name if submission else f"#{invite.client_id}"

        delivered = await notify_admins(
            bot,
            session,
            client_id=invite.client_id,
            build=lambda name=name: _("⌛ {name}'s link expired without joining").format(name=html.escape(name)),
        )
        if delivered:
            await invite_repo.mark_expired_notified(session, invite.id)
            await session.commit()
            notified += 1
            logger.info("Expired-link notice sent: link_id=%s client=%s", invite.id, invite.client_id)
        else:
            logger.warning("Expired-link notice reached no admin, will retry: link_id=%s", invite.id)
    return notified


async def run_once(bot: Bot, session_factory: async_sessionmaker[AsyncSession]) -> None:
    async with session_factory() as session:
        await notify_expired_links(bot, session)


async def expiry_loop(bot: Bot, session_factory: async_sessionmaker[AsyncSession]) -> None:
    logger.info("Link-expiry loop started (every %s s)", CHECK_INTERVAL_SECONDS)
    while True:
        try:
            await run_once(bot, session_factory)
        except asyncio.CancelledError:
            raise
        except Exception:
            logger.exception("Link-expiry loop iteration failed")
        await asyncio.sleep(CHECK_INTERVAL_SECONDS)


async def stop(task: asyncio.Task[None] | None) -> None:
    if task is None:
        return
    task.cancel()
    with contextlib.suppress(asyncio.CancelledError):
        await task
    logger.info("Link-expiry loop stopped")
