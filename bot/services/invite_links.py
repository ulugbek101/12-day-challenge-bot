"""Personal invite links: create (revoking the previous one), deliver, revoke.

Links are created with creates_join_request=True, so clicking one only files a
join request; bot/handlers/channel.py then approves it only for the client the
link was issued to. member_limit can't be combined with join requests, and
wouldn't stop a stranger who clicks first anyway.
"""
from __future__ import annotations

import asyncio
import html
import logging
from collections import defaultdict
from datetime import timedelta, timezone

from aiogram import Bot
from aiogram.exceptions import TelegramAPIError, TelegramBadRequest
from aiogram.utils.i18n import gettext as _
from sqlalchemy import select
from sqlalchemy.ext.asyncio import AsyncSession

from bot.config import get_settings
from bot.db.models import Client, InviteLink
from bot.db.repositories import invite_links as invite_repo
from bot.services.notifications import send_to_client
from bot.services.timefmt import to_display, utcnow
from bot.services.tg import with_retry

logger = logging.getLogger(__name__)

# One bot container only (polling), so an in-process lock per client is enough
# to stop two admins (or a double tap) from minting two links at once.
_client_locks: defaultdict[int, asyncio.Lock] = defaultdict(asyncio.Lock)


def link_name(client_id: int, submission_id: int) -> str:
    return f"c{client_id}s{submission_id}"


async def revoke_open_links(bot: Bot, session: AsyncSession, client_id: int) -> None:
    """Revoke every link of this client that hasn't been used or revoked yet."""
    settings = get_settings()
    now = utcnow()
    stmt = select(InviteLink).where(
        InviteLink.client_id == client_id,
        InviteLink.revoked_at.is_(None),
        InviteLink.used_at.is_(None),
    )
    for invite in (await session.execute(stmt)).scalars():
        if invite.expires_at > now:
            try:
                await with_retry(
                    lambda: bot.revoke_chat_invite_link(chat_id=settings.channel_id, invite_link=invite.link)
                )
            except TelegramBadRequest as exc:
                logger.warning("Telegram refused to revoke link %s: %s", invite.id, exc.message)
        invite.revoked_at = now
        logger.info("Invite link revoked: link_id=%s client=%s", invite.id, client_id)


async def create_link(bot: Bot, session: AsyncSession, *, client: Client, submission_id: int) -> InviteLink:
    """Revoke the previous link(s) and mint a new personal link. Commits.

    Raises TelegramAPIError if Telegram refuses (e.g. the bot lost its admin rights).
    """
    settings = get_settings()
    async with _client_locks[client.id]:
        await revoke_open_links(bot, session, client.id)
        expires_at = utcnow() + timedelta(hours=settings.invite_link_ttl_hours)
        name = link_name(client.id, submission_id)
        created = await with_retry(
            lambda: bot.create_chat_invite_link(
                chat_id=settings.channel_id,
                name=name,
                creates_join_request=True,
                expire_date=expires_at.replace(tzinfo=timezone.utc),
            )
        )
        invite = await invite_repo.create(
            session,
            client_id=client.id,
            submission_id=submission_id,
            link=created.invite_link,
            name=name,
            expires_at=expires_at,
        )
        await session.commit()
    logger.info(
        "Invite link created: link_id=%s client=%s submission=%s expires_at=%sZ",
        invite.id, client.id, submission_id, expires_at.isoformat(timespec="seconds"),
    )
    return invite


async def deliver_link(bot: Bot, session: AsyncSession, *, client: Client, invite: InviteLink) -> str | None:
    """Send the client their link. Records the outcome on the invite row and commits.

    Returns None on success, or the delivery error (e.g. "bot was blocked by the user").
    """
    tz = get_settings().tz

    def build():  # noqa: ANN202
        text = _(
            "🎉 Congratulations! Your payment has been approved.\n\n"
            "Here is your personal invite link. It works only for your Telegram account "
            "and is valid until {expires}:\n<pre>{link}</pre>\n"
            "Open it and tap “Request to join” — the bot will let you in automatically."
        ).format(expires=to_display(invite.expires_at, tz), link=html.escape(invite.link))
        return text, None

    error = await send_to_client(bot, client, build)
    await invite_repo.mark_send_result(session, invite.id, success=error is None, error=error)
    await session.commit()
    if error is None:
        logger.info("Invite link delivered: link_id=%s client=%s", invite.id, client.id)
    else:
        logger.warning("Invite link NOT delivered: link_id=%s client=%s reason=%s", invite.id, client.id, error)
    return error


def link_generation_error(exc: TelegramAPIError) -> str:
    return exc.message[:300]
