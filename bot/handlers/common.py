from aiogram import F, Router
from aiogram.exceptions import TelegramBadRequest
from aiogram.filters import Command, CommandStart
from aiogram.fsm.context import FSMContext
from aiogram.types import CallbackQuery, InlineKeyboardMarkup, Message

from ..db import DB
from ..keyboards import main_kb
from ..middleware import NickForm
from ..utils import ROLES, esc

router = Router(name="common")


async def show(cb: CallbackQuery, text: str, reply_markup: InlineKeyboardMarkup | None = None):
    """Обновить сообщение под кнопкой, а если нельзя (например, это фото) — прислать новое."""
    msg = cb.message
    if msg is not None and msg.text is not None:
        try:
            await msg.edit_text(text, reply_markup=reply_markup)
            return
        except TelegramBadRequest as e:
            if "not modified" in str(e):
                return
    await cb.bot.send_message(cb.from_user.id, text, reply_markup=reply_markup)


@router.message(NickForm.nick, F.text)
async def set_nick(message: Message, state: FSMContext, db: DB, user):
    nick = message.text.strip()
    if nick.startswith("/") or not 2 <= len(nick) <= 32:
        await message.answer("Ник должен быть от 2 до 32 символов. Попробуйте ещё раз:")
        return
    taken = await db.one(
        "SELECT id FROM users WHERE lower(nick)=lower(?) AND id<>?", nick, user["id"]
    )
    if taken:
        await message.answer("Этот ник уже занят. Введите другой:")
        return
    await db.run("UPDATE users SET nick=? WHERE id=?", nick, user["id"])
    await db.audit(user["id"], f"Указал ник «{nick}»")
    await state.clear()
    user = await db.get_user(user["id"])
    await message.answer(
        f"✅ Готово, <b>{esc(nick)}</b>!\nВаша роль: {ROLES[user['role']]}.\n\n"
        "Пользуйтесь меню внизу.",
        reply_markup=main_kb(user),
    )


@router.message(NickForm.nick)
async def set_nick_wrong(message: Message):
    await message.answer("Введите ник текстом:")


@router.message(CommandStart())
@router.message(Command("menu"))
async def cmd_start(message: Message, state: FSMContext, user):
    await state.clear()
    await message.answer(
        f"👋 Здравствуйте, <b>{esc(user['nick'])}</b>!\nВаша роль: {ROLES[user['role']]}.",
        reply_markup=main_kb(user),
    )


@router.message(Command("cancel"))
async def cmd_cancel(message: Message, state: FSMContext, user):
    await state.clear()
    await message.answer("Действие отменено.", reply_markup=main_kb(user))


@router.callback_query(F.data == "cancel")
async def cb_cancel(cb: CallbackQuery, state: FSMContext):
    await state.clear()
    await cb.answer("Отменено")
    await show(cb, "Действие отменено.")


@router.callback_query(F.data == "noop")
async def cb_noop(cb: CallbackQuery):
    await cb.answer()
