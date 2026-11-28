import asyncio
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
CREATE INDEX IF NOT EXISTS idx_pay_client ON payments(client_id);
CREATE INDEX IF NOT EXISTS idx_pay_worker ON payments(worker_id, status, reviewed_at);
CREATE INDEX IF NOT EXISTS idx_pay_req ON payments(requisite_id, status, reviewed_at);
CREATE INDEX IF NOT EXISTS idx_clients_worker ON clients(worker_id);
CREATE INDEX IF NOT EXISTS idx_clients_req ON clients(requisite_id);
CREATE INDEX IF NOT EXISTS idx_comments_client ON comments(client_id);
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


# Изменения схемы для уже существующих баз. Только добавлять в конец!
MIGRATIONS = [
    # 1: подтверждение новых сотрудников админом
    "ALTER TABLE users ADD COLUMN approved INTEGER NOT NULL DEFAULT 1",
    # 2: доля сотрудника фиксируется в копейках при подтверждении
    "ALTER TABLE payments ADD COLUMN worker_share INTEGER;"
    "UPDATE payments SET worker_share = CAST(amount * COALESCE(worker_percent, 0) / 100.0 + 0.5 AS INTEGER) "
    "WHERE status='confirmed';",
    # 3: снимок реквизита в оплате (чтобы отчёт не терял его после удаления)
    "ALTER TABLE payments ADD COLUMN requisite_label TEXT;"
    "UPDATE payments SET requisite_label = (SELECT iban || ' (' || holder || ')' FROM requisites r "
    "WHERE r.id = payments.requisite_id);",
    # 4: кому уже отправлен итог дня (защита от дублей)
    "CREATE TABLE IF NOT EXISTS daily_sent (day TEXT NOT NULL, tg_id INTEGER NOT NULL, PRIMARY KEY (day, tg_id));",
    # 5: «одно окно» — какое сообщение бота сейчас экран пользователя и какие временные сообщения убрать
    "CREATE TABLE IF NOT EXISTS ui (tg_id INTEGER PRIMARY KEY, screen_id INTEGER, aux TEXT NOT NULL DEFAULT '[]');",
    # 6: заработок по текущим процентам (правило: смена процента пересчитывает всё), точное округление,
    #    «Оплачено» только с квитанцией, индексы
    "UPDATE payments SET worker_percent=(SELECT percent FROM users u WHERE u.id=payments.worker_id) "
    "WHERE status='confirmed' AND worker_id IS NOT NULL;"
    "UPDATE payments SET worker_share=(amount * CAST(ROUND(COALESCE(worker_percent, 0) * 100) AS INTEGER) + 5000) / 10000 WHERE status='confirmed';"
    "UPDATE clients SET status='work' WHERE status='paid' AND NOT EXISTS "
    "(SELECT 1 FROM payments p WHERE p.client_id=clients.id AND p.status IN ('pending','confirmed'));"
    "CREATE INDEX IF NOT EXISTS idx_audit_user ON audit(user_id);"
    "CREATE INDEX IF NOT EXISTS idx_pay_sub ON payments(submitted_by);"
    "CREATE INDEX IF NOT EXISTS idx_pay_rev ON payments(reviewed_by);"
    "CREATE INDEX IF NOT EXISTS idx_clients_created ON clients(created_at);",
]


def _lower(value):
    return value.lower() if isinstance(value, str) else value


class DB:
    """Одно соединение в режиме autocommit, все обращения идут по очереди через lock.

    Так снимок базы (VACUUM INTO) никогда не попадает внутрь чужой транзакции.
    """

    def __init__(self, path: str):
        self.path = path
        self.conn: aiosqlite.Connection | None = None
        self.dirty = False
        self.lock = asyncio.Lock()

    async def connect(self) -> None:
        self.conn = await aiosqlite.connect(self.path, isolation_level=None)
        try:
            self.conn.row_factory = aiosqlite.Row
            await self.conn.create_function("ulower", 1, _lower, deterministic=True)
            await self.conn.execute("PRAGMA foreign_keys = ON")
            await self.conn.executescript(SCHEMA)
            async with self.conn.execute("PRAGMA user_version") as cur:
                version = (await cur.fetchone())[0]
            # Миграции — с выключенными внешними ключами: пересоздание таблиц не должно обнулять связи.
            await self.conn.execute("PRAGMA foreign_keys = OFF")
            for i, script in enumerate(MIGRATIONS[version:], start=version + 1):
                try:
                    await self.conn.executescript(
                        f"BEGIN;\n{script};\nPRAGMA user_version={int(i)};\nCOMMIT;")
                except BaseException:
                    if self.conn.in_transaction:
                        await self.conn.execute("ROLLBACK")
                    raise
                self.dirty = True
            async with self.conn.execute("PRAGMA foreign_key_check") as cur:
                if await cur.fetchone():
                    raise SystemExit("Нарушены связи в базе после миграции")
            await self.conn.execute("PRAGMA foreign_keys = ON")
            # уборка «осиротевших» служебных строк
            await self.conn.execute("DELETE FROM ui WHERE tg_id NOT IN (SELECT tg_id FROM users WHERE tg_id IS NOT NULL)")
            await self.conn.execute("DELETE FROM fsm WHERE state IS NULL AND (data IS NULL OR data='{}')")
            async with self.conn.execute("PRAGMA quick_check") as cur:
                if (await cur.fetchone())[0] != "ok":
                    raise SystemExit("База данных повреждена (quick_check)")
        except BaseException:
            await self.conn.close()
            self.conn = None
            raise

    async def close(self) -> None:
        if self.conn:
            async with self.lock:
                await self.conn.close()
                self.conn = None

    async def one(self, sql: str, *params):
        async with self.lock:
            async with self.conn.execute(sql, params) as cur:
                return await cur.fetchone()

    async def all(self, sql: str, *params):
        async with self.lock:
            async with self.conn.execute(sql, params) as cur:
                return await cur.fetchall()

    async def run(self, sql: str, *params) -> aiosqlite.Cursor:
        async with self.lock:
            cur = await self.conn.execute(sql, params)
        self.dirty = True
        return cur

    async def run_many(self, statements: list[tuple]) -> list[aiosqlite.Cursor]:
        """Несколько изменений одной транзакцией: либо все, либо ничего. Возвращает курсоры (rowcount/lastrowid).
        Внутри нельзя вызывать другие методы DB — замок не реентерабельный."""
        async with self.lock:
            await self.conn.execute("BEGIN")
            try:
                curs = []
                for sql, *params in statements:
                    curs.append(await self.conn.execute(sql, params))
                await self.conn.execute("COMMIT")
            except BaseException:
                await self.conn.execute("ROLLBACK")
                raise
        self.dirty = True
        return curs

    async def snapshot(self, dest: str) -> None:
        async with self.lock:
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
