"""Хранилище состояний диалогов в SQLite, чтобы они переживали перезапуск."""
import json
from typing import Any, Mapping

from aiogram.fsm.state import State
from aiogram.fsm.storage.base import BaseStorage, StateType, StorageKey

from .db import DB


class SQLiteStorage(BaseStorage):
    def __init__(self, db: DB):
        self.db = db

    @staticmethod
    def _key(key: StorageKey) -> str:
        return ":".join(
            str(x)
            for x in (
                key.bot_id,
                key.chat_id,
                key.user_id,
                getattr(key, "thread_id", None),
                getattr(key, "business_connection_id", None),
                key.destiny,
            )
        )

    async def set_state(self, key: StorageKey, state: StateType = None) -> None:
        value = state.state if isinstance(state, State) else state
        row = await self.db.one("SELECT state FROM fsm WHERE key=?", self._key(key))
        if (row["state"] if row else None) == value:
            return  # ничего не изменилось — не трогаем базу (и не запускаем сохранение)
        await self.db.run(
            "INSERT INTO fsm(key, state) VALUES (?, ?) "
            "ON CONFLICT(key) DO UPDATE SET state=excluded.state",
            self._key(key), value,
        )

    async def get_state(self, key: StorageKey) -> str | None:
        row = await self.db.one("SELECT state FROM fsm WHERE key=?", self._key(key))
        return row["state"] if row else None

    async def set_data(self, key: StorageKey, data: Mapping[str, Any]) -> None:
        payload = json.dumps(dict(data), ensure_ascii=False)
        row = await self.db.one("SELECT data FROM fsm WHERE key=?", self._key(key))
        current = row["data"] if row else None
        if current == payload or (current in (None, "{}") and payload == "{}"):
            return
        await self.db.run(
            "INSERT INTO fsm(key, data) VALUES (?, ?) "
            "ON CONFLICT(key) DO UPDATE SET data=excluded.data",
            self._key(key), payload,
        )

    async def get_data(self, key: StorageKey) -> dict[str, Any]:
        row = await self.db.one("SELECT data FROM fsm WHERE key=?", self._key(key))
        if not row or not row["data"]:
            return {}
        return json.loads(row["data"])

    async def close(self) -> None:
        pass
