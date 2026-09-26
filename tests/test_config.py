import pytest

from bot.config import ConfigError, parse_admins


def test_parse_admins_basic():
    assert parse_admins("123,456") == [123, 456]


def test_parse_admins_tolerates_spaces():
    assert parse_admins(" 123 , 456 ,789") == [123, 456, 789]


def test_parse_admins_tolerates_trailing_comma():
    assert parse_admins("123,456,") == [123, 456]


def test_parse_admins_single():
    assert parse_admins("123456789") == [123456789]


def test_parse_admins_empty_raises():
    with pytest.raises(ConfigError):
        parse_admins("")


def test_parse_admins_whitespace_only_raises():
    with pytest.raises(ConfigError):
        parse_admins("   ")


def test_parse_admins_only_commas_raises():
    with pytest.raises(ConfigError):
        parse_admins(",,,")


def test_parse_admins_malformed_raises():
    with pytest.raises(ConfigError):
        parse_admins("123,abc,456")


def test_parse_admins_none_like_raises():
    with pytest.raises(ConfigError):
        parse_admins(None)  # type: ignore[arg-type]
