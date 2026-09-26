import pytest

from bot.services.phone import digits_only, format_phone_display, normalize_phone

VALID_INPUTS = [
    "+998901234567",
    "998901234567",
    "901234567",
    "+998 90 123 45 67",
    "998 90 123 45 67",
    "90 123 45 67",
    "+998-90-123-45-67",
    "998-90-123-45-67",
    "90-123-45-67",
    "+998 90-123 45-67",
    "+998(90)1234567",
]


@pytest.mark.parametrize("raw", VALID_INPUTS)
def test_normalize_phone_valid_formats(raw):
    assert normalize_phone(raw) == "+998901234567"


@pytest.mark.parametrize(
    "raw",
    [
        "",
        "12345",
        "+1 555 123 4567",
        "99890123456",  # one digit short
        "9989012345678",  # one digit too many
        "abcdefghi",
        "+998 90 123 45",  # missing a group
    ],
)
def test_normalize_phone_invalid_formats(raw):
    assert normalize_phone(raw) is None


def test_digits_only():
    assert digits_only("+998 90-123 45 67") == "998901234567"
    assert digits_only("") == ""


def test_format_phone_display():
    assert format_phone_display("+998901234567") == "+998 90 123 45 67"


def test_format_phone_display_from_raw_variant():
    normalized = normalize_phone("998-90-123-45-67")
    assert format_phone_display(normalized) == "+998 90 123 45 67"


def test_format_phone_display_returns_input_unchanged_if_malformed():
    assert format_phone_display("not-a-phone") == "not-a-phone"
