"""All CallbackData factories. Short prefixes and ids only: Telegram caps
callback_data at 64 bytes."""
from __future__ import annotations

from aiogram.filters.callback_data import CallbackData


class LangCb(CallbackData, prefix="lg"):
    lang: str  # ru | uz
    ctx: str  # s = first /start, u = user settings, a = admin panel


class FormCb(CallbackData, prefix="f"):
    a: str  # send | restart | cancel | name | phone  (name/phone = reuse previous value)


class AgainCb(CallbackData, prefix="ag"):
    pass


class MenuCb(CallbackData, prefix="m"):
    a: str  # home | search | settings


class ListCb(CallbackData, prefix="l"):
    st: str  # p | a | r
    p: int


class SearchCb(CallbackData, prefix="s"):
    a: str  # page | again | cancel
    p: int = 1


class CardCb(CallbackData, prefix="c"):
    # open | ap | apy | apn | rj | rjy | rjn | rjc | gen | rgen | rs
    a: str
    cid: int
    sid: int = 0
    src: str = "p"  # p | a | r | s : where the card was opened from, for "Back"
    p: int = 1


class HistCb(CallbackData, prefix="h"):
    cid: int
    i: int  # attempt index, 0 = newest
    src: str
    p: int


class NoticeCb(CallbackData, prefix="n"):
    cid: int


class RetryReasonCb(CallbackData, prefix="rr"):
    cid: int
    mid: int  # id of the admin's reason message, to copy_message it again
