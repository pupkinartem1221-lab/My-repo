"""«Одно окно»: у каждого пользователя одно сообщение-экран, которое меняется на месте.

* Нажатие кнопки — экран редактируется.
* Пользователь что-то ввёл — его сообщение удаляется, старый экран удаляется, новый
  присылается внизу. В чате всегда только актуальный экран.
* Временные сообщения (фото квитанций и т.п.) удаляются при следующей смене экрана.
"""
import json

from aiogram import Bot
from aiogram.exceptions import TelegramAPIError, TelegramBadRequest
from aiogram.types import CallbackQuery, InlineKeyboardMarkup, Message

from .db import DB

_db: DB | None = None


def init(db: DB) -> None:
    global _db
    _db = db


async def _get(chat_id: int) -> tuple[int | None, list[int]]:
    row = await _db.one("SELECT screen_id, aux FROM ui WHERE tg_id=?", chat_id)
    if not row:
        return None, []
    return row["screen_id"], json.loads(row["aux"] or "[]")


async def _set(chat_id: int, screen_id: int | None, aux: list[int]) -> None:
    old_screen, old_aux = await _get(chat_id)
    if old_screen == screen_id and old_aux == aux:
        return
    await _db.run(
        "INSERT INTO ui(tg_id, screen_id, aux) VALUES (?, ?, ?) "
        "ON CONFLICT(tg_id) DO UPDATE SET screen_id=excluded.screen_id, aux=excluded.aux",
        chat_id, screen_id, json.dumps(aux[-50:]),
    )


async def _delete(bot: Bot, chat_id: int, ids) -> None:
    ids = [i for i in ids if i]
    for start in range(0, len(ids), 100):
        try:
            await bot.delete_messages(chat_id, ids[start:start + 100])
        except TelegramAPIError:
            for i in ids[start:start + 100]:
                try:
                    await bot.delete_message(chat_id, i)
                except TelegramAPIError:
                    pass


async def show(event: Message | CallbackQuery, text: str,
               reply_markup: InlineKeyboardMarkup | None = None) -> None:
    bot = event.bot
    chat_id = event.from_user.id
    screen_id, aux = await _get(chat_id)
    await _delete(bot, chat_id, aux)

    if isinstance(event, CallbackQuery):
        msg = event.message
        rm = getattr(msg, "reply_markup", None)
        # уведомление (с кнопкой «Скрыть») не превращаем в экран — оно остаётся, экран приходит ниже
        notice = bool(rm) and any(b.callback_data == "hide" for r in rm.inline_keyboard for b in r)
        if isinstance(msg, Message) and msg.text is not None and msg.message_id not in aux and not notice:
            try:
                await msg.edit_text(text, reply_markup=reply_markup)
                ok = True
            except TelegramBadRequest as e:
                ok = "not modified" in str(e)
            if ok:
                if screen_id and screen_id != msg.message_id:
                    await _delete(bot, chat_id, [screen_id])  # экран был другим — убрать дубль
                await _set(chat_id, msg.message_id, [])
                return
    else:
        try:
            await event.delete()  # ввод пользователя больше не нужен
        except (TelegramAPIError, AttributeError):
            pass

    if screen_id:
        await _delete(bot, chat_id, [screen_id])
    sent = await bot.send_message(chat_id, text, reply_markup=reply_markup)
    await _set(chat_id, sent.message_id, [])


async def _add_aux(chat_id: int, message_id: int) -> None:
    screen_id, aux = await _get(chat_id)
    await _set(chat_id, screen_id, aux + [message_id])


async def extra_file(bot: Bot, chat_id: int, file_id: str, file_type: str, caption: str,
                     reply_markup: InlineKeyboardMarkup | None = None, replace: bool = False) -> None:
    """Временное фото/файл под экраном — исчезнет при следующей смене экрана."""
    if replace:
        screen_id, aux = await _get(chat_id)
        await _delete(bot, chat_id, aux)
        await _set(chat_id, screen_id, [])
    try:
        if file_type == "photo":
            sent = await bot.send_photo(chat_id, file_id, caption=caption, reply_markup=reply_markup)
        else:
            sent = await bot.send_document(chat_id, file_id, caption=caption, reply_markup=reply_markup)
    except TelegramAPIError:
        return
    await _add_aux(chat_id, sent.message_id)


async def forget(chat_id: int) -> None:
    await _db.run("DELETE FROM ui WHERE tg_id=?", chat_id)


async def clear_chat(bot: Bot, chat_id: int) -> None:
    """Убрать экран и временные сообщения пользователя (при удалении/отказе в доступе)."""
    screen_id, aux = await _get(chat_id)
    await _delete(bot, chat_id, aux + ([screen_id] if screen_id else []))
    await forget(chat_id)
