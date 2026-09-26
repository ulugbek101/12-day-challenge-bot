"""End-to-end client flow: real handlers, real MySQL, fake Telegram API."""
from __future__ import annotations

from aiogram.methods import SendDocument, SendMessage, SendPhoto
from aiogram.types import InlineKeyboardMarkup, ReplyKeyboardMarkup
from sqlalchemy import func, select

from bot.db.models import Client, ClientStatus, Language, ScreenshotKind, Submission, SubmissionStatus
from bot.keyboards.callbacks import AgainCb, FormCb, LangCb
from tests import fakes
from tests.conftest import ADMIN_1, ADMIN_2

USER = 111_222_333


async def _client(app, telegram_id: int = USER) -> Client | None:
    async with app.session_factory() as s:
        return (await s.execute(select(Client).where(Client.telegram_id == telegram_id))).scalar_one_or_none()


async def _submissions(app) -> list[Submission]:
    async with app.session_factory() as s:
        return list((await s.execute(select(Submission).order_by(Submission.id))).scalars())


def _last_message(app, chat_id: int = USER) -> SendMessage:
    return [c for c in app.tg.of(SendMessage) if c.chat_id == chat_id][-1]


def _buttons(markup) -> list[str]:  # noqa: ANN001
    if isinstance(markup, InlineKeyboardMarkup):
        return [b.text for row in markup.inline_keyboard for b in row]
    if isinstance(markup, ReplyKeyboardMarkup):
        return [b.text for row in markup.keyboard for b in row]
    return []


async def start_as_new_user(app, lang: str = "ru", *, username: str | None = "aziza_k") -> None:
    await app.feed(fakes.message(USER, text="/start", username=username))
    await app.feed(fakes.callback(USER, LangCb(lang=lang, ctx="s").pack()))


async def fill_form(app, *, name: str = "Aziza Karimova", phone: str = "90-123-45-67") -> None:
    await app.feed(fakes.message(USER, photo=True, file_id="SCREEN-1"))
    await app.feed(fakes.message(USER, text=name))
    await app.feed(fakes.message(USER, text=phone))


# ------------------------------------------------------------------ language


async def test_first_start_asks_language_in_both_languages_with_flags(app):
    await app.feed(fakes.message(USER, text="/start"))

    prompt = _last_message(app)
    assert "Выберите язык" in prompt.text and "Tilni tanlang" in prompt.text
    assert _buttons(prompt.reply_markup) == ["🇷🇺 Русский", "🇺🇿 O'zbekcha"]
    client = await _client(app)
    assert client is not None and client.language is None


async def test_choosing_uzbek_continues_in_uzbek_and_starts_the_form(app):
    await start_as_new_user(app, "uz")

    client = await _client(app)
    assert client.language == Language.uz
    texts = app.tg.texts_to(USER)
    assert any("Xush kelibsiz" in t for t in texts)
    assert any("Qanday to'lash kerak" in t for t in texts)  # payment instructions, in Uzbek
    welcome = [c for c in app.tg.of(SendMessage) if c.chat_id == USER and "Xush kelibsiz" in c.text][0]
    assert _buttons(welcome.reply_markup) == ["💳 To'lovni yuborish", "⚙️ Sozlamalar"]


async def test_changing_language_in_settings_resends_keyboard_in_new_language(app):
    await start_as_new_user(app, "ru")
    await app.feed(fakes.message(USER, text="❌ Отмена"))  # any text; form stays, irrelevant here
    await app.feed(fakes.message(USER, text="⚙️ Настройки"))
    assert "Выберите язык" in _last_message(app).text

    await app.feed(fakes.callback(USER, LangCb(lang="uz", ctx="u").pack()))

    assert (await _client(app)).language == Language.uz
    last = _last_message(app)
    assert last.text == "✅ Til o'zgartirildi."
    assert _buttons(last.reply_markup) == ["💳 To'lovni yuborish", "⚙️ Sozlamalar"]


async def test_reply_button_from_an_older_language_keyboard_still_works(app):
    await start_as_new_user(app, "uz")
    await app.feed(fakes.callback(USER, FormCb(a="cancel").pack()))
    app.tg.reset()
    await app.feed(fakes.message(USER, text="💳 Отправить оплату"))  # the RU label
    assert any("Qanday to'lash kerak" in t for t in app.tg.texts_to(USER))


# ------------------------------------------------------------------ happy path


async def test_full_submission_creates_pending_submission_and_notifies_admins(app):
    await start_as_new_user(app)
    await fill_form(app, name="  Aziza   Karimova ", phone="+998 90-123 45 67")

    summary = [c for c in app.tg.of(SendPhoto) if c.chat_id == USER][-1]
    assert summary.photo == "SCREEN-1"
    assert "Aziza Karimova" in summary.caption
    assert "+998 90 123 45 67" in summary.caption
    app.tg.reset()

    await app.feed(fakes.callback(USER, FormCb(a="send").pack(), media=True, text=summary.caption))

    [sub] = await _submissions(app)
    assert sub.full_name == "Aziza Karimova"
    assert sub.phone == "+998901234567"
    assert sub.phone_normalized == "998901234567"
    assert sub.screenshot_kind == ScreenshotKind.photo
    assert sub.status == SubmissionStatus.pending
    assert (await _client(app)).status == ClientStatus.pending

    confirmation = _last_message(app)
    assert "отправлена на проверку" in confirmation.text
    assert _buttons(confirmation.reply_markup) == ["💳 Отправить оплату", "⚙️ Настройки"]

    for admin in (ADMIN_1, ADMIN_2):
        notice = _last_message(app, admin)
        assert "Aziza Karimova" in notice.text
        assert len(_buttons(notice.reply_markup)) == 1


async def test_image_sent_as_document_is_accepted(app):
    await start_as_new_user(app)
    await app.feed(fakes.message(USER, document_mime="image/jpeg", file_id="DOC-IMG"))
    await app.feed(fakes.message(USER, text="Aziza Karimova"))
    await app.feed(fakes.message(USER, text="901234567"))

    summary = [c for c in app.tg.of(SendDocument) if c.chat_id == USER][-1]
    assert summary.document == "DOC-IMG"
    await app.feed(fakes.callback(USER, FormCb(a="send").pack(), media=True))
    [sub] = await _submissions(app)
    assert sub.screenshot_kind == ScreenshotKind.document


# ------------------------------------------------------------------ validation


async def test_non_image_screenshot_is_refused_with_a_hint(app):
    await start_as_new_user(app)
    for bad in (dict(text="hello"), dict(document_mime="application/pdf"), dict(sticker=True), dict(animation=True)):
        app.tg.reset()
        await app.feed(fakes.message(USER, **bad))
        assert "скриншот" in _last_message(app).text.lower()
    # still waiting for the screenshot
    await app.feed(fakes.message(USER, photo=True))
    assert "полное имя" in _last_message(app).text


async def test_name_length_is_validated(app):
    await start_as_new_user(app)
    await app.feed(fakes.message(USER, photo=True))
    await app.feed(fakes.message(USER, text="A"))
    assert "от 2 до 100" in _last_message(app).text
    await app.feed(fakes.message(USER, text="x" * 101))
    assert "от 2 до 100" in _last_message(app).text
    await app.feed(fakes.message(USER, text="Al"))
    assert "номер телефона" in [c for c in app.tg.of(SendMessage) if c.chat_id == USER][-1].text


async def test_contact_of_another_person_is_refused_own_contact_accepted(app):
    await start_as_new_user(app)
    await app.feed(fakes.message(USER, photo=True))
    await app.feed(fakes.message(USER, text="Aziza Karimova"))

    await app.feed(fakes.message(USER, contact_of=555, phone="+998901112233"))
    assert "своим контактом" in _last_message(app).text

    await app.feed(fakes.message(USER, contact_of=USER, phone="998901234567"))
    await app.feed(fakes.callback(USER, FormCb(a="send").pack(), media=True))
    [sub] = await _submissions(app)
    assert sub.phone == "+998901234567"


async def test_foreign_or_malformed_phone_is_refused(app):
    await start_as_new_user(app)
    await app.feed(fakes.message(USER, photo=True))
    await app.feed(fakes.message(USER, text="Aziza Karimova"))
    for bad in ("+1 555 123 4567", "12345", "abc"):
        await app.feed(fakes.message(USER, text=bad))
        assert "Узбекистана" in _last_message(app).text
    await app.feed(fakes.message(USER, contact_of=USER, phone="+15551234567"))
    assert "Узбекистана" in _last_message(app).text
    assert await _submissions(app) == []


# ------------------------------------------------------------------ form controls


async def test_cancel_ends_the_form_and_restores_the_keyboard(app):
    await start_as_new_user(app)
    await app.feed(fakes.message(USER, photo=True))
    await app.feed(fakes.callback(USER, FormCb(a="cancel").pack()))
    last = _last_message(app)
    assert "отменена" in last.text
    assert _buttons(last.reply_markup) == ["💳 Отправить оплату", "⚙️ Настройки"]
    await app.feed(fakes.message(USER, text="Aziza Karimova"))  # no longer in the form
    assert "кнопки ниже" in _last_message(app).text


async def test_start_over_from_summary_restarts_the_form(app):
    await start_as_new_user(app)
    await fill_form(app)
    await app.feed(fakes.callback(USER, FormCb(a="restart").pack(), media=True))
    assert any("Как оплатить" in t for t in app.tg.texts_to(USER)[-2:])
    assert await _submissions(app) == []


async def test_double_tap_on_send_creates_only_one_submission(app):
    await start_as_new_user(app)
    await fill_form(app)
    await app.feed(fakes.callback(USER, FormCb(a="send").pack(), media=True))
    await app.feed(fakes.callback(USER, FormCb(a="send").pack(), media=True))
    assert len(await _submissions(app)) == 1
    admin_notices = [c for c in app.tg.of(SendMessage) if c.chat_id == ADMIN_1 and "Aziza" in c.text]
    assert len(admin_notices) == 1


# ------------------------------------------------------------------ guards


async def test_pending_client_cannot_submit_again(app):
    await start_as_new_user(app)
    await fill_form(app)
    await app.feed(fakes.callback(USER, FormCb(a="send").pack(), media=True))
    app.tg.reset()

    await app.feed(fakes.message(USER, text="💳 Отправить оплату"))
    assert "на проверке" in _last_message(app).text
    await app.feed(fakes.message(USER, photo=True))  # no form active
    assert len(await _submissions(app)) == 1


async def test_approved_client_with_link_is_told_to_use_it(app, session_factory):
    await start_as_new_user(app)
    await fill_form(app)
    await app.feed(fakes.callback(USER, FormCb(a="send").pack(), media=True))
    from bot.db.repositories import invite_links as invite_repo
    from bot.services.timefmt import utcnow
    from datetime import timedelta

    async with session_factory() as s:
        client = (await s.execute(select(Client).where(Client.telegram_id == USER))).scalar_one()
        client.status = ClientStatus.approved
        [sub] = (await s.execute(select(Submission))).scalars().all()
        await invite_repo.create(s, client_id=client.id, submission_id=sub.id, link="https://t.me/+x",
                                 name="c1s1", expires_at=utcnow() + timedelta(hours=5))
        await s.commit()

    await app.feed(fakes.message(USER, text="💳 Отправить оплату"))
    text = _last_message(app).text
    assert "уже подтверждена" in text and "@stylist_support" in text


async def test_approved_client_without_link_is_told_not_approved_yet(app, session_factory):
    await start_as_new_user(app)
    async with session_factory() as s:
        client = (await s.execute(select(Client).where(Client.telegram_id == USER))).scalar_one()
        client.status = ClientStatus.approved
        await s.commit()
    await app.feed(fakes.message(USER, text="💳 Отправить оплату"))
    assert "ещё не подтверждена" in _last_message(app).text


# ------------------------------------------------------------------ resubmission


async def test_after_rejection_previous_name_and_phone_can_be_reused(app, session_factory):
    await start_as_new_user(app)
    await fill_form(app, name="Aziza Karimova", phone="901234567")
    await app.feed(fakes.callback(USER, FormCb(a="send").pack(), media=True))
    async with session_factory() as s:
        client = (await s.execute(select(Client).where(Client.telegram_id == USER))).scalar_one()
        client.status = ClientStatus.rejected
        await s.commit()

    await app.feed(fakes.callback(USER, AgainCb().pack()))
    await app.feed(fakes.message(USER, photo=True, file_id="SCREEN-2"))
    name_prompt = _last_message(app)
    assert "Использовать: Aziza Karimova" in _buttons(name_prompt.reply_markup)

    await app.feed(fakes.callback(USER, FormCb(a="name").pack()))
    phone_offer = _last_message(app)
    assert "Использовать: +998 90 123 45 67" in _buttons(phone_offer.reply_markup)
    await app.feed(fakes.callback(USER, FormCb(a="phone").pack()))
    await app.feed(fakes.callback(USER, FormCb(a="send").pack(), media=True))

    subs = await _submissions(app)
    assert [s.screenshot_file_id for s in subs] == ["SCREEN-1", "SCREEN-2"]
    assert subs[1].full_name == "Aziza Karimova" and subs[1].phone == "+998901234567"


async def test_half_filled_form_survives_a_restart(app, session_factory):
    """The FSM lives in MySQL: swapping in a fresh storage object (as a restart would)
    keeps the client mid-form."""
    from bot.fsm.mysql_storage import MySQLStorage

    await start_as_new_user(app)
    await app.feed(fakes.message(USER, photo=True, file_id="SCREEN-R"))

    app.dp.fsm.storage = MySQLStorage(session_factory)  # "restart"
    await app.feed(fakes.message(USER, text="Aziza Karimova"))
    await app.feed(fakes.message(USER, text="901234567"))
    await app.feed(fakes.callback(USER, FormCb(a="send").pack(), media=True))
    [sub] = await _submissions(app)
    assert sub.screenshot_file_id == "SCREEN-R"


async def test_submission_count_query_sanity(app):
    async with app.session_factory() as s:
        assert (await s.execute(select(func.count()).select_from(Submission))).scalar_one() == 0
