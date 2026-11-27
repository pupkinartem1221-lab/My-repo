from aiogram import Router
from aiogram.types import CallbackQuery, Message

from ..keyboards import main_kb

router = Router(name="fallback")


@router.message()
async def unknown_message(message: Message, user):
    await message.answer("Не понял команду. Воспользуйтесь меню 👇", reply_markup=main_kb(user))


@router.callback_query()
async def unknown_callback(cb: CallbackQuery):
    await cb.answer("Кнопка устарела", show_alert=False)
