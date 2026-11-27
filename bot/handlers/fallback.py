from aiogram import Router
from aiogram.types import CallbackQuery, Message

from ..db import DB
from .common import to_menu

router = Router(name="fallback")


@router.message()
async def unknown_message(message: Message, db: DB, user):
    await to_menu(message, db, user, "Не понял 🤔 Выберите действие:")


@router.callback_query()
async def unknown_callback(cb: CallbackQuery):
    await cb.answer("Кнопка устарела")
