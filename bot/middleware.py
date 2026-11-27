import time
from typing import Any, Awaitable, Callable

from aiogram import BaseMiddleware
from aiogram.fsm.state import State, StatesGroup
from aiogram.types import CallbackQuery, Message, ReplyKeyboardRemove, TelegramObject

from .db import DB
from .keyboards import MENU_BUTTONS, danger_btn, kb, ok_btn
from .notify import notify_admins
from .utils import ROLES, esc

PENDING_TTL = 14 * 24 * 3600  # приглашение по username действует 14 дней


class NickForm(StatesGroup):
    nick = State()


NICK_PROMPT = (
    "👋 Добро пожаловать в CRM!\n\n"
    "Для начала работы введите ваш <b>ник в CRM</b> (он будет виден в отчётах):"
)
WAIT_TEXT = "⏳ Ваш доступ ожидает подтверждения администратором. Мы сообщим, когда он будет открыт."


async def _claim_username(db: DB, username: str, user_id: int) -> None:
    """Пользователь с tg_id занял username: висящее приглашение на этот username больше
    никогда не сможет законно сработать (его некому взять), поэтому оно удаляется,
    а устаревшая запись у другого пользователя очищается."""
    await db.run("DELETE FROM users WHERE username=? AND tg_id IS NULL AND id<>?", username, user_id)
    await db.run("UPDATE users SET username=NULL WHERE username=? AND id<>?", username, user_id)
    await db.run("UPDATE users SET username=? WHERE id=?", username, user_id)


async def resolve_user(db: DB, tg_user, bot):
    username = (tg_user.username or "").lower() or None
    row = await db.one("SELECT * FROM users WHERE tg_id=?", tg_user.id)

    if row is None and username:
        pending = await db.one(
            "SELECT * FROM users WHERE username=? AND tg_id IS NULL AND created_at>?",
            username, int(time.time()) - PENDING_TTL,
        )
        if pending:
            cur = await db.run(
                "UPDATE users SET tg_id=?, approved=0 WHERE id=? AND tg_id IS NULL",
                tg_user.id, pending["id"])
            if cur.rowcount != 1:
                return await db.one("SELECT * FROM users WHERE tg_id=?", tg_user.id)
            await db.audit(pending["id"], f"Подключился к боту (@{username}), ждёт подтверждения")
            text = (
                f"🔔 <b>Запрос доступа</b>\n"
                f"{ROLES[pending['role']]} @{esc(username)}\n"
                f"Имя в Telegram: {esc(tg_user.full_name)}\n"
                f"Telegram ID: <code>{tg_user.id}</code>\n\n"
                "Убедитесь, что это нужный человек, и подтвердите доступ."
            )
            markup = kb([ok_btn("✅ Подтвердить", f"ap:ok:{pending['id']}"),
                         danger_btn("❌ Отклонить", f"ap:no:{pending['id']}")])
            await notify_admins(bot, db, text, reply_markup=markup,
                                owner_only=pending["role"] == "admin")
            row = await db.one("SELECT * FROM users WHERE id=?", pending["id"])

    if row is None:
        return None

    if username and username != row["username"]:
        await _claim_username(db, username, row["id"])
        row = await db.one("SELECT * FROM users WHERE id=?", row["id"])
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
        if chat is None or chat.type != "private":
            return None

        db: DB = data["db"]
        user = await resolve_user(db, tg_user, data["bot"])
        if user is None:
            return None
        data["user"] = user

        if not user["approved"]:
            if isinstance(event, CallbackQuery):
                await event.answer(WAIT_TEXT, show_alert=True)
            else:
                await event.answer(WAIT_TEXT, reply_markup=ReplyKeyboardRemove())
            return None

        state = data["state"]
        if not user["nick"]:
            if isinstance(event, Message) and await state.get_state() == NickForm.nick.state:
                return await handler(event, data)
            await state.set_state(NickForm.nick)
            if isinstance(event, CallbackQuery):
                await event.answer()
                await data["bot"].send_message(tg_user.id, NICK_PROMPT)
            else:
                await event.answer(NICK_PROMPT, reply_markup=ReplyKeyboardRemove())
            return None

        # Кнопка главного меню всегда прерывает текущий диалог (иначе её текст
        # попадёт в форму как ввод). Фильтры состояния читают raw_state.
        if isinstance(event, Message) and event.text in MENU_BUTTONS and data.get("raw_state"):
            await state.clear()
            data["raw_state"] = None

        return await handler(event, data)
