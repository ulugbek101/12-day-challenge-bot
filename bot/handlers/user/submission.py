"""Client side: payment screenshot -> full name -> phone -> summary -> send."""
from __future__ import annotations

import html
import logging
import re

from aiogram import Bot, F, Router
from aiogram.exceptions import TelegramBadRequest
from aiogram.fsm.context import FSMContext
from aiogram.types import CallbackQuery, Message, ReplyKeyboardRemove
from aiogram.utils.i18n import gettext as _
from sqlalchemy.ext.asyncio import AsyncSession

from bot.config import get_settings
from bot.db.models import Client, ClientStatus, ScreenshotKind
from bot.db.repositories import clients as clients_repo
from bot.db.repositories import invite_links as invite_repo
from bot.db.repositories import submissions as submissions_repo
from bot.filters.is_admin import ButtonText
from bot.keyboards import user as kb
from bot.keyboards.callbacks import AgainCb, FormCb
from bot.keyboards.reply import BTN_SETTINGS, BTN_SUBMIT, contact_keyboard, main_keyboard
from bot.services.notifications import notify_admins
from bot.services.phone import format_phone_display, normalize_phone
from bot.states import SubmitForm

logger = logging.getLogger(__name__)
router = Router(name="user")

NAME_MIN, NAME_MAX = 2, 100


# ------------------------------------------------------------------ entry points


async def start_submission(bot: Bot, session: AsyncSession, client: Client, chat_id: int, state: FSMContext) -> None:
    """Begin (or restart) the form, unless the client's status forbids a new attempt."""
    settings = get_settings()

    if client.status == ClientStatus.pending:
        await bot.send_message(chat_id, _("⏳ Your payment is under review. We'll notify you here once it's checked."))
        return

    if client.status == ClientStatus.approved:
        invite = await invite_repo.get_current_for_client(session, client.id)
        if invite is None:
            # Approved in the DB, but no link could be created yet: to the client this
            # is indistinguishable from "still being reviewed".
            await bot.send_message(chat_id, _("⏳ Your payment has not been approved yet. Please wait — we'll notify you here."))
            return
        text = _("✅ You're already approved. Please use the personal invite link we sent you.")
        if settings.support_username:
            text += "\n" + _("Need help? Contact @{support}").format(support=html.escape(settings.support_username.lstrip("@")))
        await bot.send_message(chat_id, text)
        return

    await state.clear()
    if client.status == ClientStatus.rejected:
        previous = await submissions_repo.get_latest_for_client(session, client.id)
        if previous is not None:
            await state.update_data(prev_name=previous.full_name, prev_phone=previous.phone)

    await state.set_state(SubmitForm.screenshot)
    await bot.send_message(
        chat_id,
        _(
            "💳 <b>How to pay</b>\n\n"
            "1. Open the payment page below and pay by card transfer.\n"
            "2. Take a screenshot of the successful payment.\n"
            "3. Send the screenshot or receipt (photo, image file or PDF) here 👇"
        ),
        reply_markup=kb.payment_page_keyboard(settings.payment_page_url),
    )


@router.message(ButtonText(BTN_SUBMIT))
async def on_submit_button(message: Message, bot: Bot, session: AsyncSession, client: Client, state: FSMContext) -> None:
    await start_submission(bot, session, client, message.chat.id, state)


@router.callback_query(AgainCb.filter())
async def on_submit_again(callback: CallbackQuery, bot: Bot, session: AsyncSession, client: Client, state: FSMContext) -> None:
    await callback.answer()
    await start_submission(bot, session, client, callback.message.chat.id, state)


@router.message(ButtonText(BTN_SETTINGS))
async def on_settings_button(message: Message) -> None:
    await message.answer(_("🌐 Choose your language:"), reply_markup=kb.language_keyboard("u"))


# ------------------------------------------------------------------ step 1: screenshot


@router.message(SubmitForm.screenshot, F.photo)
async def on_screenshot_photo(message: Message, state: FSMContext) -> None:
    await _accept_screenshot(message, state, message.photo[-1].file_id, ScreenshotKind.photo)


@router.message(SubmitForm.screenshot, F.document)
async def on_screenshot_document(message: Message, state: FSMContext) -> None:
    mime = message.document.mime_type or ""
    if not (mime.startswith("image/") or mime == "application/pdf") or message.animation is not None:
        await message.answer(_("⚠️ Please send the payment screenshot or receipt as a photo, an image file or a PDF."))
        return
    await _accept_screenshot(message, state, message.document.file_id, ScreenshotKind.document)


@router.message(SubmitForm.screenshot)
async def on_screenshot_invalid(message: Message) -> None:
    await message.answer(_("⚠️ Please send the payment screenshot or receipt as a photo, an image file or a PDF."))


async def _accept_screenshot(message: Message, state: FSMContext, file_id: str, kind: ScreenshotKind) -> None:
    await state.update_data(screenshot_file_id=file_id, screenshot_kind=kind.value)
    await state.set_state(SubmitForm.full_name)
    data = await state.get_data()
    prev_name = data.get("prev_name")
    markup = kb.reuse_keyboard("name", prev_name) if prev_name else kb.cancel_keyboard()
    await message.answer(_("✍️ Enter your full name (first and last name):"), reply_markup=markup)


# ------------------------------------------------------------------ step 2: full name


@router.message(SubmitForm.full_name, F.text)
async def on_full_name(message: Message, state: FSMContext) -> None:
    name = re.sub(r"\s+", " ", message.text).strip()
    if not NAME_MIN <= len(name) <= NAME_MAX:
        await message.answer(_("⚠️ The name must be 2 to 100 characters long. Please try again:"))
        return
    await _accept_name(message.chat.id, message.bot, state, name)


@router.callback_query(SubmitForm.full_name, FormCb.filter(F.a == "name"))
async def on_reuse_name(callback: CallbackQuery, bot: Bot, state: FSMContext) -> None:
    await callback.answer()
    data = await state.get_data()
    if not data.get("prev_name"):
        return
    await _drop_markup(callback)
    await _accept_name(callback.message.chat.id, bot, state, data["prev_name"])


@router.message(SubmitForm.full_name)
async def on_full_name_invalid(message: Message) -> None:
    await message.answer(_("⚠️ Please type your full name as text."))


async def _accept_name(chat_id: int, bot: Bot, state: FSMContext, name: str) -> None:
    await state.update_data(full_name=name)
    await state.set_state(SubmitForm.phone)
    await bot.send_message(
        chat_id,
        _(
            "📞 Send your phone number: tap “Share my contact” below, "
            "or type it, e.g. +998 90 123 45 67"
        ),
        reply_markup=contact_keyboard(),
    )
    data = await state.get_data()
    if data.get("prev_phone"):
        await bot.send_message(
            chat_id,
            _("Or use the number from your previous attempt:"),
            reply_markup=kb.reuse_keyboard("phone", format_phone_display(data["prev_phone"])),
        )


# ------------------------------------------------------------------ step 3: phone


@router.message(SubmitForm.phone, F.contact)
async def on_phone_contact(message: Message, state: FSMContext) -> None:
    if message.contact.user_id != message.from_user.id:
        await message.answer(_("⚠️ Please share your own contact using the button, or type your number."))
        return
    phone = normalize_phone(message.contact.phone_number)
    if phone is None:
        await message.answer(_("⚠️ Only Uzbekistan numbers are accepted. Please type a number like +998 90 123 45 67"))
        return
    await _accept_phone(message.chat.id, message.bot, state, phone)


@router.message(SubmitForm.phone, F.text)
async def on_phone_text(message: Message, state: FSMContext) -> None:
    phone = normalize_phone(message.text)
    if phone is None:
        await message.answer(
            _("⚠️ This doesn't look like an Uzbekistan phone number. Please send it like +998 90 123 45 67")
        )
        return
    await _accept_phone(message.chat.id, message.bot, state, phone)


@router.callback_query(SubmitForm.phone, FormCb.filter(F.a == "phone"))
async def on_reuse_phone(callback: CallbackQuery, bot: Bot, state: FSMContext) -> None:
    await callback.answer()
    data = await state.get_data()
    if not data.get("prev_phone"):
        return
    await _drop_markup(callback)
    await _accept_phone(callback.message.chat.id, bot, state, data["prev_phone"])


@router.message(SubmitForm.phone)
async def on_phone_invalid(message: Message) -> None:
    await message.answer(_("⚠️ Please share your contact or type your phone number."))


async def _accept_phone(chat_id: int, bot: Bot, state: FSMContext, phone: str) -> None:
    await state.update_data(phone=phone)
    await state.set_state(SubmitForm.confirm)
    data = await state.get_data()
    await bot.send_message(chat_id, _("📋 Please check your details:"), reply_markup=ReplyKeyboardRemove())
    caption = _(
        "<b>Your submission</b>\n\n"
        "👤 Full name: {name}\n"
        "📞 Phone: {phone}\n\n"
        "Is everything correct?"
    ).format(name=html.escape(data["full_name"]), phone=format_phone_display(phone))
    if data["screenshot_kind"] == ScreenshotKind.photo.value:
        await bot.send_photo(chat_id, data["screenshot_file_id"], caption=caption, reply_markup=kb.summary_keyboard())
    else:
        await bot.send_document(chat_id, data["screenshot_file_id"], caption=caption, reply_markup=kb.summary_keyboard())


# ------------------------------------------------------------------ step 4: confirm


@router.callback_query(SubmitForm.confirm, FormCb.filter(F.a == "send"))
async def on_send(callback: CallbackQuery, bot: Bot, session: AsyncSession, client: Client, state: FSMContext) -> None:
    await callback.answer()
    data = await state.get_data()
    required = ("screenshot_file_id", "screenshot_kind", "full_name", "phone")
    if client.status == ClientStatus.pending or not all(data.get(k) for k in required):
        await state.clear()
        await _drop_markup(callback)
        await callback.message.answer(
            _("⏳ Your payment is under review. We'll notify you here once it's checked."),
            reply_markup=main_keyboard(is_admin=False),
        )
        return

    # Clear first: with per-user event isolation a second tap on "Send" will
    # find no active form and be ignored instead of creating a duplicate.
    await state.clear()
    submission = await submissions_repo.create(
        session,
        client_id=client.id,
        full_name=data["full_name"],
        phone=data["phone"],
        screenshot_file_id=data["screenshot_file_id"],
        screenshot_kind=ScreenshotKind(data["screenshot_kind"]),
    )
    await clients_repo.set_status(session, client.id, ClientStatus.pending)
    await session.commit()
    logger.info(
        "Submission created: submission=%s client=%s tg=%s", submission.id, client.id, callback.from_user.id
    )

    try:
        await callback.message.edit_caption(
            caption=callback.message.html_text + "\n\n" + _("✅ Sent for review"), reply_markup=None
        )
    except TelegramBadRequest:
        await _drop_markup(callback)
    await callback.message.answer(
        _("✅ Thank you! Your payment has been sent for review. We'll notify you here."),
        reply_markup=main_keyboard(is_admin=False),
    )

    name = submission.full_name
    await notify_admins(
        bot,
        session,
        client_id=client.id,
        build=lambda: _("🆕 {name} — new payment to review").format(name=html.escape(name)),
    )


@router.callback_query(FormCb.filter(F.a == "restart"))
async def on_restart(callback: CallbackQuery, bot: Bot, session: AsyncSession, client: Client, state: FSMContext) -> None:
    await callback.answer()
    await _drop_markup(callback)
    await callback.message.answer(_("🔄 Let's start over."), reply_markup=main_keyboard(is_admin=False))
    await start_submission(bot, session, client, callback.message.chat.id, state)


@router.callback_query(FormCb.filter(F.a == "cancel"))
async def on_cancel(callback: CallbackQuery, state: FSMContext) -> None:
    await callback.answer()
    await state.clear()
    await _drop_markup(callback)
    await callback.message.answer(_("❌ Submission cancelled."), reply_markup=main_keyboard(is_admin=False))


@router.callback_query(FormCb.filter())
async def on_stale_form_button(callback: CallbackQuery) -> None:
    """Buttons from a form that already finished (e.g. a double tap on "Send")."""
    await callback.answer(_("This form is no longer active."))


@router.message(SubmitForm.confirm)
async def on_confirm_text(message: Message) -> None:
    await message.answer(_("Please use the buttons under your submission: ✅ Send or 🔄 Start over."))


@router.message()
async def on_anything_else(message: Message) -> None:
    await message.answer(_("Please use the buttons below 👇"), reply_markup=main_keyboard(is_admin=False))


async def _drop_markup(callback: CallbackQuery) -> None:
    try:
        await callback.message.edit_reply_markup(reply_markup=None)
    except TelegramBadRequest:
        pass
