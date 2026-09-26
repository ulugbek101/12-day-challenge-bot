import pytest
from aiogram.exceptions import DataNotDictLikeError
from aiogram.fsm.state import State, StatesGroup
from aiogram.fsm.storage.base import StorageKey

from bot.fsm.mysql_storage import MySQLStorage


class Form(StatesGroup):
    step_one = State()


def make_key(**overrides) -> StorageKey:
    defaults = dict(bot_id=1, chat_id=100, user_id=100, thread_id=None, destiny="default")
    defaults.update(overrides)
    return StorageKey(**defaults)


async def test_get_state_unknown_key_returns_none(session_factory):
    storage = MySQLStorage(session_factory)
    assert await storage.get_state(make_key()) is None


async def test_set_and_get_state_with_plain_string(session_factory):
    storage = MySQLStorage(session_factory)
    key = make_key()
    await storage.set_state(key, "step_one")
    assert await storage.get_state(key) == "step_one"


async def test_set_state_accepts_state_object(session_factory):
    storage = MySQLStorage(session_factory)
    key = make_key()
    await storage.set_state(key, Form.step_one)
    assert await storage.get_state(key) == Form.step_one.state


async def test_set_state_none_clears_it(session_factory):
    storage = MySQLStorage(session_factory)
    key = make_key()
    await storage.set_state(key, "step_one")
    await storage.set_state(key, None)
    assert await storage.get_state(key) is None


async def test_get_data_unknown_key_returns_empty_dict(session_factory):
    storage = MySQLStorage(session_factory)
    assert await storage.get_data(make_key()) == {}


async def test_set_and_get_data_roundtrip(session_factory):
    storage = MySQLStorage(session_factory)
    key = make_key()
    await storage.set_data(key, {"full_name": "Aziza Karimova", "attempt": 2})
    assert await storage.get_data(key) == {"full_name": "Aziza Karimova", "attempt": 2}


async def test_set_data_rejects_non_dict(session_factory):
    storage = MySQLStorage(session_factory)
    with pytest.raises(DataNotDictLikeError):
        await storage.set_data(make_key(), ["not", "a", "dict"])  # type: ignore[arg-type]


async def test_update_data_merges(session_factory):
    storage = MySQLStorage(session_factory)
    key = make_key()
    await storage.set_data(key, {"a": 1})
    result = await storage.update_data(key, {"b": 2})
    assert result == {"a": 1, "b": 2}
    assert await storage.get_data(key) == {"a": 1, "b": 2}


async def test_get_value_helper(session_factory):
    storage = MySQLStorage(session_factory)
    key = make_key()
    await storage.set_data(key, {"a": 1})
    assert await storage.get_value(key, "a") == 1
    assert await storage.get_value(key, "missing", "fallback") == "fallback"


async def test_different_keys_do_not_clash(session_factory):
    storage = MySQLStorage(session_factory)
    key_a = make_key(user_id=1)
    key_b = make_key(user_id=2)
    await storage.set_state(key_a, "state_a")
    await storage.set_data(key_a, {"who": "a"})
    assert await storage.get_state(key_b) is None
    assert await storage.get_data(key_b) == {}
    assert await storage.get_state(key_a) == "state_a"
    assert await storage.get_data(key_a) == {"who": "a"}


async def test_destiny_isolates_state_for_same_user(session_factory):
    """An admin typing a rejection reason (destiny=admin_input) shouldn't affect
    that same admin's own client-side FSM state (destiny=default)."""
    storage = MySQLStorage(session_factory)
    default_key = make_key(destiny="default")
    admin_key = make_key(destiny="admin_input")
    await storage.set_state(default_key, "browsing")
    await storage.set_state(admin_key, "reject_reason")
    assert await storage.get_state(default_key) == "browsing"
    assert await storage.get_state(admin_key) == "reject_reason"


async def test_data_survives_a_new_storage_instance(session_factory):
    """Simulates a bot restart: a fresh MySQLStorage object still sees old data,
    because it's backed by the same MySQL table, not in-memory state."""
    key = make_key()
    first_instance = MySQLStorage(session_factory)
    await first_instance.set_state(key, "mid_form")
    await first_instance.set_data(key, {"screenshot_file_id": "AgAD123"})

    second_instance = MySQLStorage(session_factory)
    assert await second_instance.get_state(key) == "mid_form"
    assert await second_instance.get_data(key) == {"screenshot_file_id": "AgAD123"}


async def test_close_does_not_raise(session_factory):
    storage = MySQLStorage(session_factory)
    await storage.close()
