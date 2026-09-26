"""Approve flow and invite-link actions on approved cards."""
from __future__ import annotations

import html
import logging
from datetime import timedelta

from aiogram import Bot, F, Router
from aiogram.exceptions import TelegramAPIError
from aiogram.types import CallbackQuery
from aiogram.utils.i18n import gettext as _
from sqlalchemy.ext.asyncio import AsyncSession

from bot.db.models import Client, ClientStatus, SubmissionStatus
from bot.db.repositories import clients as clients_repo
from bot.db.repositories import invite_links as invite_repo
from bot.db.repositories import submissions as submissions_repo
from bot.handlers.admin.card import processed_by_notice, show_card
from bot.keyboards.callbacks import CardCb
from bot.services import invite_links, panel, screens
from bot.services.debounce import mark_success, succeeded_recently, too_soon
from bot.services.notifications import send_to_client
from bot.services.timefmt import utcnow

logger = logging.getLogger(__name__)
router = Router(name="admin.approve")

# A second "Generate new link" within this window is treated as a double tap.
FRESH_LINK_WINDOW = timedelta(seconds=5)


async def _issue_and_send(
    callback: CallbackQuery, bot: Bot, session: AsyncSession, data: CardCb, client: Client, submission_id: int
) -> None:
    """Create the personal link, send it to the client, and show the outcome in the panel."""
    admin_id = callback.from_user.id
    try:
        invite = await invite_links.create_link(bot, session, client=client, submission_id=submission_id)
    except TelegramAPIError as exc:
        logger.exception("Invite link creation failed: client=%s admin=%s", client.id, admin_id)
        await send_to_client(
            bot,
            client,
            lambda: (_("⏳ Your payment has not been approved yet. Please wait — we'll notify you here."), None),
        )
        notice = _("⚠️ Could not create the invite link: {error}").format(
            error=html.escape(invite_links.link_generation_error(exc))
        )
        await show_card(callback, bot, session, data, notice=notice)
        return

    error = await invite_links.deliver_link(bot, session, client=client, invite=invite)
    latest = await submissions_repo.get_latest_for_client(session, client.id)
    screen = screens.approval_result(
        invite=invite,
        name=latest.full_name if latest else str(client.telegram_id),
        error=error,
        cid=client.id,
        sid=submission_id,
        src=data.src,
        page=data.p,
    )
    await panel.show(bot, session, admin_id, screen)


@router.callback_query(CardCb.filter(F.a == "apy"))
async def approve(callback: CallbackQuery, callback_data: CardCb, bot: Bot, session: AsyncSession) -> None:
    await callback.answer()
    admin = callback.from_user
    if too_soon(("apy", admin.id, callback_data.sid)):
        return

    ok = await submissions_repo.set_review_result(
        session,
        submission_id=callback_data.sid,
        client_id=callback_data.cid,
        new_status=SubmissionStatus.approved,
        admin_telegram_id=admin.id,
        admin_name=admin.full_name,
    )
    await session.commit()
    if not ok:
        submission = await submissions_repo.get_by_id(session, callback_data.sid)
        logger.info("Approve ignored (already processed): admin=%s submission=%s", admin.id, callback_data.sid)
        await show_card(callback, bot, session, callback_data, notice=processed_by_notice(submission))
        return

    logger.info(
        "Admin action: approve admin=%s client=%s submission=%s", admin.id, callback_data.cid, callback_data.sid
    )
    client = await clients_repo.get_by_id(session, callback_data.cid)
    await _issue_and_send(callback, bot, session, callback_data, client, callback_data.sid)


@router.callback_query(CardCb.filter(F.a == "rgen"))
async def retry_generate(callback: CallbackQuery, callback_data: CardCb, bot: Bot, session: AsyncSession) -> None:
    """Approved client whose link could not be created earlier: create and send it now."""
    await callback.answer()
    client = await clients_repo.get_by_id(session, callback_data.cid)
    already_has_link = client is not None and await invite_repo.get_current_for_client(session, client.id)
    if client is None or client.status != ClientStatus.approved or already_has_link:
        # e.g. a double tap: the first tap already created (and sent) the link
        await show_card(callback, bot, session, callback_data)
        return
    logger.info("Admin action: retry link generation admin=%s client=%s", callback.from_user.id, client.id)
    await _issue_and_send(callback, bot, session, callback_data, client, callback_data.sid)


@router.callback_query(CardCb.filter(F.a == "gen"))
async def generate_new_link(callback: CallbackQuery, callback_data: CardCb, bot: Bot, session: AsyncSession) -> None:
    """Replace the client's link (revoking the old one) and refresh the card in place.
    No confirmation: the client is already approved. Delivery is a separate button."""
    await callback.answer()
    client = await clients_repo.get_by_id(session, callback_data.cid)
    if client is None or client.status != ClientStatus.approved:
        await show_card(callback, bot, session, callback_data)
        return

    active = await invite_repo.get_active_for_client(session, client.id)
    if active is not None and utcnow() - active.created_at < FRESH_LINK_WINDOW:
        return  # double tap: the link was minted a moment ago

    try:
        await invite_links.create_link(bot, session, client=client, submission_id=callback_data.sid)
    except TelegramAPIError as exc:
        logger.exception("New link generation failed: client=%s admin=%s", client.id, callback.from_user.id)
        notice = _("⚠️ Could not create the invite link: {error}").format(
            error=html.escape(invite_links.link_generation_error(exc))
        )
        await show_card(callback, bot, session, callback_data, notice=notice)
        return
    logger.info("Admin action: new link admin=%s client=%s", callback.from_user.id, client.id)
    await show_card(callback, bot, session, callback_data)


@router.callback_query(CardCb.filter(F.a == "rs"))
async def resend_link(callback: CallbackQuery, callback_data: CardCb, bot: Bot, session: AsyncSession) -> None:
    client = await clients_repo.get_by_id(session, callback_data.cid)
    invite = await invite_repo.get_active_for_client(session, callback_data.cid) if client else None
    if client is None or invite is None:
        await callback.answer(_("There is no active link. Generate a new one first."), show_alert=True)
        return
    await callback.answer()
    key = ("rs", invite.id)
    if succeeded_recently(key):
        return

    error = await invite_links.deliver_link(bot, session, client=client, invite=invite)
    if error is None:
        mark_success(key)
    logger.info(
        "Admin action: resend link admin=%s client=%s link_id=%s ok=%s",
        callback.from_user.id, client.id, invite.id, error is None,
    )
    if error is None:
        notice = _("📤 The link was sent to the user.")
    else:
        notice = _("⚠️ Could not send the link: {error}").format(error=html.escape(error))
    await show_card(callback, bot, session, callback_data, notice=notice)
