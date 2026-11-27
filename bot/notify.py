import asyncio
import logging

from aiogram import Bot
from aiogram.exceptions import TelegramAPIError
from aiogram.types import InlineKeyboardMarkup

from .db import DB

log = logging.getLogger(__name__)


async def send_safe(bot: Bot, chat_id: int, text: str, reply_markup=None) -> None:
    try:
        await bot.send_message(chat_id, text, reply_markup=reply_markup)
    except TelegramAPIError as e:
        log.warning("send to %s failed: %s", chat_id, type(e).__name__)


async def send_file_safe(bot: Bot, chat_id: int, file_id: str, file_type: str,
                         caption: str, reply_markup: InlineKeyboardMarkup | None = None) -> None:
    try:
        if file_type == "photo":
            await bot.send_photo(chat_id, file_id, caption=caption, reply_markup=reply_markup)
        else:
            await bot.send_document(chat_id, file_id, caption=caption, reply_markup=reply_markup)
    except TelegramAPIError as e:
        log.warning("send file to %s failed: %s", chat_id, type(e).__name__)


async def admin_chat_ids(db: DB, exclude_user_id: int | None = None) -> list[int]:
    rows = await db.all(
        "SELECT id, tg_id FROM users WHERE role IN ('owner','admin') AND tg_id IS NOT NULL"
    )
    return [r["tg_id"] for r in rows if r["id"] != exclude_user_id]


async def notify_admins(bot: Bot, db: DB, text: str, exclude_user_id: int | None = None,
                        reply_markup=None) -> None:
    for chat_id in await admin_chat_ids(db, exclude_user_id):
        await send_safe(bot, chat_id, text, reply_markup)
        await asyncio.sleep(0.05)


async def notify_user(bot: Bot, db: DB, user_id: int | None, text: str, reply_markup=None) -> None:
    user = await db.get_user(user_id)
    if user and user["tg_id"]:
        await send_safe(bot, user["tg_id"], text, reply_markup)


async def notify_all(bot: Bot, db: DB, text: str, exclude_user_id: int | None = None) -> None:
    rows = await db.all("SELECT id, tg_id FROM users WHERE tg_id IS NOT NULL AND nick IS NOT NULL")
    for r in rows:
        if r["id"] != exclude_user_id:
            await send_safe(bot, r["tg_id"], text)
            await asyncio.sleep(0.05)
