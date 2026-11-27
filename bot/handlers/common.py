from aiogram import F, Router
from aiogram.exceptions import TelegramBadRequest
from aiogram.filters import Command, CommandStart
from aiogram.fsm.context import FSMContext
from aiogram.exceptions import TelegramAPIError
from aiogram.types import CallbackQuery, InlineKeyboardMarkup, Message, ReplyKeyboardRemove

from ..db import DB
from ..keyboards import menu_kb
from ..middleware import NickForm
from ..utils import ROLES, day_range, esc, fmt_money, is_admin, today

router = Router(name="common")


async def show(cb: CallbackQuery, text: str, reply_markup: InlineKeyboardMarkup | None = None):
    """Обновить сообщение под кнопкой, а если нельзя (например, это фото) — прислать новое."""
    msg = cb.message
    if isinstance(msg, Message) and msg.text is not None:
        try:
            await msg.edit_text(text, reply_markup=reply_markup)
            return
        except TelegramBadRequest as e:
            if "not modified" in str(e):
                return
    await cb.bot.send_message(cb.from_user.id, text, reply_markup=reply_markup)


async def menu_view(db: DB, user):
    s, e = day_range(today())
    lines = ["🏠 <b>Главное меню</b>", f"{ROLES[user['role']]} · {esc(user['nick'])}", ""]
    if is_admin(user):
        pend = await db.one("SELECT COUNT(*) n, COALESCE(SUM(amount),0) s FROM payments WHERE status='pending'")
        paid = await db.one("SELECT COUNT(*) n, COALESCE(SUM(amount),0) s FROM payments "
                            "WHERE status='confirmed' AND reviewed_at>=? AND reviewed_at<?", s, e)
        lines.append(f"💰 Сегодня оплачено: <b>{fmt_money(paid['s'])}</b> ({paid['n']})")
        lines.append(f"⏳ Ждут подтверждения: <b>{pend['n']}</b>" + (f" на {fmt_money(pend['s'])}" if pend["n"] else ""))
        return "\n".join(lines), menu_kb(user, pend["n"])
    work = await db.one("SELECT COUNT(*) n FROM clients WHERE worker_id=? AND status='work'", user["id"])
    earn = await db.one("SELECT COALESCE(SUM(worker_share),0) s FROM payments WHERE worker_id=? "
                        "AND status='confirmed' AND reviewed_at>=? AND reviewed_at<?", user["id"], s, e)
    lines.append(f"🔄 Клиентов в работе: <b>{work['n']}</b>")
    lines.append(f"💵 Заработок сегодня: <b>{fmt_money(earn['s'])}</b>")
    return "\n".join(lines), menu_kb(user)


async def send_menu(message: Message, db: DB, user, prefix: str = "") -> None:
    text, markup = await menu_view(db, user)
    await message.answer(prefix + text, reply_markup=markup)


async def hide_reply_keyboard(message: Message) -> None:
    """Убрать старую нижнюю клавиатуру, не оставляя лишних сообщений."""
    try:
        tmp = await message.bot.send_message(message.chat.id, "…", reply_markup=ReplyKeyboardRemove())
        await message.bot.delete_message(message.chat.id, tmp.message_id)
    except (TelegramAPIError, AttributeError):
        pass


@router.callback_query(F.data == "m:home")
async def cb_home(cb: CallbackQuery, state: FSMContext, db: DB, user):
    await state.clear()
    await cb.answer()
    text, markup = await menu_view(db, user)
    await show(cb, text, markup)


@router.message(NickForm.nick, F.text)
async def set_nick(message: Message, state: FSMContext, db: DB, user):
    nick = " ".join(message.text.split())
    if nick.startswith("/") or not 2 <= len(nick) <= 32 or not nick.isprintable():
        await message.answer("Ник должен быть от 2 до 32 символов. Попробуйте ещё раз:")
        return
    taken = await db.one(
        "SELECT id FROM users WHERE ulower(nick)=? AND id<>?", nick.lower(), user["id"]
    )
    if taken:
        await message.answer("Этот ник уже занят. Введите другой:")
        return
    await db.run("UPDATE users SET nick=? WHERE id=?", nick, user["id"])
    await db.audit(user["id"], f"Указал ник «{nick}»")
    await state.clear()
    user = await db.get_user(user["id"])
    await hide_reply_keyboard(message)
    await send_menu(message, db, user, f"✅ Готово, <b>{esc(nick)}</b>!\n\n")


@router.message(NickForm.nick)
async def set_nick_wrong(message: Message):
    await message.answer("Введите ник текстом:")


@router.message(CommandStart())
@router.message(Command("menu"))
async def cmd_start(message: Message, state: FSMContext, db: DB, user):
    await state.clear()
    await hide_reply_keyboard(message)
    await send_menu(message, db, user)


@router.message(Command("cancel"))
async def cmd_cancel(message: Message, state: FSMContext, db: DB, user):
    await state.clear()
    await send_menu(message, db, user, "Действие отменено.\n\n")


@router.callback_query(F.data == "cancel")
async def cb_cancel(cb: CallbackQuery, state: FSMContext, db: DB, user):
    await state.clear()
    await cb.answer("Отменено")
    text, markup = await menu_view(db, user)
    await show(cb, "Действие отменено.\n\n" + text, markup)


@router.callback_query(F.data == "noop")
async def cb_noop(cb: CallbackQuery):
    await cb.answer()
