from aiogram import F, Router
from aiogram.exceptions import TelegramAPIError
from aiogram.filters import Command, CommandStart
from aiogram.fsm.context import FSMContext
from aiogram.types import CallbackQuery, Message, ReplyKeyboardRemove

from ..db import DB
from ..keyboards import menu_kb
from ..middleware import NickForm
from ..ui import show
from ..utils import day_range, esc, fmt_money, is_admin, today

router = Router(name="common")


async def menu_view(db: DB, user, note: str = ""):
    s, e = day_range(today())
    lines = [note, ""] if note else []
    lines.append(f"🏠 <b>Меню</b> · {esc(user['nick'])}")
    if is_admin(user):
        pend = await db.one("SELECT COUNT(*) n FROM payments WHERE status='pending'")
        paid = await db.one("SELECT COUNT(*) n, COALESCE(SUM(amount),0) s FROM payments "
                            "WHERE status='confirmed' AND reviewed_at>=? AND reviewed_at<?", s, e)
        lines.append(f"\n💰 Сегодня: <b>{fmt_money(paid['s'])}</b> · {paid['n']} опл.")
        lines.append(f"⏳ На проверке: <b>{pend['n']}</b>")
        return "\n".join(lines), menu_kb(user, pend["n"])
    work = await db.one("SELECT COUNT(*) n FROM clients WHERE worker_id=? AND status='work'", user["id"])
    earn = await db.one("SELECT COALESCE(SUM(worker_share),0) s FROM payments WHERE worker_id=? "
                        "AND status='confirmed' AND reviewed_at>=? AND reviewed_at<?", user["id"], s, e)
    lines.append(f"\n🔄 В работе: <b>{work['n']}</b>")
    lines.append(f"💵 Заработано сегодня: <b>{fmt_money(earn['s'])}</b>")
    return "\n".join(lines), menu_kb(user)


async def to_menu(event, db: DB, user, note: str = "") -> None:
    text, markup = await menu_view(db, user, note)
    await show(event, text, markup)


async def hide_reply_keyboard(message: Message) -> None:
    """Убрать старую нижнюю клавиатуру, не оставляя лишних сообщений."""
    try:
        tmp = await message.bot.send_message(message.chat.id, "…", reply_markup=ReplyKeyboardRemove())
        await message.bot.delete_message(message.chat.id, tmp.message_id)
    except (TelegramAPIError, AttributeError):
        pass


@router.callback_query(F.data == "hide")
async def cb_hide(cb: CallbackQuery):
    await cb.answer()
    try:
        await cb.message.delete()
    except (TelegramAPIError, AttributeError):
        pass


@router.callback_query(F.data == "m:home")
async def cb_home(cb: CallbackQuery, state: FSMContext, db: DB, user):
    await state.clear()
    await cb.answer()
    await to_menu(cb, db, user)


@router.message(NickForm.nick, F.text)
async def set_nick(message: Message, state: FSMContext, db: DB, user):
    nick = " ".join(message.text.split())
    if nick.startswith("/") or not 2 <= len(nick) <= 32 or not nick.isprintable():
        await show(message, "Ник — от 2 до 32 символов. Введите ещё раз:")
        return
    taken = await db.one("SELECT id FROM users WHERE ulower(nick)=? AND id<>?", nick.lower(), user["id"])
    if taken:
        await show(message, "Этот ник занят. Введите другой:")
        return
    await db.run("UPDATE users SET nick=? WHERE id=?", nick, user["id"])
    await db.audit(user["id"], f"Указал ник «{nick}»")
    await state.clear()
    user = await db.get_user(user["id"])
    await hide_reply_keyboard(message)
    await to_menu(message, db, user, f"✅ Добро пожаловать, <b>{esc(nick)}</b>!")


@router.message(NickForm.nick)
async def set_nick_wrong(message: Message):
    await show(message, "Введите ник текстом:")


@router.message(CommandStart())
@router.message(Command("menu"))
async def cmd_start(message: Message, state: FSMContext, db: DB, user):
    await state.clear()
    await hide_reply_keyboard(message)
    await to_menu(message, db, user)


@router.message(Command("cancel"))
async def cmd_cancel(message: Message, state: FSMContext, db: DB, user):
    await state.clear()
    await to_menu(message, db, user, "Отменено.")


@router.callback_query(F.data == "cancel")
async def cb_cancel(cb: CallbackQuery, state: FSMContext, db: DB, user):
    await state.clear()
    await cb.answer("Отменено")
    await to_menu(cb, db, user)


@router.callback_query(F.data == "noop")
async def cb_noop(cb: CallbackQuery):
    await cb.answer()
