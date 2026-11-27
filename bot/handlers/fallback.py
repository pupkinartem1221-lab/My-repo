from aiogram import Router
from aiogram.types import CallbackQuery, Message

from ..db import DB
from .common import send_menu

router = Router(name="fallback")


@router.message()
async def unknown_message(message: Message, db: DB, user):
    await send_menu(message, db, user, "Не понял команду. Выберите действие 👇\n\n")


@router.callback_query()
async def unknown_callback(cb: CallbackQuery):
    await cb.answer("Кнопка устарела", show_alert=False)
