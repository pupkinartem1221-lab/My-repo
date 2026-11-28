import re

from aiogram import Bot, F, Router
from aiogram.fsm.context import FSMContext
from aiogram.fsm.state import State, StatesGroup
from aiogram.types import CallbackQuery, Message

from ..db import DB
from ..keyboards import BTN_STAFF, back_btn, btn, cancel_kb, confirm_kb, danger_btn, home_btn, kb, ok_btn, url_btn
from ..middleware import PENDING_TTL
from ..notify import notify_admins, notify_user, send_safe
from ..ui import clear_chat, show
from ..rules import blocks_delete, set_percent, worker_total
from ..utils import ROLES, clip, esc, fmt_money, fmt_short, is_admin, now, pays, user_name

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


def can_approve(actor, target) -> bool:
    if target["role"] == "admin":
        return actor["role"] == "owner"
    return is_admin(actor)


def status_label(u) -> str:
    if not u["tg_id"]:
        return "⌛ приглашение истекло" if u["created_at"] < now() - PENDING_TTL else "⏳ ещё не открыл бота"
    if not u["approved"]:
        return "🔔 ждёт подтверждения"
    if not u["nick"]:
        return "⏳ не указал ник"
    return "✅ активен"


# ---------- список ----------

async def list_view(db: DB, user):
    rows = await db.all(
        "SELECT * FROM users ORDER BY CASE role WHEN 'owner' THEN 0 WHEN 'admin' THEN 1 ELSE 2 END, id LIMIT 90")
    buttons = []
    waiting = 0
    for u in rows:
        icon = ROLES[u["role"]].split(" ")[0]
        st = status_label(u)
        mark = "" if st.startswith("✅") else " " + st[:1]
        waiting += st.startswith("🔔")
        buttons.append([btn(clip(f"{icon} {u['nick'] or ('@' + (u['username'] or '?'))} · {u['percent']:g}%{mark}", 60),
                            f"st:v:{u['id']}")])
    add = [ok_btn("➕ Сотрудник", "st:add:worker")]
    if user["role"] == "owner":
        add.append(ok_btn("➕ Админ", "st:add:admin"))
    buttons.append(add)
    buttons.append([home_btn()])
    text = f"👤 <b>Команда</b> · {len(rows)}"
    if waiting:
        text += f"\n\n🔔 Ждут подтверждения: {waiting}"
    text += "\n\n<i>✅ активен · ⏳ не открыл бота · 🔔 ждёт подтверждения · ⌛ истекло</i>"
    return text, kb(*buttons)


async def open_list(event, db: DB, user):
    text, markup = await list_view(db, user)
    await show(event, text, markup)


@router.message(F.text.in_({BTN_STAFF, "👤 Сотрудники"}))
async def staff_menu(message: Message, state: FSMContext, db: DB, user):
    await state.clear()
    if is_admin(user):
        await open_list(message, db, user)


@router.callback_query(F.data.in_({"m:staff", "st:list"}))
async def staff_menu_cb(cb: CallbackQuery, state: FSMContext, db: DB, user):
    await state.clear()
    if not is_admin(user):
        return await cb.answer("Нет доступа", show_alert=True)
    await cb.answer()
    await open_list(cb, db, user)


# ---------- карточка ----------

async def card_view(db: DB, user, uid: int, note: str = ""):
    u = await db.get_user(uid)
    if u is None:
        return None, None
    c = await db.one("SELECT COUNT(*) n, SUM(status='work') w, SUM(status='paid') p, SUM(status='lost') l "
                     "FROM clients WHERE worker_id=?", uid)
    lines = [note, ""] if note else []
    lines += [
        f"{ROLES[u['role']].split(' ')[0]} <b>{esc(u['nick'] or '—')}</b> · {ROLES[u['role']].split(' ', 1)[1]}",
        f"{('@' + esc(u['username'])) if u['username'] else 'без username'} · {status_label(u)}",
        f"\n💯 Процент: <b>{u['percent']:g}%</b>",
        f"👥 Клиенты: {c['n']} · 🔄 {c['w'] or 0} · ✅ {c['p'] or 0} · ❌ {c['l'] or 0}",
        f"<i>Добавлен {fmt_short(u['created_at'])}</i>",
    ]
    rows = []
    if u["tg_id"] and not u["approved"] and can_approve(user, u):
        rows.append([ok_btn("✅ Подтвердить", f"ap:ok:{uid}"), danger_btn("❌ Отклонить", f"ap:no:{uid}")])
    top = []
    if u["username"]:
        top.append(url_btn("💬 Написать", f"https://t.me/{u['username']}"))
    elif u["tg_id"]:
        top.append(url_btn("💬 Написать", f"tg://user?id={u['tg_id']}"))
    if can_set_percent(user, u):
        top.append(btn("💯 Процент", f"st:p:{uid}"))
    rows.append(top)
    if can_manage(user, u):
        rows.append([danger_btn("🗑 Удалить из команды", f"st:del:{uid}")])
    rows.append([back_btn("st:list", "« Команда"), home_btn()])
    return "\n".join(lines), kb(*rows)


async def open_card(event, db: DB, user, uid: int, note: str = ""):
    text, markup = await card_view(db, user, uid, note)
    if text is None:
        await open_list(event, db, user)
        return
    await show(event, text, markup)


@router.callback_query(F.data.startswith("st:v:"))
async def staff_card(cb: CallbackQuery, state: FSMContext, db: DB, user):
    await state.clear()
    if not is_admin(user):
        return await cb.answer("Нет доступа", show_alert=True)
    await cb.answer()
    await open_card(cb, db, user, int(cb.data.split(":")[2]))


# ---------- подтверждение доступа ----------

@router.callback_query(F.data.startswith("ap:"))
async def approve(cb: CallbackQuery, db: DB, user, bot: Bot):
    _, action, uid = cb.data.split(":")
    u = await db.get_user(int(uid))
    if u is None:
        return await cb.answer("Запрос уже обработан", show_alert=True)
    if not can_approve(user, u):
        return await cb.answer("Нет доступа", show_alert=True)
    if u["approved"]:
        return await cb.answer("Уже подтверждён", show_alert=True)
    name = "@" + (u["username"] or "?")
    if action == "ok":
        if (await db.run("UPDATE users SET approved=1 WHERE id=? AND approved=0", u["id"])).rowcount != 1:
            return await cb.answer("Уже обработано", show_alert=True)
        await db.audit(user["id"], f"Подтвердил доступ {name} ({ROLES[u['role']]})")
        await cb.answer("✅ Доступ открыт")
        await open_card(cb, db, user, u["id"], f"✅ {esc(name)} получил доступ")
        await notify_admins(bot, db, f"✅ {user_name(user)} подтвердил доступ {esc(name)}",
                            exclude_user_id=user["id"])
        await send_safe(bot, u["tg_id"], "✅ Доступ открыт! Нажмите /start")
    else:
        await db.run("DELETE FROM users WHERE id=? AND approved=0", u["id"])
        await db.run("DELETE FROM fsm WHERE key LIKE ?", f"%:{u['tg_id']}:{u['tg_id']}:%")
        await clear_chat(bot, u["tg_id"])
        await db.audit(user["id"], f"Отклонил доступ {name} (Telegram ID {u['tg_id']})")
        await cb.answer("❌ Отклонено")
        await open_list(cb, db, user)
        await notify_admins(bot, db, f"❌ {user_name(user)} отклонил доступ {esc(name)}",
                            exclude_user_id=user["id"])


# ---------- приглашение ----------

@router.callback_query(F.data.startswith("st:add:"))
async def staff_add_start(cb: CallbackQuery, state: FSMContext, user):
    role = cb.data.split(":")[2]
    if not is_admin(user) or role not in ("admin", "worker") or (role == "admin" and user["role"] != "owner"):
        return await cb.answer("Нет доступа", show_alert=True)
    await state.set_state(AddStaff.username)
    await state.set_data({"role": role})
    await cb.answer()
    who = "админа" if role == "admin" else "сотрудника"
    await show(cb, f"➕ <b>Пригласить {who}</b>\n\nВведите его @username в Telegram:", cancel_kb())


@router.message(AddStaff.username, F.text)
async def staff_add_finish(message: Message, state: FSMContext, db: DB, user, bot: Bot):
    role = (await state.get_data()).get("role")
    if not is_admin(user) or role not in ("admin", "worker") or (role == "admin" and user["role"] != "owner"):
        await state.clear()
        return
    username = re.sub(r"^(https?://)?t\.me/", "", message.text.strip().lower()).lstrip("@")
    if not USERNAME_RE.fullmatch(username):
        await show(message, "❗ Это не похоже на username. Пример: @ivan_petrov\n\nВведите ещё раз:", cancel_kb())
        return
    existing = await db.one("SELECT * FROM users WHERE username=?", username)
    if existing and not (existing["tg_id"] is None and existing["created_at"] < now() - PENDING_TTL):
        await state.clear()
        await open_card(message, db, user, existing["id"], "ℹ️ Он уже в команде")
        return
    if existing:  # просроченное приглашение — заменяем
        await db.run("DELETE FROM users WHERE id=?", existing["id"])
    cur = await db.run(
        "INSERT INTO users(username, role, percent, added_by, created_at, approved) VALUES (?, ?, 50, ?, ?, 0)",
        username, role, user["id"], now())
    await state.clear()
    title = ROLES[role]
    await db.audit(user["id"], f"Пригласил {title} @{username}")
    await open_card(message, db, user, cur.lastrowid,
                    f"✅ Приглашение создано\n\n1. Попросите @{esc(username)} открыть бота и нажать /start\n"
                    "2. Вам придёт запрос — проверьте имя и подтвердите")
    await notify_admins(bot, db, f"➕ {user_name(user)} пригласил {title} @{esc(username)}",
                        exclude_user_id=user["id"])


# ---------- процент ----------

@router.callback_query(F.data.startswith("st:p:"))
async def percent_start(cb: CallbackQuery, state: FSMContext, db: DB, user):
    u = await db.get_user(int(cb.data.split(":")[2]))
    if u is None or not can_set_percent(user, u):
        return await cb.answer("Нет доступа", show_alert=True)
    await state.set_state(SetPercent.value)
    await state.set_data({"uid": u["id"]})
    await cb.answer()
    presets = [btn(f"{p}%", f"st:pv:{p}") for p in (30, 40, 50, 60)]
    await show(cb, f"💯 Процент для <b>{user_name(u)}</b> · сейчас {u['percent']:g}%\n\n"
                   "Выберите или введите число от 0 до 100.\n<i>Весь заработок сотрудника пересчитается по новому проценту.</i>",
               kb(presets, [btn("✖️ Отмена", f"st:v:{u['id']}")]))


async def save_percent(event, state: FSMContext, db: DB, user, bot: Bot, value: float):
    uid = (await state.get_data()).get("uid")
    await state.clear()
    u = await db.get_user(uid)
    if u is None or not can_set_percent(user, u):
        await show(event, "Нет доступа.", kb([home_btn()]))
        return
    n = await set_percent(db, uid, value)
    total = await worker_total(db, uid)
    await db.audit(user["id"], f"Процент {u['nick'] or u['username']}: {u['percent']:g}% → {value:g}% "
                               f"(пересчитано оплат: {n})")
    await open_card(event, db, user, uid, f"✅ Процент: {value:g}%\nЗаработок пересчитан: {fmt_money(total)} ({pays(n)})")
    if uid != user["id"] and u["tg_id"]:
        await notify_user(bot, db, uid, f"💯 Ваш процент теперь <b>{value:g}%</b>\n"
                                         f"Заработок пересчитан: <b>{fmt_money(total)}</b>")
    await notify_admins(bot, db, f"💯 {user_name(user)}: процент {user_name(u)} {u['percent']:g}% → {value:g}%",
                        exclude_user_id=user["id"])


@router.callback_query(SetPercent.value, F.data.startswith("st:pv:"))
async def percent_preset(cb: CallbackQuery, state: FSMContext, db: DB, user, bot: Bot):
    await cb.answer()
    await save_percent(cb, state, db, user, bot, float(cb.data.split(":")[2]))


@router.message(SetPercent.value, F.text)
async def percent_save(message: Message, state: FSMContext, db: DB, user, bot: Bot):
    try:
        value = round(float(message.text.strip().replace(",", ".").rstrip("%")), 2)
    except ValueError:
        value = -1
    if not 0 <= value <= 100:
        uid = (await state.get_data()).get("uid")
        await show(message, "❗ Нужно число от 0 до 100:", kb([btn("✖️ Отмена", f"st:v:{uid}")]))
        return
    await save_percent(message, state, db, user, bot, value)


# ---------- удаление ----------

@router.callback_query(F.data.startswith("st:del:"))
async def staff_delete_ask(cb: CallbackQuery, db: DB, user):
    uid = int(cb.data.split(":")[2])
    u = await db.get_user(uid)
    if u is None or not can_manage(user, u):
        return await cb.answer("Нет доступа", show_alert=True)
    await cb.answer()
    await show(cb, f"🗑 Удалить <b>{user_name(u)}</b>?\n\nДоступ к боту закроется. Его клиентов можно будет передать.",
               confirm_kb(f"st:delok:{uid}", f"st:v:{uid}"))


@router.callback_query(F.data.startswith("st:delok:"))
async def staff_delete(cb: CallbackQuery, db: DB, user, bot: Bot):
    uid = int(cb.data.split(":")[2])
    u = await db.get_user(uid)
    if u is None or not can_manage(user, u):
        return await cb.answer("Нет доступа", show_alert=True)
    reason = await blocks_delete(db, uid)
    if reason:
        return await cb.answer(reason, show_alert=True)
    if u["tg_id"]:
        await clear_chat(bot, u["tg_id"])
    stmts = [("DELETE FROM users WHERE id=?", uid)]
    if u["tg_id"]:
        stmts.insert(0, ("DELETE FROM fsm WHERE key LIKE ?", f"%:{u['tg_id']}:{u['tg_id']}:%"))
    await db.run_many(stmts)
    name = u["nick"] or u["username"]
    await db.audit(user["id"], f"Удалил {ROLES[u['role']]} {name}")
    await cb.answer("Удалено")
    await open_list(cb, db, user)
    await notify_admins(bot, db, f"🗑 {user_name(user)} удалил {esc(name)}", exclude_user_id=user["id"])
