"""gettext-based i18n (aiogram.utils.i18n) shared by handlers and background tasks."""
from __future__ import annotations

from collections.abc import Iterator
from contextlib import contextmanager
from pathlib import Path

from aiogram.utils.i18n import I18n

LOCALES_DIR = Path(__file__).parent / "locales"
SUPPORTED_LANGUAGES = ("ru", "uz")

_i18n: I18n | None = None


def N_(message: str) -> str:
    """Mark a string for extraction without translating it (used for button labels
    that must be matched against every locale, see filters.ButtonText)."""
    return message


def setup_i18n(default_locale: str) -> I18n:
    global _i18n
    _i18n = I18n(path=LOCALES_DIR, default_locale=default_locale, domain="messages")
    return _i18n


def get_i18n() -> I18n:
    if _i18n is None:
        raise RuntimeError("i18n is not initialised; call setup_i18n() at startup")
    return _i18n


@contextmanager
def in_locale(locale: str | None) -> Iterator[None]:
    """Translate in a specific user's language outside of their own update
    (e.g. notifying a client from an admin's action, or from the reminder task)."""
    i18n = get_i18n()
    with i18n.context(), i18n.use_locale(locale or i18n.default_locale):
        yield


def all_translations(msgid: str) -> set[str]:
    """Every localized form of msgid, so reply-keyboard taps match regardless of
    which language the keyboard was rendered in."""
    i18n = get_i18n()
    return {i18n.gettext(msgid, locale=locale) for locale in SUPPORTED_LANGUAGES}
