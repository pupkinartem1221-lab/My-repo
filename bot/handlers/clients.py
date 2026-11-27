import re

from aiogram import Bot, F, Router
from aiogram.fsm.context import FSMContext
from aiogram.fsm.state import State, StatesGroup
from aiogram.types import CallbackQuery, Message

from ..db import DB
from ..keyboards import BTN_CLIENTS, BTN_NEW_CLIENT, btn, cancel_kb, kb
from ..notify import notify_admins, notify_user
from ..utils import CLIENT_STATUSES, esc, fmt_dt, fmt_money, is_admin, now, user_name
from .common import show
from .requisites import req_for_client, req_short

router = Router(name="clients")
PAGE = 8
PHONE = "replace(replace(replace(replace(replace(phone,'+',''),' ',''),'-',''),'(',''),')','')"
FILTERS = {"all": "Все", **{k: v for k, v in CLIENT_STATUSES.items()}}


class NewClient(StatesGroup):
    name = State()
    phone = State()
    comment = State()
    worker = State()


class ClientComment(StatesGroup):
    text = State()


class ClientSearch(StatesGroup):
    query = State()


async def get_client_for(db: DB, user, cid: int):
    """Клиент, если у пользователя есть к нему доступ (админ — ко всем, сотрудник — к своим)."""
    c = await db.one("SELECT * FROM clients WHERE id=?", cid)
    if c is None:
        return None
    if is_admin(user) or c["worker_id"] == user["id"]:
        return c
    return None


def client_btn(c) -> list:
    icon = CLIENT_STATUSES.get(c["status"], "")[:1]
    label = f"{icon} #{c['id']} {c['name'][:28]}"
    if c["phone"]:
        label += f" · {c['phone'][-10:]}"
    return [btn(label, f"cl:v:{c['id']}")]


# --- список ---

async def list_view(db: DB, user, flt: str, page: int):
    where, params = [], []
    if not is_admin(user):
        where.append("worker_id=?")
        params.append(user["id"])
    if flt in CLIENT_STATUSES:
        where.append("status=?")
        params.append(flt)
    w = ("WHERE " + " AND ".join(where)) if where else ""
    total = (await db.one(f"SELECT COUNT(*) n FROM clients {w}", *params))["n"]
    pages = max(1, (total + PAGE - 1) // PAGE)
    page = min(max(page, 0), pages - 1)
    rows = await db.all(
        f"SELECT * FROM clients {w} ORDER BY id DESC LIMIT ? OFFSET ?", *params, PAGE, page * PAGE
    )
    title = "👥 <b>Клиенты</b>" if is_admin(user) else "👥 <b>Мои клиенты</b>"
    text = f"{title}\nФильтр: {FILTERS[flt]} · всего {total}"
    if total:
        text += f" · стр. {page + 1}/{pages}"
    else:
        text += "\n\nКлиентов нет."

    flt_row = [btn(("• " if k == flt else "") + v.split(" ")[0], f"cl:l:{k}:0")
               for k, v in FILTERS.items()]
    nav = []
    if page > 0:
        nav.append(btn("◀️", f"cl:l:{flt}:{page - 1}"))
    if page < pages - 1:
        nav.append(btn("▶️", f"cl:l:{flt}:{page + 1}"))
    markup = kb(flt_row, *[client_btn(c) for c in rows], nav, [btn("🔍 Поиск", "cl:search")])
    return text, markup


@router.message(F.text == BTN_CLIENTS)
async def clients_menu(message: Message, state: FSMContext, db: DB, user):
    await state.clear()
    text, markup = await list_view(db, user, "all", 0)
    await message.answer(text, reply_markup=markup)


@router.callback_query(F.data.startswith("cl:l:"))
async def clients_list_cb(cb: CallbackQuery, db: DB, user):
    _, _, flt, page = cb.data.split(":")
    text, markup = await list_view(db, user, flt if flt in FILTERS else "all", int(page))
    await cb.answer()
    await show(cb, text, markup)


@router.callback_query(F.data == "cl:search")
async def search_start(cb: CallbackQuery, state: FSMContext):
    await state.set_state(ClientSearch.query)
    await cb.answer()
    await cb.message.answer("Введите имя или телефон клиента для поиска:", reply_markup=cancel_kb())


@router.message(ClientSearch.query, F.text)
async def search_do(message: Message, state: FSMContext, db: DB, user):
    q = message.text.strip()
    digits = re.sub(r"\D", "", q)
    sql = f"SELECT * FROM clients WHERE (lower(name) LIKE ? OR (? <> '' AND {PHONE} LIKE ?))"
    params = [f"%{q.lower()}%", digits, f"%{digits}%"]
    if not is_admin(user):
        sql += " AND worker_id=?"
        params.append(user["id"])
    rows = await db.all(sql + " ORDER BY id DESC LIMIT 20", *params)
    await state.clear()
    if not rows:
        await message.answer("Ничего не найдено.")
        return
    await message.answer(f"🔍 Найдено: {len(rows)}", reply_markup=kb(*[client_btn(c) for c in rows]))


# --- карточка ---

async def card_view(db: DB, user, c):
    worker = await db.get_user(c["worker_id"])
    req = await db.one("SELECT * FROM requisites WHERE id=?", c["requisite_id"]) if c["requisite_id"] else None
    sums = await db.one(
        "SELECT COUNT(*) n, "
        "COALESCE(SUM(CASE WHEN status='confirmed' THEN amount END),0) paid, "
        "COALESCE(SUM(CASE WHEN status='pending' THEN amount END),0) pend "
        "FROM payments WHERE client_id=?", c["id"])
    comments = await db.all(
        "SELECT * FROM comments WHERE client_id=? ORDER BY id DESC LIMIT 5", c["id"])

    lines = [
        f"👤 <b>Клиент #{c['id']}</b>",
        f"Имя: {esc(c['name'])}",
        f"Телефон: <code>{esc(c['phone'] or '—')}</code>",
        f"Статус: {CLIENT_STATUSES.get(c['status'], c['status'])}",
        f"Сотрудник: {user_name(worker)}",
        f"Реквизит: {req_short(req)}",
        f"Оплачено: {fmt_money(sums['paid'])}"
        + (f" · ожидает проверки: {fmt_money(sums['pend'])}" if sums["pend"] else ""),
        f"Создан: {fmt_dt(c['created_at'])}",
    ]
    if comments:
        lines.append("\n💬 <b>Последние комментарии:</b>")
        for cm in reversed(comments):
            author = await db.get_user(cm["author_id"])
            lines.append(f"• <i>{fmt_dt(cm['created_at'])}, {user_name(author)}:</i> {esc(cm['text'])}")

    cid = c["id"]
    status_row = [btn(("✔️ " if k == c["status"] else "") + v, f"cl:st:{cid}:{k}")
                  for k, v in CLIENT_STATUSES.items()]
    rows = [
        status_row[:2], status_row[2:],
        [btn("💬 Комментарий", f"cl:cm:{cid}"), btn("📝 Все комментарии", f"cl:cma:{cid}")],
        [btn("💳 Реквизит", f"cl:rq:{cid}"), btn("🧾 Добавить квитанцию", f"pay:new:{cid}")],
        [btn(f"💰 Оплаты ({sums['n']})", f"pay:cl:{cid}")],
    ]
    if is_admin(user):
        rows.append([btn("👤 Сменить сотрудника", f"cl:w:{cid}"), btn("🗑 Удалить", f"cl:del:{cid}")])
    rows.append([btn("« К списку", "cl:l:all:0")])
    return "\n".join(lines)[:4000], kb(*rows)


async def send_card(message: Message, db: DB, user, cid: int, prefix: str = ""):
    c = await get_client_for(db, user, cid)
    if c is None:
        await message.answer("Клиент не найден.")
        return
    text, markup = await card_view(db, user, c)
    await message.answer(prefix + text, reply_markup=markup)


@router.callback_query(F.data.startswith("cl:v:"))
async def client_card(cb: CallbackQuery, state: FSMContext, db: DB, user):
    await state.clear()
    c = await get_client_for(db, user, int(cb.data.split(":")[2]))
    if c is None:
        return await cb.answer("Клиент не найден или нет доступа", show_alert=True)
    text, markup = await card_view(db, user, c)
    await cb.answer()
    await show(cb, text, markup)


@router.callback_query(F.data.startswith("cl:st:"))
async def client_status(cb: CallbackQuery, db: DB, user, bot: Bot):
    _, _, cid, st = cb.data.split(":")
    c = await get_client_for(db, user, int(cid))
    if c is None:
        return await cb.answer("Нет доступа", show_alert=True)
    if st not in CLIENT_STATUSES:
        return await cb.answer()
    if c["status"] == st:
        return await cb.answer("Этот статус уже установлен")
    await db.run("UPDATE clients SET status=? WHERE id=?", st, c["id"])
    old, new = CLIENT_STATUSES.get(c["status"], c["status"]), CLIENT_STATUSES[st]
    await db.audit(user["id"], f"Клиент #{c['id']}: {old} → {new}")
    await notify_admins(
        bot, db,
        f"🔁 {user_name(user)} сменил статус клиента #{c['id']} {esc(c['name'])}: {old} → <b>{new}</b>",
        exclude_user_id=user["id"],
    )
    await cb.answer("Статус изменён")
    c = await db.one("SELECT * FROM clients WHERE id=?", c["id"])
    text, markup = await card_view(db, user, c)
    await show(cb, text, markup)


# --- комментарии ---

@router.callback_query(F.data.startswith("cl:cm:"))
async def comment_start(cb: CallbackQuery, state: FSMContext, db: DB, user):
    c = await get_client_for(db, user, int(cb.data.split(":")[2]))
    if c is None:
        return await cb.answer("Нет доступа", show_alert=True)
    await state.set_state(ClientComment.text)
    await state.update_data(cid=c["id"])
    await cb.answer()
    await cb.message.answer(f"💬 Введите комментарий к клиенту #{c['id']} {esc(c['name'])}:",
                            reply_markup=cancel_kb())


@router.message(ClientComment.text, F.text)
async def comment_save(message: Message, state: FSMContext, db: DB, user):
    cid = (await state.get_data())["cid"]
    c = await get_client_for(db, user, cid)
    await state.clear()
    if c is None:
        await message.answer("Клиент не найден.")
        return
    await db.run("INSERT INTO comments(client_id, author_id, text, created_at) VALUES (?, ?, ?, ?)",
                 cid, user["id"], message.text.strip()[:1500], now())
    await db.audit(user["id"], f"Комментарий к клиенту #{cid}")
    await send_card(message, db, user, cid, "✅ Комментарий добавлен.\n\n")


@router.callback_query(F.data.startswith("cl:cma:"))
async def comments_all(cb: CallbackQuery, db: DB, user):
    c = await get_client_for(db, user, int(cb.data.split(":")[2]))
    if c is None:
        return await cb.answer("Нет доступа", show_alert=True)
    rows = await db.all("SELECT * FROM comments WHERE client_id=? ORDER BY id", c["id"])
    await cb.answer()
    if not rows:
        await cb.message.answer("Комментариев пока нет.")
        return
    chunk = f"📝 <b>Комментарии — клиент #{c['id']} {esc(c['name'])}</b>\n"
    for cm in rows:
        author = await db.get_user(cm["author_id"])
        line = f"\n• <i>{fmt_dt(cm['created_at'])}, {user_name(author)}:</i> {esc(cm['text'])}"
        if len(chunk) + len(line) > 3900:
            await cb.message.answer(chunk)
            chunk = ""
        chunk += line
    await cb.message.answer(chunk, reply_markup=kb([btn("« К клиенту", f"cl:v:{c['id']}")]))


# --- реквизит клиента ---

@router.callback_query(F.data.startswith("cl:rq:"))
async def client_req_pick(cb: CallbackQuery, db: DB, user):
    c = await get_client_for(db, user, int(cb.data.split(":")[2]))
    if c is None:
        return await cb.answer("Нет доступа", show_alert=True)
    reqs = await db.all("SELECT * FROM requisites WHERE is_active=1 ORDER BY id DESC")
    rows = [[btn(f"🟢 #{r['id']} {r['iban'][-8:]} · {r['holder'][:22]}", f"cl:rqs:{c['id']}:{r['id']}")]
            for r in reqs]
    if c["requisite_id"]:
        rows.append([btn("📋 Показать текущий для клиента", f"cl:rqshow:{c['id']}")])
        rows.append([btn("✖️ Отвязать реквизит", f"cl:rqs:{c['id']}:0")])
    rows.append([btn("« К клиенту", f"cl:v:{c['id']}")])
    text = f"💳 Выберите рабочий реквизит для клиента #{c['id']} {esc(c['name'])}:"
    if not reqs:
        text = "Нет рабочих реквизитов. Обратитесь к админу."
    await cb.answer()
    await show(cb, text, kb(*rows))


@router.callback_query(F.data.startswith("cl:rqs:"))
async def client_req_set(cb: CallbackQuery, db: DB, user):
    _, _, cid, rid = cb.data.split(":")
    c = await get_client_for(db, user, int(cid))
    if c is None:
        return await cb.answer("Нет доступа", show_alert=True)
    rid = int(rid)
    r = None
    if rid:
        r = await db.one("SELECT * FROM requisites WHERE id=? AND is_active=1", rid)
        if r is None:
            return await cb.answer("Реквизит не рабочий или удалён", show_alert=True)
    await db.run("UPDATE clients SET requisite_id=? WHERE id=?", rid or None, c["id"])
    await db.audit(user["id"], f"Клиент #{c['id']}: реквизит → {('#' + str(rid)) if rid else 'отвязан'}")
    await cb.answer("Сохранено")
    c = await db.one("SELECT * FROM clients WHERE id=?", c["id"])
    text, markup = await card_view(db, user, c)
    await show(cb, text, markup)
    if r is not None:
        await cb.message.answer(req_for_client(r))


@router.callback_query(F.data.startswith("cl:rqshow:"))
async def client_req_show(cb: CallbackQuery, db: DB, user):
    c = await get_client_for(db, user, int(cb.data.split(":")[2]))
    if c is None or not c["requisite_id"]:
        return await cb.answer("Реквизит не привязан", show_alert=True)
    r = await db.one("SELECT * FROM requisites WHERE id=?", c["requisite_id"])
    await cb.answer()
    if not r["is_active"]:
        await cb.message.answer("⚠️ Этот реквизит сейчас <b>не рабочий</b>! Выберите другой.")
        return
    await cb.message.answer(req_for_client(r))


# --- смена сотрудника / удаление (админ) ---

@router.callback_query(F.data.startswith("cl:w:"))
async def client_worker_pick(cb: CallbackQuery, db: DB, user):
    if not is_admin(user):
        return await cb.answer("Нет доступа", show_alert=True)
    cid = int(cb.data.split(":")[2])
    staff = await db.all("SELECT * FROM users WHERE nick IS NOT NULL ORDER BY role DESC, nick")
    rows = [[btn(user_name(u), f"cl:ws:{cid}:{u['id']}")] for u in staff]
    rows.append([btn("« К клиенту", f"cl:v:{cid}")])
    await cb.answer()
    await show(cb, f"👤 Выберите сотрудника для клиента #{cid}:", kb(*rows))


@router.callback_query(F.data.startswith("cl:ws:"))
async def client_worker_set(cb: CallbackQuery, db: DB, user, bot: Bot):
    if not is_admin(user):
        return await cb.answer("Нет доступа", show_alert=True)
    _, _, cid, uid = cb.data.split(":")
    c = await db.one("SELECT * FROM clients WHERE id=?", int(cid))
    worker = await db.get_user(int(uid))
    if c is None or worker is None:
        return await cb.answer("Не найдено", show_alert=True)
    await db.run("UPDATE clients SET worker_id=? WHERE id=?", worker["id"], c["id"])
    await db.audit(user["id"], f"Клиент #{c['id']} передан {worker['nick']}")
    if worker["id"] != user["id"]:
        await notify_user(bot, db, worker["id"],
                          f"📥 Вам передан клиент #{c['id']} {esc(c['name'])}.",
                          kb([btn("Открыть", f"cl:v:{c['id']}")]))
    await cb.answer("Сохранено")
    c = await db.one("SELECT * FROM clients WHERE id=?", c["id"])
    text, markup = await card_view(db, user, c)
    await show(cb, text, markup)


@router.callback_query(F.data.startswith("cl:del:"))
async def client_delete_ask(cb: CallbackQuery, user):
    if not is_admin(user):
        return await cb.answer("Нет доступа", show_alert=True)
    cid = int(cb.data.split(":")[2])
    await cb.answer()
    await show(cb, f"🗑 Удалить клиента #{cid} вместе с комментариями?\n"
                   "Подтверждённые оплаты останутся в отчётах.",
               kb([btn("✅ Да, удалить", f"cl:delok:{cid}"), btn("« Нет", f"cl:v:{cid}")]))


@router.callback_query(F.data.startswith("cl:delok:"))
async def client_delete(cb: CallbackQuery, db: DB, user, bot: Bot):
    if not is_admin(user):
        return await cb.answer("Нет доступа", show_alert=True)
    cid = int(cb.data.split(":")[2])
    c = await db.one("SELECT * FROM clients WHERE id=?", cid)
    if c is None:
        return await cb.answer("Уже удалён", show_alert=True)
    await db.run("DELETE FROM clients WHERE id=?", cid)
    await db.audit(user["id"], f"Удалил клиента #{cid} {c['name']}")
    await notify_admins(bot, db, f"🗑 {user_name(user)} удалил клиента #{cid} {esc(c['name'])}.",
                        exclude_user_id=user["id"])
    await cb.answer("Удалено")
    text, markup = await list_view(db, user, "all", 0)
    await show(cb, text, markup)


# --- новый клиент ---

@router.message(F.text == BTN_NEW_CLIENT)
async def new_client_start(message: Message, state: FSMContext):
    await state.clear()
    await state.set_state(NewClient.name)
    await message.answer("➕ <b>Новый клиент</b>\n\nВведите имя клиента:", reply_markup=cancel_kb())


@router.message(NewClient.name, F.text)
async def new_client_name(message: Message, state: FSMContext):
    name = " ".join(message.text.split())
    if not 1 <= len(name) <= 100:
        await message.answer("Введите имя (до 100 символов):", reply_markup=cancel_kb())
        return
    await state.update_data(name=name)
    await state.set_state(NewClient.phone)
    await message.answer("Введите телефон клиента:", reply_markup=cancel_kb())


@router.message(NewClient.phone, F.text | F.contact)
async def new_client_phone(message: Message, state: FSMContext, db: DB):
    phone = message.contact.phone_number if message.contact else message.text.strip()
    if len(re.sub(r"\D", "", phone)) < 7 or len(phone) > 25:
        await message.answer("Похоже, это не телефон. Введите ещё раз:", reply_markup=cancel_kb())
        return
    digits = re.sub(r"\D", "", phone)
    dup = await db.one(
        f"SELECT id, name FROM clients WHERE {PHONE} LIKE ?",
        f"%{digits[-9:]}%")
    await state.update_data(phone=phone)
    await state.set_state(NewClient.comment)
    warn = f"⚠️ Клиент с похожим номером уже есть: #{dup['id']} {esc(dup['name'])}\n\n" if dup else ""
    await message.answer(warn + "Комментарий к клиенту (или «-» чтобы пропустить):",
                         reply_markup=cancel_kb())


@router.message(NewClient.comment, F.text)
async def new_client_comment(message: Message, state: FSMContext, db: DB, user, bot: Bot):
    comment = None if message.text.strip() == "-" else message.text.strip()[:1500]
    await state.update_data(comment=comment)
    if is_admin(user):
        staff = await db.all("SELECT * FROM users WHERE nick IS NOT NULL ORDER BY role DESC, nick")
        rows = [[btn(("🙋 Себе" if u["id"] == user["id"] else user_name(u)), f"nc:w:{u['id']}")]
                for u in staff]
        rows.append([btn("✖️ Отмена", "cancel")])
        await state.set_state(NewClient.worker)
        await message.answer("Какому сотруднику отдать клиента?", reply_markup=kb(*rows))
        return
    await create_client(message, state, db, user, bot, user["id"])


@router.callback_query(NewClient.worker, F.data.startswith("nc:w:"))
async def new_client_worker(cb: CallbackQuery, state: FSMContext, db: DB, user, bot: Bot):
    await cb.answer()
    await create_client(cb.message, state, db, user, bot, int(cb.data.split(":")[2]))


async def create_client(message: Message, state: FSMContext, db: DB, user, bot: Bot, worker_id: int):
    data = await state.get_data()
    await state.clear()
    if "name" not in data:
        await message.answer("Данные устарели, начните заново.")
        return
    cur = await db.run(
        "INSERT INTO clients(name, phone, worker_id, status, created_by, created_at) "
        "VALUES (?, ?, ?, 'work', ?, ?)",
        data["name"], data["phone"], worker_id, user["id"], now(),
    )
    cid = cur.lastrowid
    if data.get("comment"):
        await db.run("INSERT INTO comments(client_id, author_id, text, created_at) VALUES (?, ?, ?, ?)",
                     cid, user["id"], data["comment"], now())
    worker = await db.get_user(worker_id)
    await db.audit(user["id"], f"Добавил клиента #{cid} {data['name']} (сотрудник {worker['nick'] if worker else '—'})")
    await notify_admins(
        bot, db,
        f"🆕 Новый клиент #{cid} {esc(data['name'])}, <code>{esc(data['phone'])}</code>\n"
        f"Сотрудник: {user_name(worker)} · добавил: {user_name(user)}",
        exclude_user_id=user["id"],
        reply_markup=kb([btn("Открыть", f"cl:v:{cid}")]),
    )
    if worker and worker["id"] != user["id"] and worker["role"] == "worker":
        await notify_user(bot, db, worker["id"], f"📥 Вам назначен новый клиент #{cid} {esc(data['name'])}.",
                          kb([btn("Открыть", f"cl:v:{cid}")]))
    await send_card(message, db, user, cid, "✅ Клиент добавлен.\n\n")
