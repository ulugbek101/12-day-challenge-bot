"""Reject flow: confirm -> reason (text/photo/document/voice) -> copy to the client.

The reason is relayed with copy_message (Telegram's "forward without sender"),
never forward_message, so the client doesn't see the admin's name or profile.
The admin's reason message is kept; the bot replies to it with the delivery
status and, on failure, a retry button that can be pressed until it succeeds.
Rejection reasons are never stored in the database.
"""
from __future__ import annotations

import html
import logging

from aiogram import Bot, F, Router
from aiogram.exceptions import TelegramAPIError, TelegramBadRequest
from aiogram.fsm.context import FSMContext
from aiogram.types import CallbackQuery, Message
from aiogram.utils.i18n import gettext as _
from sqlalchemy.ext.asyncio import AsyncSession

from bot.db.models import Client, SubmissionStatus
from bot.db.repositories import clients as clients_repo
from bot.db.repositories import submissions as submissions_repo
from bot.handlers.admin.card import processed_by_notice, show_card, still_pending
from bot.i18n import in_locale
from bot.keyboards import admin as kb
from bot.keyboards.callbacks import CardCb, RetryReasonCb
from bot.keyboards.user import submit_again_keyboard
from bot.services import panel, screens
from bot.services.debounce import too_soon
from bot.services.notifications import client_locale
from bot.services.tg import describe_error, safe_delete, with_retry
from bot.states import AdminInput

logger = logging.getLogger(__name__)
router = Router(name="admin.reject")


def is_valid_reason(message: Message) -> bool:
    """Text, photo, document/file or a Telegram voice message. GIFs arrive as documents
    too, but carry `animation`; they're rejected along with stickers, videos, etc."""
    if message.animation is not None:
        return False
    return bool(message.text or message.photo or message.document or message.voice)


async def deliver_reason(bot: Bot, client: Client, from_chat_id: int, message_id: int) -> str | None:
    """Send the localized header, then copy the admin's message. Returns an error or None."""
    with in_locale(client_locale(client)):
        header = _("❌ Unfortunately, your payment was not accepted.\n\nReason:")
        again = submit_again_keyboard()
    try:
        await with_retry(lambda: bot.send_message(client.telegram_id, header))
        await with_retry(
            lambda: bot.copy_message(
                chat_id=client.telegram_id,
                from_chat_id=from_chat_id,
                message_id=message_id,
                reply_markup=again,
            )
        )
    except TelegramAPIError as exc:
        logger.warning("Rejection reason not delivered: client=%s reason=%s", client.id, exc.message, exc_info=True)
        return describe_error(exc)
    return None


def _delivery_status(name: str, error: str | None) -> str:
    if error is None:
        return _("✅ The reason was delivered to {name}.").format(name=html.escape(name))
    return _("⚠️ Could not deliver the reason to {name}: {error}").format(
        name=html.escape(name), error=html.escape(error)
    )


@router.callback_query(CardCb.filter(F.a == "rjy"))
async def ask_reason(
    callback: CallbackQuery, callback_data: CardCb, bot: Bot, session: AsyncSession, state: FSMContext
) -> None:
    await callback.answer()
    if not await still_pending(callback, bot, session, callback_data):
        return
    submission = await submissions_repo.get_by_id(session, callback_data.sid)
    await state.set_state(AdminInput.reject_reason)
    await state.update_data(
        rej={"cid": callback_data.cid, "sid": callback_data.sid, "src": callback_data.src, "p": callback_data.p,
             "name": submission.full_name}
    )
    screen = screens.reject_reason_prompt(
        cid=callback_data.cid, sid=callback_data.sid, src=callback_data.src, page=callback_data.p,
        name=submission.full_name,
    )
    await panel.show(bot, session, callback.from_user.id, screen)


@router.callback_query(CardCb.filter(F.a == "rjc"))
async def cancel_reason(callback: CallbackQuery, callback_data: CardCb, bot: Bot, session: AsyncSession) -> None:
    """Back to the card without rejecting (the pending input state is already cleared
    by CancelPendingInputMiddleware)."""
    await callback.answer()
    await show_card(callback, bot, session, callback_data)


@router.message(AdminInput.reject_reason)
async def on_reason(message: Message, bot: Bot, session: AsyncSession, state: FSMContext) -> None:
    admin = message.from_user
    rej = (await state.get_data()).get("rej")
    if not rej:
        await state.set_state(None)
        await safe_delete(bot, message.chat.id, message.message_id)
        return

    if not is_valid_reason(message):
        await safe_delete(bot, message.chat.id, message.message_id)
        screen = screens.reject_reason_prompt(
            cid=rej["cid"], sid=rej["sid"], src=rej["src"], page=rej["p"], name=rej["name"], invalid=True
        )
        await panel.show(bot, session, admin.id, screen)
        return

    await state.set_state(None)
    ok = await submissions_repo.set_review_result(
        session,
        submission_id=rej["sid"],
        client_id=rej["cid"],
        new_status=SubmissionStatus.rejected,
        admin_telegram_id=admin.id,
        admin_name=admin.full_name,
    )
    await session.commit()
    if not ok:
        submission = await submissions_repo.get_by_id(session, rej["sid"])
        logger.info("Reject ignored (already processed): admin=%s submission=%s", admin.id, rej["sid"])
        screen = await screens.client_card(
            session, rej["cid"], rej["src"], rej["p"], notice=processed_by_notice(submission)
        )
        if screen is not None:
            await panel.show(bot, session, admin.id, screen)
        return

    logger.info("Admin action: reject admin=%s client=%s submission=%s", admin.id, rej["cid"], rej["sid"])
    client = await clients_repo.get_by_id(session, rej["cid"])
    error = await deliver_reason(bot, client, message.chat.id, message.message_id)
    await message.reply(
        _delivery_status(rej["name"], error),
        reply_markup=None if error is None else kb.retry_reason(client.id, message.message_id),
    )

    notice = _("❌ {name} rejected.").format(name=html.escape(rej["name"]))
    # The reason and its delivery status stay in the chat, so re-send the panel below
    # them (the old panel is deleted: still exactly one panel).
    await panel.show(bot, session, admin.id, await screens.status_list(session, "p", 1, notice=notice), fresh=True)


@router.callback_query(RetryReasonCb.filter())
async def retry_reason(callback: CallbackQuery, callback_data: RetryReasonCb, bot: Bot, session: AsyncSession) -> None:
    await callback.answer()
    if too_soon(("rr", callback_data.mid)):
        return
    client = await clients_repo.get_by_id(session, callback_data.cid)
    if client is None:
        return
    latest = await submissions_repo.get_latest_for_client(session, client.id)
    name = latest.full_name if latest else str(client.telegram_id)

    error = await deliver_reason(bot, client, callback.message.chat.id, callback_data.mid)
    logger.info(
        "Admin action: retry rejection reason admin=%s client=%s ok=%s", callback.from_user.id, client.id, error is None
    )
    try:
        await callback.message.edit_text(
            _delivery_status(name, error),
            reply_markup=None if error is None else kb.retry_reason(client.id, callback_data.mid),
        )
    except TelegramBadRequest:
        pass  # "message is not modified" when the same error repeats
