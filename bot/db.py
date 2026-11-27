import os

import aiosqlite

from .utils import now

SCHEMA = """
CREATE TABLE IF NOT EXISTS users (
    id          INTEGER PRIMARY KEY AUTOINCREMENT,
    tg_id       INTEGER UNIQUE,
    username    TEXT UNIQUE,
    role        TEXT NOT NULL CHECK (role IN ('owner', 'admin', 'worker')),
    nick        TEXT,
    percent     REAL NOT NULL DEFAULT 50,
    added_by    INTEGER,
    created_at  INTEGER NOT NULL
);
CREATE TABLE IF NOT EXISTS requisites (
    id          INTEGER PRIMARY KEY AUTOINCREMENT,
    iban        TEXT NOT NULL,
    holder      TEXT NOT NULL,
    ipn         TEXT NOT NULL,
    comment     TEXT,
    is_active   INTEGER NOT NULL DEFAULT 1,
    created_by  INTEGER REFERENCES users(id) ON DELETE SET NULL,
    created_at  INTEGER NOT NULL
);
CREATE TABLE IF NOT EXISTS clients (
    id           INTEGER PRIMARY KEY AUTOINCREMENT,
    name         TEXT NOT NULL,
    phone        TEXT,
    worker_id    INTEGER REFERENCES users(id) ON DELETE SET NULL,
    requisite_id INTEGER REFERENCES requisites(id) ON DELETE SET NULL,
    status       TEXT NOT NULL DEFAULT 'work',
    created_by   INTEGER REFERENCES users(id) ON DELETE SET NULL,
    created_at   INTEGER NOT NULL
);
CREATE TABLE IF NOT EXISTS comments (
    id          INTEGER PRIMARY KEY AUTOINCREMENT,
    client_id   INTEGER NOT NULL REFERENCES clients(id) ON DELETE CASCADE,
    author_id   INTEGER REFERENCES users(id) ON DELETE SET NULL,
    text        TEXT NOT NULL,
    created_at  INTEGER NOT NULL
);
CREATE TABLE IF NOT EXISTS payments (
    id             INTEGER PRIMARY KEY AUTOINCREMENT,
    client_id      INTEGER REFERENCES clients(id) ON DELETE SET NULL,
    client_name    TEXT,
    requisite_id   INTEGER REFERENCES requisites(id) ON DELETE SET NULL,
    worker_id      INTEGER REFERENCES users(id) ON DELETE SET NULL,
    amount         INTEGER NOT NULL,
    file_id        TEXT NOT NULL,
    file_type      TEXT NOT NULL,
    status         TEXT NOT NULL DEFAULT 'pending',
    worker_percent REAL,
    submitted_by   INTEGER REFERENCES users(id) ON DELETE SET NULL,
    submitted_at   INTEGER NOT NULL,
    reviewed_by    INTEGER REFERENCES users(id) ON DELETE SET NULL,
    reviewed_at    INTEGER
);
CREATE INDEX IF NOT EXISTS idx_pay_status ON payments(status, reviewed_at);
CREATE INDEX IF NOT EXISTS idx_clients_worker ON clients(worker_id);
CREATE TABLE IF NOT EXISTS audit (
    id          INTEGER PRIMARY KEY AUTOINCREMENT,
    user_id     INTEGER REFERENCES users(id) ON DELETE SET NULL,
    text        TEXT NOT NULL,
    created_at  INTEGER NOT NULL
);
CREATE TABLE IF NOT EXISTS settings (
    key   TEXT PRIMARY KEY,
    value TEXT
);
CREATE TABLE IF NOT EXISTS fsm (
    key   TEXT PRIMARY KEY,
    state TEXT,
    data  TEXT
);
"""


class DB:
    def __init__(self, path: str):
        self.path = path
        self.conn: aiosqlite.Connection | None = None
        self.dirty = False

    async def connect(self) -> None:
        self.conn = await aiosqlite.connect(self.path)
        self.conn.row_factory = aiosqlite.Row
        await self.conn.execute("PRAGMA foreign_keys = ON")
        await self.conn.executescript(SCHEMA)
        await self.conn.commit()

    async def close(self) -> None:
        if self.conn:
            await self.conn.close()

    async def one(self, sql: str, *params):
        async with self.conn.execute(sql, params) as cur:
            return await cur.fetchone()

    async def all(self, sql: str, *params):
        async with self.conn.execute(sql, params) as cur:
            return await cur.fetchall()

    async def run(self, sql: str, *params) -> aiosqlite.Cursor:
        cur = await self.conn.execute(sql, params)
        await self.conn.commit()
        self.dirty = True
        return cur

    async def snapshot(self, dest: str) -> None:
        if os.path.exists(dest):
            os.remove(dest)
        await self.conn.execute("VACUUM INTO ?", (dest,))

    async def get_setting(self, key: str) -> str | None:
        row = await self.one("SELECT value FROM settings WHERE key=?", key)
        return row["value"] if row else None

    async def set_setting(self, key: str, value: str) -> None:
        await self.run(
            "INSERT INTO settings(key, value) VALUES (?, ?) "
            "ON CONFLICT(key) DO UPDATE SET value=excluded.value",
            key, value,
        )

    async def audit(self, user_id: int | None, text: str) -> None:
        await self.run(
            "INSERT INTO audit(user_id, text, created_at) VALUES (?, ?, ?)",
            user_id, text, now(),
        )

    async def get_user(self, user_id: int | None):
        if user_id is None:
            return None
        return await self.one("SELECT * FROM users WHERE id=?", user_id)
