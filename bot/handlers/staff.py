import re

from aiogram import Bot, F, Router
from aiogram.fsm.context import FSMContext
from aiogram.fsm.state import State, StatesGroup
from aiogram.types import CallbackQuery, Message

from ..db import DB
from ..keyboards import BTN_STAFF, back_btn, btn, cancel_kb, confirm_kb, danger_btn, kb, ok_btn, url_btn
from ..middleware import PENDING_TTL
from ..notify import notify_admins, send_safe
from ..keyboards import main_kb
from ..utils import ROLES, clip, esc, fmt_dt, is_admin, now, user_name
from .common import show

router = Router(name="staff")
USERNAME_RE = re.compile(r"[a-z](?!.*__)[a-z0-9_]{2,30}[a-z0-9]")


class AddStaff(StatesGroup):
    username = State()


class SetPercent(StatesGroup):
    value = State()


def can_manage(actor, target) -> bool:
    """Удаление: главного админа — никто, админов — только главный, сотрудников — любой админ."""
    if target["role"] == "owner":
        return False
    if target["role"] == "admin":
        return actor["role"] == "owner"
    return is_admin(actor)


def can_set_percent(actor, target) -> bool:
    """Процент сотрудников меняют админы, процент админов (и свой) — только главный админ."""
    if actor["role"] == "owner":
        return True
    return is_admin(actor) and target["role"] == "worker"


def status_label(u) -> str:
    if not u["tg_id"]:
        if u["created_at"] < now() - PENDING_TTL:
            return "⌛ приглашение истекло"
        return "⏳ ещё не писал боту"
    if not u["approved"]:
        return "🔔 ждёт подтверждения"
    if not u["nick"]:
        return "⏳ не указал ник"
    return "✅ подключён"


async def list_view(db: DB, user):
    rows = await db.all(
        "SELECT * FROM users ORDER BY CASE role WHEN 'owner' THEN 0 WHEN 'admin' THEN 1 ELSE 2 END, id "
        "LIMIT 90")
    buttons = []
    for u in rows:
        icon = ROLES[u["role"]].split(" ")[0]
        mark = "" if status_label(u).startswith("✅") else " " + status_label(u)[:1]
        label = f"{icon} {u['nick'] or ('@' + (u['username'] or '?'))} · {u['percent']:g}%{mark}"
        buttons.append([btn(clip(label, 60), f"st:v:{u['id']}")])
    add = [ok_btn("➕ Сотрудник", "st:add:worker")]
    if user["role"] == "owner":
        add.append(ok_btn("➕ Админ", "st:add:admin"))
    buttons.append(add)
    text = ("👤 <b>Сотрудники</b>\n"
            "⏳ — не запустил бота или не указал ник · 🔔 — ждёт подтверждения · ⌛ — приглашение истекло")
    return text, kb(*buttons)


@router.message(F.text == BTN_STAFF)
async def staff_menu(message: Message, state: FSMContext, db: DB, user):
    await state.clear()
    if not is_admin(user):
        await message.answer("Нет доступа.", reply_markup=main_kb(user))
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


async def card_view(db: DB, user, uid: int):
    u = await db.get_user(uid)
    if u is None:
        return None, None
    clients = await db.one(
        "SELECT COUNT(*) n, SUM(status='work') w, SUM(status='paid') p, SUM(status='lost') l "
        "FROM clients WHERE worker_id=?", uid)
    text = (
        f"{ROLES[u['role']]}\n\n"
        f"Ник: <b>{esc(u['nick'] or '—')}</b>\n"
        f"Username: {('@' + esc(u['username'])) if u['username'] else '—'}\n"
        f"Статус: {status_label(u)}\n"
        f"Процент от оплат: <b>{u['percent']:g}%</b>\n"
        f"Клиентов: {clients['n']} (в работе {clients['w'] or 0}, оплачено {clients['p'] or 0}, "
        f"слив {clients['l'] or 0})\n"
        f"Добавлен: {fmt_dt(u['created_at'])}"
    )
    rows = []
    if u["tg_id"] and not u["approved"] and can_approve(user, u):
        rows.append([ok_btn("✅ Подтвердить доступ", f"ap:ok:{uid}"), danger_btn("❌ Отклонить", f"ap:no:{uid}")])
    contact = []
    if u["username"]:
        contact.append(url_btn("💬 Написать", f"https://t.me/{u['username']}"))
    elif u["tg_id"]:
        contact.append(url_btn("💬 Написать", f"tg://user?id={u['tg_id']}"))
    if can_set_percent(user, u):
        contact.append(btn("💯 Процент", f"st:p:{uid}"))
    rows.append(contact)
    if can_manage(user, u):
        rows.append([danger_btn("🗑 Удалить", f"st:del:{uid}")])
    rows.append([back_btn("st:list", "« К списку")])
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


# --- подтверждение доступа ---

def can_approve(actor, target) -> bool:
    if target["role"] == "admin":
        return actor["role"] == "owner"
    return is_admin(actor)


@router.callback_query(F.data.startswith("ap:"))
async def approve(cb: CallbackQuery, db: DB, user, bot: Bot):
    _, action, uid = cb.data.split(":")
    u = await db.get_user(int(uid))
    if u is None:
        await cb.answer("Запрос уже обработан", show_alert=True)
        return await show(cb, "Запрос доступа уже обработан.")
    if not can_approve(user, u):
        return await cb.answer("Нет доступа", show_alert=True)
    if u["approved"]:
        await cb.answer("Уже подтверждён", show_alert=True)
        return await show(cb, f"✅ Доступ для @{esc(u['username'] or '')} уже подтверждён.")
    name = "@" + (u["username"] or "?")
    if action == "ok":
        cur = await db.run("UPDATE users SET approved=1 WHERE id=? AND approved=0", u["id"])
        if cur.rowcount != 1:
            return await cb.answer("Уже обработано", show_alert=True)
        await db.audit(user["id"], f"Подтвердил доступ {name} ({ROLES[u['role']]})")
        await cb.answer("Доступ открыт")
        await show(cb, f"✅ Доступ для {esc(name)} подтвердил {user_name(user)}.")
        await notify_admins(bot, db, f"✅ {user_name(user)} подтвердил доступ {esc(name)}.",
                            exclude_user_id=user["id"])
        await send_safe(bot, u["tg_id"], "✅ Доступ открыт! Нажмите /start, чтобы начать работу.")
    else:
        await db.run("DELETE FROM users WHERE id=? AND approved=0", u["id"])
        await db.run("DELETE FROM fsm WHERE key LIKE ?", f"%:{u['tg_id']}:{u['tg_id']}:%")
        await db.audit(user["id"], f"Отклонил доступ {name} (Telegram ID {u['tg_id']})")
        await cb.answer("Отклонено")
        await show(cb, f"❌ Доступ для {esc(name)} отклонил {user_name(user)}. Приглашение удалено.")
        await notify_admins(bot, db, f"❌ {user_name(user)} отклонил доступ {esc(name)}.",
                            exclude_user_id=user["id"])


# --- добавление ---

@router.callback_query(F.data.startswith("st:add:"))
async def staff_add_start(cb: CallbackQuery, state: FSMContext, user):
    role = cb.data.split(":")[2]
    if not is_admin(user) or role not in ("admin", "worker") or (role == "admin" and user["role"] != "owner"):
        return await cb.answer("Нет доступа", show_alert=True)
    await state.set_state(AddStaff.username)
    await state.set_data({"role": role})
    await cb.answer()
    who = "админа" if role == "admin" else "сотрудника"
    await cb.message.answer(f"Введите @username нового {who} в Telegram:", reply_markup=cancel_kb())


@router.message(AddStaff.username, F.text)
async def staff_add_finish(message: Message, state: FSMContext, db: DB, user, bot: Bot):
    role = (await state.get_data()).get("role")
    if not is_admin(user) or role not in ("admin", "worker") or (role == "admin" and user["role"] != "owner"):
        await state.clear()
        return
    username = re.sub(r"^(https?://)?t\.me/", "", message.text.strip().lower()).lstrip("@")
    if not USERNAME_RE.fullmatch(username):
        await message.answer("Некорректный username. Введите в формате @username:", reply_markup=cancel_kb())
        return
    existing = await db.one("SELECT * FROM users WHERE username=?", username)
    if existing and not (existing["tg_id"] is None and existing["created_at"] < now() - PENDING_TTL):
        await state.clear()
        await message.answer("Пользователь с таким username уже есть в списке.")
        return
    if existing:  # просроченное приглашение — заменяем
        await db.run("DELETE FROM users WHERE id=?", existing["id"])
    cur = await db.run(
        "INSERT INTO users(username, role, percent, added_by, created_at, approved) VALUES (?, ?, 50, ?, ?, 0)",
        username, role, user["id"], now())
    await state.clear()
    title = ROLES[role]
    await db.audit(user["id"], f"Пригласил {title} @{username}")
    await notify_admins(bot, db, f"➕ {user_name(user)} пригласил: {title} @{esc(username)}",
                        exclude_user_id=user["id"])
    text, markup = await card_view(db, user, cur.lastrowid)
    await message.answer(
        f"✅ Приглашение для {title} @{esc(username)} создано (действует 14 дней).\n"
        "Попросите его открыть бота и нажать /start. После этого придёт запрос — "
        "<b>проверьте имя и Telegram ID</b> и подтвердите доступ.\n\n" + text,
        reply_markup=markup)


# --- процент ---

@router.callback_query(F.data.startswith("st:p:"))
async def percent_start(cb: CallbackQuery, state: FSMContext, db: DB, user):
    u = await db.get_user(int(cb.data.split(":")[2]))
    if u is None or not can_set_percent(user, u):
        return await cb.answer("Нет доступа", show_alert=True)
    await state.set_state(SetPercent.value)
    await state.set_data({"uid": u["id"]})
    await cb.answer()
    await cb.message.answer(
        f"Текущий процент {user_name(u)}: <b>{u['percent']:g}%</b>\n"
        "Введите новый процент от суммы оплаты клиента (0–100):\n\n"
        "<i>Новый процент действует для оплат, подтверждённых после изменения.</i>",
        reply_markup=cancel_kb())


@router.message(SetPercent.value, F.text)
async def percent_save(message: Message, state: FSMContext, db: DB, user, bot: Bot):
    try:
        value = round(float(message.text.strip().replace(",", ".").rstrip("%")), 2)
    except ValueError:
        value = -1
    if not 0 <= value <= 100:
        await message.answer("Введите число от 0 до 100:", reply_markup=cancel_kb())
        return
    uid = (await state.get_data()).get("uid")
    await state.clear()
    u = await db.get_user(uid)
    if u is None or not can_set_percent(user, u):
        await message.answer("Нет доступа или сотрудник не найден.")
        return
    await db.run("UPDATE users SET percent=? WHERE id=?", value, uid)
    await db.audit(user["id"], f"Процент {u['nick'] or u['username']}: {u['percent']:g}% → {value:g}%")
    if uid != user["id"] and u["tg_id"]:
        await send_safe(bot, u["tg_id"], f"💯 Ваш процент от оплат изменён: <b>{value:g}%</b>")
    await notify_admins(bot, db, f"💯 {user_name(user)} изменил процент {user_name(u)}: "
                                 f"{u['percent']:g}% → {value:g}%", exclude_user_id=user["id"])
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
               confirm_kb(f"st:delok:{uid}", f"st:v:{uid}"))


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
    await cb.answer("Удалено")
    await notify_admins(bot, db, f"🗑 {user_name(user)} удалил {ROLES[u['role']]} {esc(name)}.",
                        exclude_user_id=user["id"])
    text, markup = await list_view(db, user)
    await show(cb, text, markup)
