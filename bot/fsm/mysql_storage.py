"""aiogram FSM storage backed by MySQL (the fsm_storage table).

aiogram ships no MySQL storage. Without this, a half-filled client form or an
admin mid-way through typing a rejection reason or a search query would be
lost on every restart/redeploy.
"""
from __future__ import annotations

from collections.abc import Mapping
from typing import Any

from aiogram.exceptions import DataNotDictLikeError
from aiogram.fsm.state import State
from aiogram.fsm.storage.base import BaseStorage, StateType, StorageKey
from sqlalchemy.ext.asyncio import AsyncSession, async_sessionmaker

from bot.db.models import FSMRecord
from bot.services.timefmt import utcnow


def serialize_key(key: StorageKey) -> str:
    """StorageKey -> the fsm_storage.key string. Order matches the column comment."""
    return ":".join(
        str(part)
        for part in (
            key.bot_id,
            key.chat_id,
            key.user_id,
            key.thread_id,
            key.business_connection_id,
            key.destiny,
        )
    )


class MySQLStorage(BaseStorage):
    def __init__(self, session_factory: async_sessionmaker[AsyncSession]) -> None:
        self._session_factory = session_factory

    async def close(self) -> None:
        # The engine's lifecycle is owned by the app entrypoint, not this storage.
        pass

    async def set_state(self, key: StorageKey, state: StateType = None) -> None:
        raw_key = serialize_key(key)
        value = state.state if isinstance(state, State) else state
        async with self._session_factory() as session:
            record = await session.get(FSMRecord, raw_key)
            if record is None:
                session.add(FSMRecord(key=raw_key, state=value, data={}, updated_at=utcnow()))
            else:
                record.state = value
                record.updated_at = utcnow()
            await session.commit()

    async def get_state(self, key: StorageKey) -> str | None:
        raw_key = serialize_key(key)
        async with self._session_factory() as session:
            record = await session.get(FSMRecord, raw_key)
            return record.state if record is not None else None

    async def set_data(self, key: StorageKey, data: Mapping[str, Any]) -> None:
        if not isinstance(data, dict):
            msg = f"Data must be a dict or dict-like object, got {type(data).__name__}"
            raise DataNotDictLikeError(msg)
        raw_key = serialize_key(key)
        async with self._session_factory() as session:
            record = await session.get(FSMRecord, raw_key)
            if record is None:
                session.add(FSMRecord(key=raw_key, state=None, data=dict(data), updated_at=utcnow()))
            else:
                record.data = dict(data)
                record.updated_at = utcnow()
            await session.commit()

    async def get_data(self, key: StorageKey) -> dict[str, Any]:
        raw_key = serialize_key(key)
        async with self._session_factory() as session:
            record = await session.get(FSMRecord, raw_key)
            return dict(record.data) if record is not None else {}
