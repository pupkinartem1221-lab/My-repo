import sqlite3
from typing import Any, Awaitable, Callable

from aiogram import BaseMiddleware
from aiogram.fsm.state import State, StatesGroup
from aiogram.types import CallbackQuery, Message, ReplyKeyboardRemove, TelegramObject

from .db import DB
from .notify import notify_admins
from .utils import ROLES, esc


class NickForm(StatesGroup):
    nick = State()


NICK_PROMPT = (
    "👋 Добро пожаловать в CRM!\n\n"
    "Для начала работы введите ваш <b>ник в CRM</b> (он будет виден в отчётах):"
)


async def resolve_user(db: DB, owner_id: int, tg_user, bot):
    username = (tg_user.username or "").lower() or None
    row = await db.one("SELECT * FROM users WHERE tg_id=?", tg_user.id)

    if row is None and username:
        pending = await db.one(
            "SELECT * FROM users WHERE username=? AND tg_id IS NULL", username
        )
        if pending:
            await db.run("UPDATE users SET tg_id=? WHERE id=?", tg_user.id, pending["id"])
            await db.audit(pending["id"], f"Подключился к боту (@{username})")
            await notify_admins(
                bot, db,
                f"🔌 {ROLES[pending['role']]} @{esc(username)} подключился к боту.",
                exclude_user_id=pending["id"],
            )
            row = await db.one("SELECT * FROM users WHERE id=?", pending["id"])

    if row is None:
        return None

    if username and username != row["username"]:
        try:
            await db.run("UPDATE users SET username=? WHERE id=?", username, row["id"])
            row = await db.one("SELECT * FROM users WHERE id=?", row["id"])
        except sqlite3.IntegrityError:
            pass
    return row


class AccessMiddleware(BaseMiddleware):
    """Пускает только сотрудников из базы. Остальным бот не отвечает вообще."""

    async def __call__(
        self,
        handler: Callable[[TelegramObject, dict[str, Any]], Awaitable[Any]],
        event: TelegramObject,
        data: dict[str, Any],
    ) -> Any:
        tg_user = data.get("event_from_user")
        chat = data.get("event_chat")
        if tg_user is None or tg_user.is_bot:
            return None
        if chat is not None and chat.type != "private":
            return None

        db: DB = data["db"]
        user = await resolve_user(db, data["cfg"].owner_id, tg_user, data["bot"])
        if user is None:
            return None
        data["user"] = user

        if not user["nick"]:
            state = data["state"]
            if isinstance(event, Message) and await state.get_state() == NickForm.nick.state:
                return await handler(event, data)
            await state.set_state(NickForm.nick)
            if isinstance(event, CallbackQuery):
                await event.answer()
                if event.message:
                    await event.message.answer(NICK_PROMPT)
            else:
                await event.answer(NICK_PROMPT, reply_markup=ReplyKeyboardRemove())
            return None

        return await handler(event, data)
