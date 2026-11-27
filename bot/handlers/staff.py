import re
import sqlite3

from aiogram import Bot, F, Router
from aiogram.fsm.context import FSMContext
from aiogram.fsm.state import State, StatesGroup
from aiogram.types import CallbackQuery, Message

from ..db import DB
from ..keyboards import BTN_STAFF, btn, cancel_kb, kb
from ..notify import notify_admins, notify_user
from ..utils import ROLES, esc, fmt_dt, is_admin, now, user_name
from .common import show

router = Router(name="staff")


class AddStaff(StatesGroup):
    username = State()


class SetPercent(StatesGroup):
    value = State()


async def list_view(db: DB, user):
    rows = await db.all(
        "SELECT * FROM users ORDER BY CASE role WHEN 'owner' THEN 0 WHEN 'admin' THEN 1 ELSE 2 END, id")
    text = "👤 <b>Сотрудники</b>\n"
    buttons = []
    for u in rows:
        icon = ROLES[u["role"]].split(" ")[0]
        wait = " ⏳" if not u["tg_id"] or not u["nick"] else ""
        label = f"{icon} {u['nick'] or ('@' + (u['username'] or '?'))} · {u['percent']:g}%{wait}"
        buttons.append([btn(label, f"st:v:{u['id']}")])
    text += "⏳ — ещё не запустил бота или не указал ник."
    add = [btn("➕ Сотрудник", "st:add:worker")]
    if user["role"] == "owner":
        add.append(btn("➕ Админ", "st:add:admin"))
    buttons.append(add)
    return text, kb(*buttons)


@router.message(F.text == BTN_STAFF)
async def staff_menu(message: Message, state: FSMContext, db: DB, user):
    await state.clear()
    if not is_admin(user):
        return
    text, markup = await list_view(db, user)
    await message.answer(text, reply_markup=markup)


@router.callback_query(F.data == "st:list")
async def staff_list_cb(cb: CallbackQuery, db: DB, user):
    if not is_admin(user):
        return await cb.answer("Нет доступа", show_alert=True)
    text, markup = await list_view(db, user)
    await cb.answer()
    await show(cb, text, markup)


def can_manage(actor, target) -> bool:
    if target["role"] == "owner":
        return False
    if target["role"] == "admin":
        return actor["role"] == "owner"
    return is_admin(actor)


async def card_view(db: DB, user, uid: int):
    u = await db.get_user(uid)
    if u is None:
        return None, None
    clients = await db.one(
        "SELECT COUNT(*) n, SUM(status='work') w, SUM(status='paid') p, SUM(status='lost') l "
        "FROM clients WHERE worker_id=?", uid)
    if not u["tg_id"]:
        conn = "⏳ ещё не писал боту"
    elif not u["nick"]:
        conn = "⏳ не указал ник"
    else:
        conn = "✅ подключён"
    text = (
        f"{ROLES[u['role']]}\n\n"
        f"Ник: <b>{esc(u['nick'] or '—')}</b>\n"
        f"Username: {('@' + esc(u['username'])) if u['username'] else '—'}\n"
        f"Статус: {conn}\n"
        f"Процент от оплат: <b>{u['percent']:g}%</b>\n"
        f"Клиентов: {clients['n']} (в работе {clients['w'] or 0}, оплачено {clients['p'] or 0}, "
        f"слив {clients['l'] or 0})\n"
        f"Добавлен: {fmt_dt(u['created_at'])}"
    )
    rows = [[btn("💯 Изменить процент", f"st:p:{uid}")]]
    if can_manage(user, u):
        rows.append([btn("🗑 Удалить", f"st:del:{uid}")])
    rows.append([btn("« К списку", "st:list")])
    return text, kb(*rows)


@router.callback_query(F.data.startswith("st:v:"))
async def staff_card(cb: CallbackQuery, db: DB, user):
    if not is_admin(user):
        return await cb.answer("Нет доступа", show_alert=True)
    text, markup = await card_view(db, user, int(cb.data.split(":")[2]))
    if text is None:
        return await cb.answer("Не найден", show_alert=True)
    await cb.answer()
    await show(cb, text, markup)


# --- добавление ---

@router.callback_query(F.data.startswith("st:add:"))
async def staff_add_start(cb: CallbackQuery, state: FSMContext, user):
    role = cb.data.split(":")[2]
    if not is_admin(user) or (role == "admin" and user["role"] != "owner") or role not in ("admin", "worker"):
        return await cb.answer("Нет доступа", show_alert=True)
    await state.set_state(AddStaff.username)
    await state.update_data(role=role)
    await cb.answer()
    who = "админа" if role == "admin" else "сотрудника"
    await cb.message.answer(f"Введите @username нового {who} в Telegram:", reply_markup=cancel_kb())


@router.message(AddStaff.username, F.text)
async def staff_add_finish(message: Message, state: FSMContext, db: DB, user, bot: Bot):
    role = (await state.get_data()).get("role", "worker")
    username = message.text.strip().lstrip("@").lower()
    username = re.sub(r"^(https?://)?t\.me/", "", username)
    if not re.fullmatch(r"[a-z0-9_]{4,32}", username):
        await message.answer("Некорректный username. Введите в формате @username:", reply_markup=cancel_kb())
        return
    try:
        cur = await db.run(
            "INSERT INTO users(username, role, percent, added_by, created_at) VALUES (?, ?, 50, ?, ?)",
            username, role, user["id"], now())
    except sqlite3.IntegrityError:
        await message.answer("Пользователь с таким username уже есть в списке.")
        await state.clear()
        return
    await state.clear()
    title = ROLES[role]
    await db.audit(user["id"], f"Добавил {title} @{username}")
    await notify_admins(bot, db, f"➕ {user_name(user)} добавил: {title} @{esc(username)}",
                        exclude_user_id=user["id"])
    text, markup = await card_view(db, user, cur.lastrowid)
    await message.answer(
        f"✅ Добавлен {title} @{esc(username)}.\n"
        "Попросите его открыть бота и нажать /start — после этого он укажет свой ник.\n\n" + text,
        reply_markup=markup)


# --- процент ---

@router.callback_query(F.data.startswith("st:p:"))
async def percent_start(cb: CallbackQuery, state: FSMContext, db: DB, user):
    if not is_admin(user):
        return await cb.answer("Нет доступа", show_alert=True)
    uid = int(cb.data.split(":")[2])
    u = await db.get_user(uid)
    if u is None:
        return await cb.answer("Не найден", show_alert=True)
    await state.set_state(SetPercent.value)
    await state.update_data(uid=uid)
    await cb.answer()
    await cb.message.answer(
        f"Текущий процент {user_name(u)}: <b>{u['percent']:g}%</b>\n"
        "Введите новый процент от суммы оплаты клиента (0–100):\n\n"
        "<i>Новый процент действует для оплат, подтверждённых после изменения.</i>",
        reply_markup=cancel_kb())


@router.message(SetPercent.value, F.text)
async def percent_save(message: Message, state: FSMContext, db: DB, user, bot: Bot):
    try:
        value = float(message.text.strip().replace(",", ".").rstrip("%"))
    except ValueError:
        value = -1
    if not 0 <= value <= 100:
        await message.answer("Введите число от 0 до 100:", reply_markup=cancel_kb())
        return
    uid = (await state.get_data())["uid"]
    await state.clear()
    u = await db.get_user(uid)
    if u is None:
        await message.answer("Сотрудник не найден.")
        return
    await db.run("UPDATE users SET percent=? WHERE id=?", value, uid)
    await db.audit(user["id"], f"Процент {u['nick'] or u['username']}: {u['percent']:g}% → {value:g}%")
    if uid != user["id"]:
        await notify_user(bot, db, uid, f"💯 Ваш процент от оплат изменён: <b>{value:g}%</b>")
    text, markup = await card_view(db, user, uid)
    await message.answer("✅ Процент сохранён.\n\n" + text, reply_markup=markup)


# --- удаление ---

@router.callback_query(F.data.startswith("st:del:"))
async def staff_delete_ask(cb: CallbackQuery, db: DB, user):
    uid = int(cb.data.split(":")[2])
    u = await db.get_user(uid)
    if u is None or not can_manage(user, u):
        return await cb.answer("Нет доступа", show_alert=True)
    await cb.answer()
    await show(cb, f"🗑 Удалить {user_name(u)}? Он потеряет доступ к боту, его клиенты останутся без "
                   "сотрудника (их можно будет передать другому).",
               kb([btn("✅ Да, удалить", f"st:delok:{uid}"), btn("« Нет", f"st:v:{uid}")]))


@router.callback_query(F.data.startswith("st:delok:"))
async def staff_delete(cb: CallbackQuery, db: DB, user, bot: Bot):
    uid = int(cb.data.split(":")[2])
    u = await db.get_user(uid)
    if u is None or not can_manage(user, u):
        return await cb.answer("Нет доступа", show_alert=True)
    if u["tg_id"]:
        await db.run("DELETE FROM fsm WHERE key LIKE ?", f"%:{u['tg_id']}:{u['tg_id']}:%")
    await db.run("DELETE FROM users WHERE id=?", uid)
    name = u["nick"] or u["username"]
    await db.audit(user["id"], f"Удалил {ROLES[u['role']]} {name}")
    await notify_admins(bot, db, f"🗑 {user_name(user)} удалил {ROLES[u['role']]} {esc(name)}.",
                        exclude_user_id=user["id"])
    await cb.answer("Удалено")
    text, markup = await list_view(db, user)
    await show(cb, text, markup)
