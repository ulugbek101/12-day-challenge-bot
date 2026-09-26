from __future__ import annotations

from aiogram.types import KeyboardButton, ReplyKeyboardMarkup
from aiogram.utils.i18n import gettext as _

from bot.i18n import N_

BTN_SUBMIT = N_("💳 Submit payment")
BTN_SETTINGS = N_("⚙️ Settings")
BTN_ADMIN_PANEL = N_("🗂 Admin panel")
BTN_SHARE_CONTACT = N_("📱 Share my contact")


def main_keyboard(*, is_admin: bool) -> ReplyKeyboardMarkup:
    first = _(BTN_ADMIN_PANEL) if is_admin else _(BTN_SUBMIT)
    return ReplyKeyboardMarkup(
        keyboard=[[KeyboardButton(text=first), KeyboardButton(text=_(BTN_SETTINGS))]],
        resize_keyboard=True,
        is_persistent=True,
    )


def contact_keyboard() -> ReplyKeyboardMarkup:
    return ReplyKeyboardMarkup(
        keyboard=[[KeyboardButton(text=_(BTN_SHARE_CONTACT), request_contact=True)]],
        resize_keyboard=True,
        one_time_keyboard=True,
    )
