from __future__ import annotations

from aiogram.types import InlineKeyboardButton, InlineKeyboardMarkup
from aiogram.utils.i18n import gettext as _

from bot.keyboards.callbacks import AgainCb, FormCb, LangCb


def language_keyboard(ctx: str) -> InlineKeyboardMarkup:
    # Language names are intentionally not translated.
    return InlineKeyboardMarkup(
        inline_keyboard=[
            [
                InlineKeyboardButton(text="🇷🇺 Русский", callback_data=LangCb(lang="ru", ctx=ctx).pack()),
                InlineKeyboardButton(text="🇺🇿 O'zbekcha", callback_data=LangCb(lang="uz", ctx=ctx).pack()),
            ]
        ]
    )


def payment_page_keyboard(url: str) -> InlineKeyboardMarkup:
    return InlineKeyboardMarkup(
        inline_keyboard=[
            [InlineKeyboardButton(text=_("💳 Open payment page"), url=url)],
            [InlineKeyboardButton(text=_("❌ Cancel"), callback_data=FormCb(a="cancel").pack())],
        ]
    )


def cancel_keyboard() -> InlineKeyboardMarkup:
    return InlineKeyboardMarkup(
        inline_keyboard=[[InlineKeyboardButton(text=_("❌ Cancel"), callback_data=FormCb(a="cancel").pack())]]
    )


def reuse_keyboard(field: str, previous_label: str) -> InlineKeyboardMarkup:
    """field: "name" | "phone". Offers the value from the previous attempt."""
    return InlineKeyboardMarkup(
        inline_keyboard=[
            [
                InlineKeyboardButton(
                    text=_("Use: {value}").format(value=previous_label),
                    callback_data=FormCb(a=field).pack(),
                )
            ],
            [InlineKeyboardButton(text=_("❌ Cancel"), callback_data=FormCb(a="cancel").pack())],
        ]
    )


def summary_keyboard() -> InlineKeyboardMarkup:
    return InlineKeyboardMarkup(
        inline_keyboard=[
            [
                InlineKeyboardButton(text=_("✅ Send"), callback_data=FormCb(a="send").pack()),
                InlineKeyboardButton(text=_("🔄 Start over"), callback_data=FormCb(a="restart").pack()),
            ],
            [InlineKeyboardButton(text=_("❌ Cancel"), callback_data=FormCb(a="cancel").pack())],
        ]
    )


def submit_again_keyboard() -> InlineKeyboardMarkup:
    return InlineKeyboardMarkup(
        inline_keyboard=[[InlineKeyboardButton(text=_("🔄 Submit again"), callback_data=AgainCb().pack())]]
    )
