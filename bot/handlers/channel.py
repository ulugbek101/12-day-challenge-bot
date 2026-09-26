"""chat_join_request: admit only the client a personal link was issued to."""
from __future__ import annotations

import html
import logging

from aiogram import Bot, Router
from aiogram.exceptions import TelegramAPIError, TelegramBadRequest
from aiogram.types import ChatJoinRequest
from aiogram.utils.i18n import gettext as _
from sqlalchemy.ext.asyncio import AsyncSession

from bot.config import get_settings
from bot.db.repositories import clients as clients_repo
from bot.db.repositories import invite_links as invite_repo
from bot.db.repositories import submissions as submissions_repo
from bot.services.join_requests import JoinAction, decide
from bot.services.notifications import notify_admins
from bot.services.timefmt import utcnow
from bot.services.tg import with_retry

logger = logging.getLogger(__name__)
router = Router(name="channel")


@router.chat_join_request()
async def on_join_request(request: ChatJoinRequest, bot: Bot, session: AsyncSession) -> None:
    settings = get_settings()
    requester = request.from_user
    if request.chat.id != settings.channel_id:
        logger.info("Ignoring join request for unrelated chat %s from %s", request.chat.id, requester.id)
        return

    link = request.invite_link.invite_link if request.invite_link else None
    invite = await invite_repo.get_by_link(session, link) if link else None
    client = await clients_repo.get_by_id(session, invite.client_id) if invite else None

    decision = decide(
        invite=invite,
        client_status=client.status if client else None,
        client_telegram_id=client.telegram_id if client else None,
        requester_telegram_id=requester.id,
        now=utcnow(),
    )

    if decision.action == JoinAction.decline:
        try:
            await with_retry(lambda: bot.decline_chat_join_request(chat_id=request.chat.id, user_id=requester.id))
        except TelegramBadRequest:
            logger.warning("Could not decline join request of %s", requester.id, exc_info=True)
        logger.info(
            "Join request DECLINED: requester=%s link_id=%s reason=%s",
            requester.id, invite.id if invite else None, decision.reason,
        )
        return

    try:
        await with_retry(lambda: bot.approve_chat_join_request(chat_id=request.chat.id, user_id=requester.id))
    except TelegramBadRequest:
        logger.warning("Could not approve join request of %s", requester.id, exc_info=True)
        return

    await invite_repo.mark_used(session, invite.id)
    await clients_repo.set_joined(session, client.id)
    await session.commit()
    logger.info("Join request APPROVED: requester=%s client=%s link_id=%s", requester.id, client.id, invite.id)

    # The link has done its job; make sure nobody else can even file a request with it.
    try:
        await with_retry(lambda: bot.revoke_chat_invite_link(chat_id=settings.channel_id, invite_link=invite.link))
        invite.revoked_at = utcnow()
        await session.commit()
        logger.info("Invite link revoked after use: link_id=%s", invite.id)
    except TelegramAPIError:
        logger.warning("Could not revoke used link %s", invite.id, exc_info=True)

    latest = await submissions_repo.get_latest_for_client(session, client.id)
    name = latest.full_name if latest else str(client.telegram_id)
    await notify_admins(
        bot,
        session,
        client_id=client.id,
        build=lambda: _("🎉 {name} joined the channel").format(name=html.escape(name)),
    )
