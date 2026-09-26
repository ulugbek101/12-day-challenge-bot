"""End-to-end admin panel scenarios: real handlers, real MySQL, fake Telegram API."""
from __future__ import annotations

from datetime import datetime, timedelta, timezone

import pytest
from aiogram.methods import (
    AnswerCallbackQuery,
    CopyMessage,
    CreateChatInviteLink,
    DeleteMessage,
    EditMessageMedia,
    EditMessageReplyMarkup,
    EditMessageText,
    ForwardMessage,
    RevokeChatInviteLink,
    SendMessage,
    SendPhoto,
)
from aiogram.types import InlineKeyboardMarkup
from sqlalchemy import select

from bot.db.models import (
    AdminPanel,
    Client,
    ClientStatus,
    InviteLink,
    Language,
    ScreenshotKind,
    Submission,
    SubmissionStatus,
)
from bot.db.repositories import clients as clients_repo
from bot.db.repositories import submissions as submissions_repo
from bot.keyboards.callbacks import CardCb, HistCb, LangCb, ListCb, MenuCb, NoticeCb, RetryReasonCb, SearchCb
from bot.services.timefmt import utcnow
from tests import fakes
from tests.conftest import ADMIN_1, ADMIN_2, CHANNEL_ID

USER = 222_333_444


# ------------------------------------------------------------------ helpers


async def seed_pending(
    app, *, telegram_id: int = USER, name: str = "Aziza Karimova", phone: str = "+998901234567",
    username: str | None = "aziza_k", language: Language = Language.ru, file_id: str = "SCREEN-1",
    created_at: datetime | None = None,
) -> tuple[int, int]:
    async with app.session_factory() as s:
        client, _ = await clients_repo.get_or_create(s, telegram_id, username)
        client.language = language
        sub = await submissions_repo.create(
            s, client_id=client.id, full_name=name, phone=phone,
            screenshot_file_id=file_id, screenshot_kind=ScreenshotKind.photo,
        )
        if created_at is not None:
            sub.created_at = created_at
        client.status = ClientStatus.pending
        await s.commit()
        return client.id, sub.id


async def panel_of(app, admin: int = ADMIN_1) -> AdminPanel | None:
    async with app.session_factory() as s:
        return await s.get(AdminPanel, admin)


async def tap(app, data: str, admin: int = ADMIN_1) -> None:
    panel = await panel_of(app, admin)
    await app.feed(fakes.callback(admin, data, message_id=panel.message_id if panel else 1,
                                  media=bool(panel and panel.is_media)))


async def open_panel(app, admin: int = ADMIN_1) -> None:
    await app.feed(fakes.message(admin, text="/admin"))


async def open_card(app, cid: int, src: str = "p", page: int = 1, admin: int = ADMIN_1) -> None:
    await open_panel(app, admin)
    await tap(app, CardCb(a="open", cid=cid, src=src, p=page).pack(), admin)


async def row(app, model, **where):  # noqa: ANN001, ANN003
    async with app.session_factory() as s:
        stmt = select(model)
        for k, v in where.items():
            stmt = stmt.where(getattr(model, k) == v)
        return list((await s.execute(stmt)).scalars())


def buttons(markup: InlineKeyboardMarkup | None) -> list[str]:
    return [b.text for r in (markup.inline_keyboard if markup else []) for b in r]


def last_panel_screen(app, admin: int = ADMIN_1):  # noqa: ANN201
    """The most recent panel content: (text, markup) from a send or an edit."""
    for call in reversed(app.tg.calls):
        if isinstance(call, (SendMessage, EditMessageText)) and getattr(call, "chat_id", None) == admin:
            return call.text, call.reply_markup
        if isinstance(call, SendPhoto) and call.chat_id == admin:
            return call.caption, call.reply_markup
        if isinstance(call, EditMessageMedia) and call.chat_id == admin:
            return call.media.caption, call.reply_markup
    raise AssertionError("no panel screen found")


# ------------------------------------------------------------------ panel basics


async def test_admin_panel_shows_live_counts_and_replaces_previous_panel(app):
    await seed_pending(app)
    await seed_pending(app, telegram_id=USER + 1, username="b")
    await open_panel(app)
    first = await panel_of(app)
    text, markup = last_panel_screen(app)
    assert "Админ-панель" in text
    assert buttons(markup)[:3] == ["⏳ На проверке (2)", "✅ Одобренные (0)", "❌ Отклонённые (0)"]

    await open_panel(app)
    second = await panel_of(app)
    assert second.message_id != first.message_id
    deleted = [c.message_id for c in app.tg.of(DeleteMessage)]
    assert first.message_id in deleted  # old panel removed
    # the admin's own "/admin" messages are deleted as well
    assert len([c for c in app.tg.of(DeleteMessage) if c.chat_id == ADMIN_1]) >= 3


async def test_admin_stray_messages_are_deleted(app):
    await app.feed(fakes.message(ADMIN_1, text="random text"))
    assert app.tg.of(DeleteMessage)[-1].chat_id == ADMIN_1


async def test_admin_language_change_in_panel(app):
    await open_panel(app)
    await tap(app, MenuCb(a="settings").pack())
    await tap(app, LangCb(lang="uz", ctx="a").pack())
    text, _ = last_panel_screen(app)
    assert "Bo'limni tanlang" in text
    changed = [c for c in app.tg.of(SendMessage) if c.chat_id == ADMIN_1 and "Til" in c.text][-1]
    assert [b.text for r in changed.reply_markup.keyboard for b in r] == ["🗂 Admin panel", "⚙️ Sozlamalar"]


# ------------------------------------------------------------------ lists


async def test_pending_list_is_fifo_paginated_ten_per_page(app):
    base = utcnow() - timedelta(days=1)
    for i in range(12):
        await seed_pending(app, telegram_id=USER + i, name=f"Client {i:02d}", username=f"u{i}",
                           created_at=base + timedelta(minutes=i))
    await open_panel(app)
    await tap(app, ListCb(st="p", p=1).pack())
    text, markup = last_panel_screen(app)
    assert "1. Client 00" in text and "10. Client 09" in text and "Client 10" not in text
    assert "+998 90 123 45 67" in text
    assert buttons(markup)[:10] == [str(i) for i in range(1, 11)]
    assert "▶️" in buttons(markup) and "◀️" not in buttons(markup)
    assert [len(r) for r in markup.inline_keyboard][:2] == [5, 5]

    await tap(app, ListCb(st="p", p=2).pack())
    text, markup = last_panel_screen(app)
    assert "1. Client 10" in text and "2. Client 11" in text
    assert "◀️" in buttons(markup) and "▶️" not in buttons(markup)


async def test_empty_list_shows_clear_text_and_back(app):
    await open_panel(app)
    await tap(app, ListCb(st="a", p=1).pack())
    text, markup = last_panel_screen(app)
    assert "Список пуст" in text
    assert buttons(markup) == ["⬅️ В меню"]


# ------------------------------------------------------------------ card


async def test_card_replaces_list_in_same_panel_with_screenshot(app):
    cid, _ = await seed_pending(app)
    await open_card(app, cid)
    photo = app.tg.of(SendPhoto)[-1]
    assert photo.photo == "SCREEN-1"
    assert "Aziza Karimova" in photo.caption and "+998 90 123 45 67" in photo.caption
    assert "@aziza_k" in photo.caption and str(USER) in photo.caption
    assert buttons(photo.reply_markup) == ["✅ Одобрить", "❌ Отклонить", "⬅️ Назад"]  # no history for 1 attempt
    panel = await panel_of(app)
    assert panel.is_media


async def test_card_html_escapes_user_input(app):
    cid, _ = await seed_pending(app, name="<b>Evil</b> & Co")
    await open_card(app, cid)
    caption = app.tg.of(SendPhoto)[-1].caption
    assert "&lt;b&gt;Evil&lt;/b&gt; &amp; Co" in caption


async def test_approve_confirmation_and_cancel_restore_keyboard(app):
    cid, sid = await seed_pending(app)
    await open_card(app, cid)
    await tap(app, CardCb(a="ap", cid=cid, sid=sid).pack())
    assert buttons(app.tg.of(EditMessageReplyMarkup)[-1].reply_markup) == ["✅ Да, уверен(а)", "↩️ Отмена"]
    await tap(app, CardCb(a="apn", cid=cid, sid=sid).pack())
    assert buttons(app.tg.of(EditMessageReplyMarkup)[-1].reply_markup) == ["✅ Одобрить", "❌ Отклонить", "⬅️ Назад"]
    [sub] = await row(app, Submission)
    assert sub.status == SubmissionStatus.pending


# ------------------------------------------------------------------ approve


async def test_approve_creates_personal_join_request_link_and_sends_it(app):
    cid, sid = await seed_pending(app)
    await open_card(app, cid)
    await tap(app, CardCb(a="ap", cid=cid, sid=sid).pack())
    await tap(app, CardCb(a="apy", cid=cid, sid=sid).pack())

    [sub] = await row(app, Submission)
    [client] = await row(app, Client, telegram_id=USER)
    assert sub.status == SubmissionStatus.approved and sub.reviewed_by == ADMIN_1
    assert client.status == ClientStatus.approved

    [create] = app.tg.of(CreateChatInviteLink)
    assert create.chat_id == CHANNEL_ID
    assert create.creates_join_request is True
    assert create.member_limit is None
    assert create.name == f"c{cid}s{sid}"
    expire = create.expire_date
    assert isinstance(expire, datetime)
    assert abs((expire - datetime.now(timezone.utc)) - timedelta(hours=24)) < timedelta(minutes=1)

    [invite] = await row(app, InviteLink)
    assert invite.sent_to_user is True and invite.send_error is None
    congrats = [c for c in app.tg.of(SendMessage) if c.chat_id == USER][-1]
    assert "Поздравляем" in congrats.text and f"<pre>{invite.link}</pre>" in congrats.text

    text, markup = last_panel_screen(app)
    assert "Ссылка отправлена пользователю" in text and f"<pre>{invite.link}</pre>" in text
    assert "⬅️ Назад" in buttons(markup)


async def test_approve_when_user_blocked_bot_offers_retry(app):
    cid, sid = await seed_pending(app)
    app.tg.fail(SendMessage, chat_id=USER)
    await open_card(app, cid)
    await tap(app, CardCb(a="apy", cid=cid, sid=sid).pack())

    [invite] = await row(app, InviteLink)
    assert invite.sent_to_user is False and "blocked" in invite.send_error
    text, markup = last_panel_screen(app)
    assert "НЕ удалось доставить" in text and "blocked" in text and invite.link in text
    assert "🔁 Повторить отправку" in buttons(markup)

    app.tg.clear_failures()
    await tap(app, CardCb(a="rs", cid=cid, sid=sid).pack())
    [invite] = await row(app, InviteLink)
    assert invite.sent_to_user is True and invite.send_error is None
    assert "Ссылка отправлена" in last_panel_screen(app)[0]


async def test_link_generation_failure_tells_user_not_approved_yet_and_allows_retry(app):
    cid, sid = await seed_pending(app)
    rule = app.tg.fail(CreateChatInviteLink, error="not enough rights to manage chat invite links")
    await open_card(app, cid)
    await tap(app, CardCb(a="apy", cid=cid, sid=sid).pack())

    assert await row(app, InviteLink) == []
    assert "ещё не подтверждена" in [c for c in app.tg.of(SendMessage) if c.chat_id == USER][-1].text
    caption, markup = last_panel_screen(app)
    assert "Ещё не одобрен" in caption and "not enough rights" in caption
    assert "🔁 Повторить создание ссылки" in buttons(markup)

    app.tg.rules.remove(rule)
    await tap(app, CardCb(a="rgen", cid=cid, sid=sid).pack())
    [invite] = await row(app, InviteLink)
    assert invite.sent_to_user is True
    assert "Поздравляем" in [c for c in app.tg.of(SendMessage) if c.chat_id == USER][-1].text


async def test_second_admin_sees_already_processed(app):
    cid, sid = await seed_pending(app)
    await open_card(app, cid, admin=ADMIN_1)
    await open_card(app, cid, admin=ADMIN_2)
    await tap(app, CardCb(a="apy", cid=cid, sid=sid).pack(), ADMIN_1)
    await tap(app, CardCb(a="apy", cid=cid, sid=sid).pack(), ADMIN_2)

    assert len(app.tg.of(CreateChatInviteLink)) == 1
    caption, _ = last_panel_screen(app, ADMIN_2)
    assert "Уже обработано" in caption
    congrats = [c for c in app.tg.of(SendMessage) if c.chat_id == USER and "Поздравляем" in c.text]
    assert len(congrats) == 1


async def test_double_tap_approve_creates_one_link_and_one_message(app):
    cid, sid = await seed_pending(app)
    await open_card(app, cid)
    await tap(app, CardCb(a="apy", cid=cid, sid=sid).pack())
    await tap(app, CardCb(a="apy", cid=cid, sid=sid).pack())
    assert len(app.tg.of(CreateChatInviteLink)) == 1
    assert len([c for c in app.tg.of(SendMessage) if c.chat_id == USER]) == 1


# ------------------------------------------------------------------ approved card actions


async def _approved(app) -> tuple[int, int]:
    cid, sid = await seed_pending(app)
    await open_card(app, cid)
    await tap(app, CardCb(a="apy", cid=cid, sid=sid).pack())
    await tap(app, CardCb(a="open", cid=cid, src="a", p=1).pack())
    return cid, sid


async def test_approved_card_shows_link_details_and_actions(app):
    cid, sid = await _approved(app)
    caption, markup = last_panel_screen(app)
    [invite] = await row(app, InviteLink)
    assert f"<pre>{invite.link}</pre>" in caption
    assert "активна" in caption and "Доставлена пользователю: да" in caption
    assert buttons(markup) == ["🔗 Создать новую ссылку", "📤 Отправить ссылку повторно", "📜 История (1)", "⬅️ Назад"]


async def test_generate_new_link_revokes_old_and_updates_card_in_place(app):
    cid, sid = await _approved(app)
    [old] = await row(app, InviteLink)
    old.created_at = utcnow() - timedelta(minutes=1)  # not a double tap
    async with app.session_factory() as s:
        (await s.get(InviteLink, old.id)).created_at = old.created_at
        await s.commit()
    app.tg.reset()

    await tap(app, CardCb(a="gen", cid=cid, sid=sid, src="a").pack())

    assert [c.invite_link for c in app.tg.of(RevokeChatInviteLink)] == [old.link]
    assert len(app.tg.of(CreateChatInviteLink)) == 1
    links = await row(app, InviteLink)
    assert links[0].revoked_at is not None and links[1].revoked_at is None
    # updated in place: an edit of the same panel message, nothing new sent anywhere
    assert app.tg.of(EditMessageMedia) and not app.tg.of(SendPhoto) and not app.tg.of(SendMessage)
    assert links[1].link in app.tg.of(EditMessageMedia)[-1].media.caption

    await tap(app, CardCb(a="gen", cid=cid, sid=sid, src="a").pack())  # immediate double tap
    assert len(await row(app, InviteLink)) == 2


async def test_resend_without_active_link_shows_alert(app, session_factory):
    cid, sid = await _approved(app)
    async with session_factory() as s:
        for invite in (await s.execute(select(InviteLink))).scalars():
            invite.expires_at = utcnow() - timedelta(minutes=1)
        await s.commit()
    await tap(app, CardCb(a="rs", cid=cid, sid=sid, src="a").pack())
    alert = app.tg.of(AnswerCallbackQuery)[-1]
    assert alert.show_alert is True and "нет" in alert.text.lower()


# ------------------------------------------------------------------ reject


async def _to_reason_prompt(app) -> tuple[int, int]:
    cid, sid = await seed_pending(app)
    await open_card(app, cid)
    await tap(app, CardCb(a="rj", cid=cid, sid=sid).pack())
    assert buttons(app.tg.of(EditMessageReplyMarkup)[-1].reply_markup) == ["✅ Да, уверен(а)", "↩️ Отмена"]
    await tap(app, CardCb(a="rjy", cid=cid, sid=sid).pack())
    return cid, sid


@pytest.mark.parametrize(
    "reason",
    [
        dict(text="The amount is wrong"),
        dict(photo=True, caption="See the amount here"),
        dict(document_mime="application/pdf", caption="Receipt requirements"),
        dict(voice=True),
    ],
    ids=["text", "photo+caption", "file+caption", "voice"],
)
async def test_reject_with_each_accepted_reason_type(app, reason):
    cid, sid = await _to_reason_prompt(app)
    assert "Отклонение: Aziza Karimova" in last_panel_screen(app)[0]
    update = fakes.message(ADMIN_1, **reason)
    reason_id = update["message"]["message_id"]
    await app.feed(update)

    [sub] = await row(app, Submission)
    [client] = await row(app, Client, telegram_id=USER)
    assert sub.status == SubmissionStatus.rejected and client.status == ClientStatus.rejected

    header = [c for c in app.tg.of(SendMessage) if c.chat_id == USER][-1]
    assert "не принята" in header.text
    [copy] = app.tg.of(CopyMessage)
    assert (copy.chat_id, copy.from_chat_id, copy.message_id) == (USER, ADMIN_1, reason_id)
    assert buttons(copy.reply_markup) == ["🔄 Отправить снова"]
    assert app.tg.of(ForwardMessage) == []  # never reveal the admin

    assert reason_id not in [c.message_id for c in app.tg.of(DeleteMessage)]  # reason kept
    status = [c for c in app.tg.of(SendMessage) if c.chat_id == ADMIN_1 and "Причина доставлена" in c.text]
    assert len(status) == 1 and status[0].reply_parameters.message_id == reason_id
    text, _ = last_panel_screen(app)
    assert "Aziza Karimova: отклонено" in text


@pytest.mark.parametrize("bad", [dict(sticker=True), dict(video=True), dict(animation=True)])
async def test_invalid_reason_is_deleted_and_hint_repeated(app, bad):
    await _to_reason_prompt(app)
    update = fakes.message(ADMIN_1, **bad)
    await app.feed(update)
    assert update["message"]["message_id"] in [c.message_id for c in app.tg.of(DeleteMessage)]
    assert "формат не принимается" in last_panel_screen(app)[0]
    [sub] = await row(app, Submission)
    assert sub.status == SubmissionStatus.pending
    await app.feed(fakes.message(ADMIN_1, text="Valid reason now"))
    [sub] = await row(app, Submission)
    assert sub.status == SubmissionStatus.rejected


async def test_cancel_reject_at_confirmation_and_at_reason(app):
    cid, sid = await seed_pending(app)
    await open_card(app, cid)
    await tap(app, CardCb(a="rj", cid=cid, sid=sid).pack())
    await tap(app, CardCb(a="rjn", cid=cid, sid=sid).pack())
    assert buttons(app.tg.of(EditMessageReplyMarkup)[-1].reply_markup)[:2] == ["✅ Одобрить", "❌ Отклонить"]

    await tap(app, CardCb(a="rjy", cid=cid, sid=sid).pack())
    await tap(app, CardCb(a="rjc", cid=cid, sid=sid).pack())
    await app.feed(fakes.message(ADMIN_1, text="this is not a reason anymore"))
    [sub] = await row(app, Submission)
    assert sub.status == SubmissionStatus.pending
    assert app.tg.of(CopyMessage) == []


async def test_reject_delivery_failure_can_be_retried_until_it_succeeds(app):
    cid, _ = await _to_reason_prompt(app)
    app.tg.fail(SendMessage, chat_id=USER)
    update = fakes.message(ADMIN_1, text="Wrong amount")
    await app.feed(update)

    status = [c for c in app.tg.of(SendMessage) if c.chat_id == ADMIN_1 and "Не удалось доставить" in c.text][-1]
    assert buttons(status.reply_markup) == ["🔁 Повторить отправку"]

    await app.feed(fakes.callback(ADMIN_1, RetryReasonCb(cid=cid, mid=update["message"]["message_id"]).pack()))
    assert "Не удалось доставить" in app.tg.of(EditMessageText)[-1].text  # still blocked

    app.tg.clear_failures()
    await app.feed(fakes.callback(ADMIN_1, RetryReasonCb(cid=cid, mid=update["message"]["message_id"]).pack(),
                                  message_id=99))
    edit = app.tg.of(EditMessageText)[-1]
    assert "Причина доставлена" in edit.text and edit.reply_markup is None
    assert app.tg.of(CopyMessage)[-1].chat_id == USER


async def test_reason_is_relayed_in_the_clients_language(app):
    cid, sid = await seed_pending(app, language=Language.uz)
    await open_card(app, cid)
    await tap(app, CardCb(a="rjy", cid=cid, sid=sid).pack())
    await app.feed(fakes.message(ADMIN_1, text="Summa noto'g'ri"))
    header = [c for c in app.tg.of(SendMessage) if c.chat_id == USER][-1]
    assert "qabul qilinmadi" in header.text
    assert buttons(app.tg.of(CopyMessage)[-1].reply_markup) == ["🔄 Qayta yuborish"]


# ------------------------------------------------------------------ history


async def test_history_flips_between_attempts_newest_first(app, session_factory):
    cid, sid1 = await seed_pending(app, name="First Name", file_id="S1")
    async with session_factory() as s:
        await submissions_repo.set_review_result(s, submission_id=sid1, client_id=cid,
                                                 new_status=SubmissionStatus.rejected,
                                                 admin_telegram_id=ADMIN_1, admin_name="Admin One")
        await s.commit()
    _, sid2 = await seed_pending(app, name="Second Name", file_id="S2")

    await open_card(app, cid)
    _, markup = last_panel_screen(app)
    assert "📜 История (2)" in buttons(markup)

    await tap(app, HistCb(cid=cid, i=0, src="p", p=1).pack())
    edit = app.tg.of(EditMessageMedia)[-1]
    assert edit.media.media == "S2" and "Попытка 2 из 2" in edit.media.caption
    assert buttons(edit.reply_markup) == ["▶️", "⬅️ К карточке"]

    await tap(app, HistCb(cid=cid, i=1, src="p", p=1).pack())
    edit = app.tg.of(EditMessageMedia)[-1]
    assert edit.media.media == "S1" and "Попытка 1 из 2" in edit.media.caption
    assert "Admin One" in edit.media.caption and "Отклонено" in edit.media.caption
    assert buttons(edit.reply_markup) == ["◀️", "⬅️ К карточке"]


# ------------------------------------------------------------------ search


async def _search(app, query: str) -> tuple[str, InlineKeyboardMarkup]:
    await tap(app, MenuCb(a="search").pack())
    update = fakes.message(ADMIN_1, text=query)
    await app.feed(update)
    assert update["message"]["message_id"] in [c.message_id for c in app.tg.of(DeleteMessage)]
    return last_panel_screen(app)


@pytest.mark.parametrize(
    "query",
    ["aziz", "KARIMOVA", "90 123 45 67", "+998901234567", "998-90-123", "@aziza_k", str(USER)],
)
async def test_search_finds_client_by_any_field(app, query):
    await seed_pending(app)
    await seed_pending(app, telegram_id=USER + 5, name="Other Person", phone="+998935554433", username="other")
    await open_panel(app)
    text, markup = await _search(app, query)
    assert "⏳ Aziza Karimova" in text and "Other Person" not in text
    assert buttons(markup)[0] == "1"


async def test_search_matches_names_from_older_attempts(app, session_factory):
    cid, sid = await seed_pending(app, name="Old Name")
    async with session_factory() as s:
        await submissions_repo.set_review_result(s, submission_id=sid, client_id=cid,
                                                 new_status=SubmissionStatus.rejected,
                                                 admin_telegram_id=ADMIN_1, admin_name="A")
        await s.commit()
    await seed_pending(app, name="New Name")
    await open_panel(app)
    text, _ = await _search(app, "old")
    assert "New Name" in text  # listed with the latest submission


async def test_search_requires_two_characters_and_reports_no_results(app):
    await seed_pending(app)
    await open_panel(app)
    text, _ = await _search(app, "a")
    assert "не менее 2 символов" in text
    await app.feed(fakes.message(ADMIN_1, text="zzzz"))
    text, markup = last_panel_screen(app)
    assert "Ничего не найдено" in text
    assert buttons(markup) == ["🔍 Искать снова", "⬅️ В меню"]


async def test_search_cancel_and_back_from_card_returns_to_results(app):
    cid, _ = await seed_pending(app)
    await open_panel(app)
    await tap(app, MenuCb(a="search").pack())
    await tap(app, SearchCb(a="cancel").pack())
    assert "Админ-панель" in last_panel_screen(app)[0]

    await _search(app, "aziza")
    await tap(app, CardCb(a="open", cid=cid, src="s", p=1).pack())
    _, markup = last_panel_screen(app)
    back = markup.inline_keyboard[-1][0]
    assert back.callback_data == SearchCb(a="page", p=1).pack()
    await tap(app, back.callback_data)
    assert "Результаты по «aziza»" in last_panel_screen(app)[0]


# ------------------------------------------------------------------ notices


async def test_open_on_a_notice_turns_it_into_the_panel(app):
    cid, _ = await seed_pending(app)
    await open_panel(app)
    old_panel = await panel_of(app)
    await app.feed(fakes.callback(ADMIN_1, NoticeCb(cid=cid).pack(), message_id=4242))
    deleted = [c.message_id for c in app.tg.of(DeleteMessage)]
    assert old_panel.message_id in deleted
    assert 4242 in deleted  # the text notice is swapped for the media card
    photo = app.tg.of(SendPhoto)[-1]
    assert "Aziza Karimova" in photo.caption
    assert (await panel_of(app)).message_id != old_panel.message_id


async def test_non_admin_cannot_use_admin_callbacks(app):
    cid, sid = await seed_pending(app)
    await app.feed(fakes.callback(USER + 99, CardCb(a="apy", cid=cid, sid=sid).pack()))
    [sub] = await row(app, Submission)
    assert sub.status == SubmissionStatus.pending
    assert app.tg.of(CreateChatInviteLink) == []
