"""Builds every admin panel screen (text/caption + keyboard + optional media).

All user-provided values are html.escape()d; captions stay under Telegram's
1024-character limit.
"""
from __future__ import annotations

import html
import math
from datetime import datetime

from aiogram.utils.i18n import gettext as _
from sqlalchemy.ext.asyncio import AsyncSession

from bot.config import get_settings
from bot.db.models import Client, ClientStatus, InviteLink, Submission, SubmissionStatus
from bot.db.repositories import clients as clients_repo
from bot.db.repositories import invite_links as invite_repo
from bot.db.repositories import submissions as submissions_repo
from bot.keyboards import admin as kb
from bot.services.panel import Media, Screen
from bot.services.phone import format_phone_display
from bot.services.timefmt import to_display, utcnow

CAPTION_LIMIT = 1024
PAGE_SIZE = submissions_repo.PAGE_SIZE

STATUS_BY_CODE = {"p": ClientStatus.pending, "a": ClientStatus.approved, "r": ClientStatus.rejected}
CODE_BY_STATUS = {v: k for k, v in STATUS_BY_CODE.items()}
MARKER = {ClientStatus.pending: "⏳", ClientStatus.approved: "✅", ClientStatus.rejected: "❌", ClientStatus.none: "•"}


def _tz() -> str:
    return get_settings().tz


def _dt(value: datetime | None) -> str:
    return to_display(value, _tz()) or "—"


def status_code(status: ClientStatus) -> str:
    return CODE_BY_STATUS.get(status, "p")


def submission_status_label(status: SubmissionStatus) -> str:
    return {
        SubmissionStatus.pending: _("⏳ Pending review"),
        SubmissionStatus.approved: _("✅ Approved"),
        SubmissionStatus.rejected: _("❌ Rejected"),
    }[status]


def client_status_label(status: ClientStatus, *, has_link: bool = True) -> str:
    if status == ClientStatus.approved and not has_link:
        return _("⏳ Not approved yet — the invite link could not be created")
    return {
        ClientStatus.none: _("— No submissions"),
        ClientStatus.pending: _("⏳ Pending review"),
        ClientStatus.approved: _("✅ Approved"),
        ClientStatus.rejected: _("❌ Rejected"),
    }[status]


def link_state_label(invite: InviteLink, now: datetime) -> str:
    if invite.used_at is not None:
        return _("used ✅")
    if invite.revoked_at is not None:
        return _("revoked 🚫")
    if invite.expires_at <= now:
        return _("expired ⌛")
    return _("active 🟢")


def _pages(total: int) -> int:
    return max(1, math.ceil(total / PAGE_SIZE))


def _entry(index: int, submission: Submission, marker: str = "") -> str:
    prefix = f"{marker} " if marker else ""
    return (
        f"{index}. {prefix}{html.escape(submission.full_name)} — "
        f"{format_phone_display(submission.phone)} — {_dt(submission.created_at)}"
    )


# ---------------------------------------------------------------- main menu


async def main_menu(session: AsyncSession, notice: str | None = None) -> Screen:
    pending = await clients_repo.count_by_status(session, ClientStatus.pending)
    approved = await clients_repo.count_by_status(session, ClientStatus.approved)
    rejected = await clients_repo.count_by_status(session, ClientStatus.rejected)
    text = _("🗂 <b>Admin panel</b>\n\nChoose a section:")
    if notice:
        text = f"{notice}\n\n{text}"
    return Screen(text=text, markup=kb.main_menu(pending, approved, rejected))


def settings_screen() -> Screen:
    return Screen(text=_("⚙️ <b>Settings</b>\n\nChoose your language:"), markup=kb.settings_menu())


# ---------------------------------------------------------------- lists


def _list_title(code: str) -> str:
    return {
        "p": _("⏳ <b>Pending payments</b>"),
        "a": _("✅ <b>Approved clients</b>"),
        "r": _("❌ <b>Rejected clients</b>"),
    }[code]


async def status_list(session: AsyncSession, code: str, page: int, notice: str | None = None) -> Screen:
    status = STATUS_BY_CODE[code]
    page = max(page, 1)
    rows, total = await submissions_repo.list_by_status(session, status, page)
    pages = _pages(total)
    if not rows and page > pages:  # list shrank since the button was drawn
        page = pages
        rows, total = await submissions_repo.list_by_status(session, status, page)

    head = f"{notice}\n\n" if notice else ""
    if total == 0:
        return Screen(text=head + _list_title(code) + "\n\n" + _("The list is empty."), markup=kb.back_to_menu())

    lines = [_entry(i + 1, sub) for i, (_client, sub) in enumerate(rows)]
    text = (
        head
        + _list_title(code)
        + " · "
        + _("page {page}/{pages}").format(page=page, pages=pages)
        + "\n\n"
        + "\n".join(lines)
    )
    ids = [client.id for client, _sub in rows]
    return Screen(text=text, markup=kb.status_list(ids, st=code, page=page, pages=pages))


# ---------------------------------------------------------------- search


def search_prompt(*, too_short: bool = False) -> Screen:
    text = _(
        "🔍 <b>Search</b>\n\nSend part of a name, a phone number (any format), "
        "an @username or an exact Telegram ID."
    )
    if too_short:
        text += "\n\n" + _("⚠️ Please send at least 2 characters.")
    return Screen(text=text, markup=kb.search_prompt())


async def search_results(session: AsyncSession, query: str, page: int) -> Screen:
    query = query.strip().lstrip("@")
    page = max(page, 1)
    rows, total = await submissions_repo.search(session, query, page)
    pages = _pages(total)
    if not rows and page > pages:
        page = pages
        rows, total = await submissions_repo.search(session, query, page)

    title = _("🔍 Results for “{query}”").format(query=html.escape(query))
    if total == 0:
        return Screen(text=title + "\n\n" + _("Nothing found."), markup=kb.no_results())

    lines = [_entry(i + 1, sub, MARKER[client.status]) for i, (client, sub) in enumerate(rows)]
    text = (
        title
        + " · "
        + _("page {page}/{pages}").format(page=page, pages=pages)
        + "\n\n"
        + "\n".join(lines)
    )
    ids = [client.id for client, _sub in rows]
    return Screen(text=text, markup=kb.search_results(ids, page=page, pages=pages))


# ---------------------------------------------------------------- client card


def _fit_caption(parts: list[str]) -> str:
    caption = "\n".join(parts)
    while len(caption) > CAPTION_LIMIT and len(parts) > 1:
        parts = parts[:-1]  # drop the least important trailing lines first
        caption = "\n".join(parts)
    return caption[:CAPTION_LIMIT]


async def client_card(
    session: AsyncSession, cid: int, src: str, page: int, notice: str | None = None
) -> Screen | None:
    client = await clients_repo.get_by_id(session, cid)
    latest = await submissions_repo.get_latest_for_client(session, cid)
    if client is None or latest is None:
        return None
    attempts = await submissions_repo.count_for_client(session, cid)
    invite = await invite_repo.get_current_for_client(session, cid)
    has_link = invite is not None

    parts: list[str] = []
    if notice:
        parts += [notice, ""]
    parts += [
        _("👤 <b>{name}</b>").format(name=html.escape(latest.full_name)),
        _("📞 Phone: {phone}").format(phone=format_phone_display(latest.phone)),
        _("💬 Username: {username}").format(
            username=f"@{html.escape(client.username)}" if client.username else "—"
        ),
        _("🆔 Telegram ID: <code>{tid}</code>").format(tid=client.telegram_id),
        _("🕒 Submitted: {date}").format(date=_dt(latest.created_at)),
        _("📌 Status: {status}").format(status=client_status_label(client.status, has_link=has_link)),
        _("🔢 Attempts: {n}").format(n=attempts),
    ]

    if client.status == ClientStatus.approved and invite is not None:
        now = utcnow()
        if invite.sent_to_user:
            delivered = _("yes ✅")
        elif invite.send_error:
            delivered = _("no ❌ ({error})").format(error=html.escape(invite.send_error[:150]))
        else:
            delivered = _("not yet")
        parts += [
            "",
            _("🔗 Invite link:"),
            f"<pre>{html.escape(invite.link)}</pre>",
            _("⌛ Expires: {date}").format(date=_dt(invite.expires_at)),
            _("📍 Link state: {state}").format(state=link_state_label(invite, now)),
            _("📤 Delivered to user: {delivered}").format(delivered=delivered),
        ]
        if client.joined_at is not None:
            parts.append(_("🎉 Joined: {date}").format(date=_dt(client.joined_at)))

    markup = kb.card(
        cid=cid,
        sid=latest.id,
        src=src,
        page=page,
        status=client.status.value,
        attempts=attempts,
        has_link=has_link,
    )
    media = Media(file_id=latest.screenshot_file_id, kind=latest.screenshot_kind)
    return Screen(text=_fit_caption(parts), markup=markup, media=media)


# ---------------------------------------------------------------- history


async def history(session: AsyncSession, cid: int, index: int, src: str, page: int) -> Screen | None:
    attempts = await submissions_repo.list_for_client(session, cid)  # newest first
    if not attempts:
        return None
    index = min(max(index, 0), len(attempts) - 1)
    sub = attempts[index]
    total = len(attempts)
    number = total - index  # attempt 1 is the oldest

    reviewed = "—"
    if sub.reviewed_at is not None:
        reviewed = _("{admin} at {date}").format(
            admin=html.escape(sub.reviewed_by_name or str(sub.reviewed_by)), date=_dt(sub.reviewed_at)
        )
    parts = [
        _("📜 <b>Attempt {k} of {n}</b>").format(k=number, n=total),
        _("🕒 Date: {date}").format(date=_dt(sub.created_at)),
        _("👤 Full name: {name}").format(name=html.escape(sub.full_name)),
        _("📞 Phone: {phone}").format(phone=format_phone_display(sub.phone)),
        _("📌 Outcome: {status}").format(status=submission_status_label(sub.status)),
        _("👮 Reviewed by: {reviewed}").format(reviewed=reviewed),
    ]
    return Screen(
        text=_fit_caption(parts),
        markup=kb.history(cid=cid, index=index, total=total, src=src, page=page),
        media=Media(file_id=sub.screenshot_file_id, kind=sub.screenshot_kind),
    )


# ---------------------------------------------------------------- reject / approve


def reject_reason_prompt(*, cid: int, sid: int, src: str, page: int, name: str, invalid: bool = False) -> Screen:
    text = _(
        "❌ <b>Rejecting {name}</b>\n\n"
        "Send the reason as one message. Accepted formats:\n"
        "• text\n"
        "• photo (optionally with a caption)\n"
        "• file/document (optionally with a caption)\n"
        "• voice message recorded in Telegram\n\n"
        "The client will receive it without your name or profile."
    ).format(name=html.escape(name))
    if invalid:
        text += "\n\n" + _("⚠️ This format is not accepted. Please send text, a photo, a file or a voice message.")
    return Screen(text=text, markup=kb.reject_reason_prompt(cid=cid, sid=sid, src=src, page=page))


def approval_result(
    *, invite: InviteLink, name: str, error: str | None, cid: int, sid: int, src: str, page: int
) -> Screen:
    link = f"<pre>{html.escape(invite.link)}</pre>"
    if error is None:
        text = _(
            "✅ <b>{name}</b> approved.\n\n"
            "The link has been sent to the user. For safety, here is a copy you can forward if needed:\n{link}"
        ).format(name=html.escape(name), link=link)
    else:
        text = _(
            "✅ <b>{name}</b> approved, but the link could NOT be delivered.\n\n"
            "Reason: {error}\n\nLink:\n{link}"
        ).format(name=html.escape(name), error=html.escape(error), link=link)
    return Screen(
        text=text,
        markup=kb.approval_result(cid=cid, sid=sid, src=src, page=page, delivered=error is None),
    )
