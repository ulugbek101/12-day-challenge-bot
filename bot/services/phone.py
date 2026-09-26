"""Uzbekistan phone number parsing, normalization and display formatting.

Accepted input (typed manually, or coming from a shared Telegram contact),
with or without spaces/dashes between groups:
  - "+998901234567"
  - "998901234567"
  - "901234567"                    (bare 9-digit local number)
  - "+998 90 123 45 67", "998-90-123-45-67", "90 123 45 67", etc.

Canonical storage:
  - `phone`            -> "+998901234567"   (used for display formatting)
  - `phone_normalized` -> "998901234567"    (digits only, used for search)
"""
from __future__ import annotations

import re

_COUNTRY_CODE = "998"
_LOCAL_LENGTH = 9  # digits after the 998 country code


def _digits(raw: str) -> str:
    return re.sub(r"\D", "", raw or "")


def normalize_phone(raw: str) -> str | None:
    """Return the canonical "+998XXXXXXXXX" form, or None if raw isn't a valid UZ number."""
    digits = _digits(raw)

    if digits.startswith(_COUNTRY_CODE) and len(digits) == len(_COUNTRY_CODE) + _LOCAL_LENGTH:
        local = digits[len(_COUNTRY_CODE):]
    elif len(digits) == _LOCAL_LENGTH:
        local = digits
    else:
        return None

    return f"+{_COUNTRY_CODE}{local}"


def digits_only(phone: str) -> str:
    """Digits-only form of an already-normalized (or raw) phone, for the search index."""
    return _digits(phone)


def format_phone_display(phone: str) -> str:
    """"+998901234567" -> "+998 90 123 45 67". Returns the input unchanged if malformed."""
    digits = _digits(phone)
    if not (digits.startswith(_COUNTRY_CODE) and len(digits) == len(_COUNTRY_CODE) + _LOCAL_LENGTH):
        return phone
    local = digits[len(_COUNTRY_CODE):]
    return f"+{_COUNTRY_CODE} {local[0:2]} {local[2:5]} {local[5:7]} {local[7:9]}"
