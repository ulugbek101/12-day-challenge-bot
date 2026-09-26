"""Background loop: expiry reminders to clients and expired-link notices to admins.

Plain asyncio task (no scheduler dependency), checking the DB every 5 minutes.
"""
from __future__ import annotations

import asyncio
import contextlib
import html
import logging

from aiogram import Bot
from aiogram.utils.i18n import gettext as _
from sqlalchemy.ext.asyncio import AsyncSession, async_sessionmaker

from bot.config import get_settings
from bot.db.repositories import clients as clients_repo
from bot.db.repositories import invite_links as invite_repo
from bot.db.repositories import submissions as submissions_repo
from bot.services.notifications import notify_admins, send_to_client
from bot.services.timefmt import to_display

logger = logging.getLogger(__name__)

CHECK_INTERVAL_SECONDS = 300


async def send_due_reminders(bot: Bot, session: AsyncSession) -> int:
    """One reminder per link, ever. reminded_at is committed *before* sending, so a
    crash or restart mid-send can never produce a second reminder (and, per spec,
    a failed reminder is not retried)."""
    settings = get_settings()
    due = await invite_repo.list_due_for_reminder(session, within_hours=settings.reminder_before_expiry_hours)
    sent = 0
    for invite in due:
        await invite_repo.mark_reminded(session, invite.id)
        await session.commit()

        client = await clients_repo.get_by_id(session, invite.client_id)
        if client is None:
            continue

        def build(invite=invite):  # noqa: ANN001, ANN202
            text = _(
                "⏰ Reminder: your personal invite link expires at {expires}.\n"
                "Please join the channel before then:\n<pre>{link}</pre>"
            ).format(expires=to_display(invite.expires_at, settings.tz), link=html.escape(invite.link))
            return text, None

        error = await send_to_client(bot, client, build)
        if error is None:
            sent += 1
            logger.info("Expiry reminder sent: link_id=%s client=%s", invite.id, client.id)
        else:
            logger.warning("Expiry reminder failed: link_id=%s client=%s reason=%s", invite.id, client.id, error)
    return sent


async def notify_expired_links(bot: Bot, session: AsyncSession) -> int:
    """Tell admins about links that expired unused. Marked done once at least one admin
    got the notice; if every admin delivery failed, it's retried on the next loop."""
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
            logger.warning("Expired-link notice not delivered to any admin, will retry: link_id=%s", invite.id)
    return notified


async def run_once(bot: Bot, session_factory: async_sessionmaker[AsyncSession]) -> None:
    async with session_factory() as session:
        await send_due_reminders(bot, session)
    async with session_factory() as session:
        await notify_expired_links(bot, session)


async def reminder_loop(bot: Bot, session_factory: async_sessionmaker[AsyncSession]) -> None:
    logger.info("Reminder loop started (every %s s)", CHECK_INTERVAL_SECONDS)
    while True:
        try:
            await run_once(bot, session_factory)
        except asyncio.CancelledError:
            raise
        except Exception:
            logger.exception("Reminder loop iteration failed")
        await asyncio.sleep(CHECK_INTERVAL_SECONDS)


async def stop(task: asyncio.Task[None] | None) -> None:
    if task is None:
        return
    task.cancel()
    with contextlib.suppress(asyncio.CancelledError):
        await task
    logger.info("Reminder loop stopped")
