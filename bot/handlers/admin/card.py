"""Client card: open it, and the "I'm sure / Cancel" keyboard swaps for approve/reject."""
from __future__ import annotations

import html

from aiogram import Bot, F, Router
from aiogram.types import CallbackQuery
from aiogram.utils.i18n import gettext as _
from sqlalchemy.ext.asyncio import AsyncSession

from bot.db.models import Submission, SubmissionStatus
from bot.db.repositories import submissions as submissions_repo
from bot.keyboards import admin as kb
from bot.keyboards.callbacks import CardCb
from bot.services import panel, screens

router = Router(name="admin.card")


def processed_by_notice(submission: Submission) -> str:
    who = submission.reviewed_by_name or str(submission.reviewed_by or "?")
    return _("ℹ️ Already processed by {admin}.").format(admin=html.escape(who))


async def show_card(
    callback: CallbackQuery, bot: Bot, session: AsyncSession, data: CardCb, notice: str | None = None
) -> None:
    screen = await screens.client_card(session, data.cid, data.src, data.p, notice=notice)
    if screen is None:
        await panel.show(bot, session, callback.from_user.id, await screens.main_menu(session, notice=_("Client not found.")))
        return
    await panel.show(bot, session, callback.from_user.id, screen)


async def still_pending(callback: CallbackQuery, bot: Bot, session: AsyncSession, data: CardCb) -> bool:
    """False (and the card is refreshed with who processed it) if the submission
    was already reviewed, e.g. by another admin."""
    submission = await submissions_repo.get_by_id(session, data.sid)
    if submission is not None and submission.status == SubmissionStatus.pending:
        return True
    notice = processed_by_notice(submission) if submission is not None else _("Client not found.")
    await show_card(callback, bot, session, data, notice=notice)
    return False


@router.callback_query(CardCb.filter(F.a == "open"))
async def open_card(callback: CallbackQuery, callback_data: CardCb, bot: Bot, session: AsyncSession) -> None:
    await callback.answer()
    await show_card(callback, bot, session, callback_data)


@router.callback_query(CardCb.filter(F.a.in_({"ap", "rj"})))
async def ask_confirmation(callback: CallbackQuery, callback_data: CardCb, bot: Bot, session: AsyncSession) -> None:
    await callback.answer()
    if not await still_pending(callback, bot, session, callback_data):
        return
    yes, no = ("apy", "apn") if callback_data.a == "ap" else ("rjy", "rjn")
    markup = kb.confirm(yes=yes, no=no, cid=callback_data.cid, sid=callback_data.sid, src=callback_data.src, page=callback_data.p)
    await panel.set_markup(bot, session, callback.from_user.id, markup)


@router.callback_query(CardCb.filter(F.a.in_({"apn", "rjn"})))
async def cancel_confirmation(callback: CallbackQuery, callback_data: CardCb, bot: Bot, session: AsyncSession) -> None:
    """Restore the card's own keyboard; nothing else changes."""
    await callback.answer()
    screen = await screens.client_card(session, callback_data.cid, callback_data.src, callback_data.p)
    if screen is not None and screen.markup is not None:
        await panel.set_markup(bot, session, callback.from_user.id, screen.markup)
