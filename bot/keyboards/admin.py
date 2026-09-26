from __future__ import annotations

from aiogram.types import InlineKeyboardButton, InlineKeyboardMarkup
from aiogram.utils.i18n import gettext as _

from bot.keyboards.callbacks import (
    CardCb,
    HistCb,
    LangCb,
    ListCb,
    MenuCb,
    NoticeCb,
    RetryReasonCb,
    SearchCb,
)

Row = list[InlineKeyboardButton]


def _btn(text: str, cb) -> InlineKeyboardButton:  # noqa: ANN001 - any CallbackData
    return InlineKeyboardButton(text=text, callback_data=cb.pack())


def back_to_source_button(src: str, page: int) -> InlineKeyboardButton:
    if src == "s":
        return _btn(_("⬅️ Back"), SearchCb(a="page", p=page))
    return _btn(_("⬅️ Back"), ListCb(st=src, p=page))


def main_menu(pending: int, approved: int, rejected: int) -> InlineKeyboardMarkup:
    return InlineKeyboardMarkup(
        inline_keyboard=[
            [_btn(_("⏳ Pending ({n})").format(n=pending), ListCb(st="p", p=1))],
            [_btn(_("✅ Approved ({n})").format(n=approved), ListCb(st="a", p=1))],
            [_btn(_("❌ Rejected ({n})").format(n=rejected), ListCb(st="r", p=1))],
            [_btn(_("🔍 Search"), MenuCb(a="search")), _btn(_("⚙️ Settings"), MenuCb(a="settings"))],
        ]
    )


def back_to_menu() -> InlineKeyboardMarkup:
    return InlineKeyboardMarkup(inline_keyboard=[[_btn(_("⬅️ Back to menu"), MenuCb(a="home"))]])


def paged_list(
    client_ids: list[int], *, src: str, page: int, pages: int, nav_prev, nav_next  # noqa: ANN001
) -> InlineKeyboardMarkup:
    """Number buttons 1..N (5 per row) opening client cards, then ◀️/▶️, then Back to menu."""
    rows: list[Row] = []
    numbers = [
        _btn(str(i + 1), CardCb(a="open", cid=cid, src=src, p=page)) for i, cid in enumerate(client_ids)
    ]
    for start in range(0, len(numbers), 5):
        rows.append(numbers[start : start + 5])

    nav: Row = []
    if page > 1:
        nav.append(_btn("◀️", nav_prev))
    if page < pages:
        nav.append(_btn("▶️", nav_next))
    if nav:
        rows.append(nav)
    if src == "s":
        rows.append([_btn(_("🔍 Search again"), SearchCb(a="again"))])
    rows.append([_btn(_("⬅️ Back to menu"), MenuCb(a="home"))])
    return InlineKeyboardMarkup(inline_keyboard=rows)


def status_list(client_ids: list[int], *, st: str, page: int, pages: int) -> InlineKeyboardMarkup:
    return paged_list(
        client_ids,
        src=st,
        page=page,
        pages=pages,
        nav_prev=ListCb(st=st, p=page - 1),
        nav_next=ListCb(st=st, p=page + 1),
    )


def search_results(client_ids: list[int], *, page: int, pages: int) -> InlineKeyboardMarkup:
    return paged_list(
        client_ids,
        src="s",
        page=page,
        pages=pages,
        nav_prev=SearchCb(a="page", p=page - 1),
        nav_next=SearchCb(a="page", p=page + 1),
    )


def search_prompt() -> InlineKeyboardMarkup:
    return InlineKeyboardMarkup(inline_keyboard=[[_btn(_("↩️ Cancel"), SearchCb(a="cancel"))]])


def no_results() -> InlineKeyboardMarkup:
    return InlineKeyboardMarkup(
        inline_keyboard=[
            [_btn(_("🔍 Search again"), SearchCb(a="again"))],
            [_btn(_("⬅️ Back to menu"), MenuCb(a="home"))],
        ]
    )


def settings_menu() -> InlineKeyboardMarkup:
    return InlineKeyboardMarkup(
        inline_keyboard=[
            [
                _btn("🇷🇺 Русский", LangCb(lang="ru", ctx="a")),
                _btn("🇺🇿 O'zbekcha", LangCb(lang="uz", ctx="a")),
            ],
            [_btn(_("⬅️ Back to menu"), MenuCb(a="home"))],
        ]
    )


def card(
    *,
    cid: int,
    sid: int,
    src: str,
    page: int,
    status: str,
    attempts: int,
    has_link: bool,
) -> InlineKeyboardMarkup:
    """status: pending | approved | rejected (the client's current status)."""
    rows: list[Row] = []
    history = _btn(_("📜 History ({n})").format(n=attempts), HistCb(cid=cid, i=0, src=src, p=page))

    if status == "pending":
        rows.append(
            [
                _btn(_("✅ Approve"), CardCb(a="ap", cid=cid, sid=sid, src=src, p=page)),
                _btn(_("❌ Reject"), CardCb(a="rj", cid=cid, sid=sid, src=src, p=page)),
            ]
        )
        if attempts > 1:
            rows.append([history])
    elif status == "approved":
        if has_link:
            rows.append([_btn(_("🔗 Generate new link"), CardCb(a="gen", cid=cid, sid=sid, src=src, p=page))])
            rows.append([_btn(_("📤 Resend link to user"), CardCb(a="rs", cid=cid, sid=sid, src=src, p=page))])
        else:
            rows.append(
                [_btn(_("🔁 Retry generating link"), CardCb(a="rgen", cid=cid, sid=sid, src=src, p=page))]
            )
        rows.append([history])
    else:
        rows.append([history])

    rows.append([back_to_source_button(src, page)])
    return InlineKeyboardMarkup(inline_keyboard=rows)


def confirm(*, yes: str, no: str, cid: int, sid: int, src: str, page: int) -> InlineKeyboardMarkup:
    return InlineKeyboardMarkup(
        inline_keyboard=[
            [
                _btn(_("✅ I'm sure"), CardCb(a=yes, cid=cid, sid=sid, src=src, p=page)),
                _btn(_("↩️ Cancel"), CardCb(a=no, cid=cid, sid=sid, src=src, p=page)),
            ]
        ]
    )


def reject_reason_prompt(*, cid: int, sid: int, src: str, page: int) -> InlineKeyboardMarkup:
    return InlineKeyboardMarkup(
        inline_keyboard=[[_btn(_("↩️ Cancel"), CardCb(a="rjc", cid=cid, sid=sid, src=src, p=page))]]
    )


def history(*, cid: int, index: int, total: int, src: str, page: int) -> InlineKeyboardMarkup:
    nav: Row = []
    if index > 0:
        nav.append(_btn("◀️", HistCb(cid=cid, i=index - 1, src=src, p=page)))
    if index < total - 1:
        nav.append(_btn("▶️", HistCb(cid=cid, i=index + 1, src=src, p=page)))
    rows: list[Row] = [nav] if nav else []
    rows.append([_btn(_("⬅️ Back to card"), CardCb(a="open", cid=cid, src=src, p=page))])
    return InlineKeyboardMarkup(inline_keyboard=rows)


def approval_result(*, cid: int, sid: int, src: str, page: int, delivered: bool) -> InlineKeyboardMarkup:
    rows: list[Row] = []
    if not delivered:
        rows.append([_btn(_("🔁 Retry sending to user"), CardCb(a="rs", cid=cid, sid=sid, src=src, p=page))])
    rows.append([_btn(_("👤 Open card"), CardCb(a="open", cid=cid, src=src, p=page))])
    rows.append([back_to_source_button(src, page)])
    return InlineKeyboardMarkup(inline_keyboard=rows)


def notice_open(cid: int) -> InlineKeyboardMarkup:
    return InlineKeyboardMarkup(inline_keyboard=[[_btn(_("Open"), NoticeCb(cid=cid))]])


def retry_reason(cid: int, mid: int) -> InlineKeyboardMarkup:
    return InlineKeyboardMarkup(inline_keyboard=[[_btn(_("🔁 Retry sending"), RetryReasonCb(cid=cid, mid=mid))]])
