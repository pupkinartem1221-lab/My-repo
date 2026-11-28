from aiogram import Router
from aiogram.fsm.context import FSMContext
from aiogram.types import CallbackQuery, Message

from ..db import DB
from .common import to_menu

router = Router(name="fallback")


@router.message()
async def unknown_message(message: Message, state: FSMContext, db: DB, user):
    # сюда попадает и неподходящий ввод в форме (фото вместо текста и т.п.) — форму сбрасываем,
    # чтобы следующий текст не записался в неё «вслепую»
    had_form = await state.get_state()
    await state.clear()
    await to_menu(message, db, user, "Действие отменено." if had_form else "Не понял 🤔 Выберите действие:")


@router.callback_query()
async def unknown_callback(cb: CallbackQuery):
    await cb.answer("Кнопка устарела")
