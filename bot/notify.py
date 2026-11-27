import asyncio
import logging

from aiogram import Bot
from aiogram.exceptions import (
    TelegramAPIError,
    TelegramForbiddenError,
    TelegramNetworkError,
    TelegramRetryAfter,
)
from aiogram.types import InlineKeyboardMarkup

from .db import DB

log = logging.getLogger(__name__)


async def _deliver(factory) -> bool:
    """Отправка с повтором при лимитах Telegram. В лог не пишутся ни ID, ни тексты."""
    for attempt in range(4):
        try:
            await factory()
            return True
        except TelegramRetryAfter as e:
            await asyncio.sleep(e.retry_after + 1)
        except TelegramNetworkError:
            await asyncio.sleep(2 * (attempt + 1))
        except TelegramForbiddenError:
            log.info("Получатель заблокировал бота")
            return False
        except TelegramAPIError as e:
            log.warning("Не удалось отправить сообщение: %s", type(e).__name__)
            return False
    log.warning("Не удалось отправить сообщение после повторов")
    return False


async def send_safe(bot: Bot, chat_id: int, text: str, reply_markup=None) -> bool:
    return await _deliver(lambda: bot.send_message(chat_id, text, reply_markup=reply_markup))


async def send_file_safe(bot: Bot, chat_id: int, file_id: str, file_type: str,
                         caption: str, reply_markup: InlineKeyboardMarkup | None = None) -> bool:
    if file_type == "photo":
        return await _deliver(lambda: bot.send_photo(chat_id, file_id, caption=caption,
                                                     reply_markup=reply_markup))
    return await _deliver(lambda: bot.send_document(chat_id, file_id, caption=caption,
                                                    reply_markup=reply_markup))


async def admin_chat_ids(db: DB, exclude_user_id: int | None = None) -> list[int]:
    rows = await db.all(
        "SELECT id, tg_id FROM users WHERE role IN ('owner','admin') AND tg_id IS NOT NULL "
        "AND approved=1"
    )
    return [r["tg_id"] for r in rows if r["id"] != exclude_user_id]


async def notify_admins(bot: Bot, db: DB, text: str, exclude_user_id: int | None = None,
                        reply_markup=None, owner_only: bool = False) -> None:
    if owner_only:
        rows = await db.all("SELECT tg_id FROM users WHERE role='owner' AND tg_id IS NOT NULL")
        chat_ids = [r["tg_id"] for r in rows]
    else:
        chat_ids = await admin_chat_ids(db, exclude_user_id)
    for chat_id in chat_ids:
        await send_safe(bot, chat_id, text, reply_markup)
        await asyncio.sleep(0.05)


async def notify_user(bot: Bot, db: DB, user_id: int | None, text: str, reply_markup=None) -> None:
    user = await db.get_user(user_id)
    if user and user["tg_id"] and user["approved"]:
        await send_safe(bot, user["tg_id"], text, reply_markup)


async def notify_all(bot: Bot, db: DB, text: str, exclude_user_id: int | None = None) -> None:
    rows = await db.all(
        "SELECT id, tg_id FROM users WHERE tg_id IS NOT NULL AND nick IS NOT NULL AND approved=1")
    for r in rows:
        if r["id"] != exclude_user_id:
            await send_safe(bot, r["tg_id"], text)
            await asyncio.sleep(0.05)
