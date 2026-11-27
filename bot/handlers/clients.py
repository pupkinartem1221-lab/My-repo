import re

from aiogram import Bot, F, Router
from aiogram.fsm.context import FSMContext
from aiogram.fsm.state import State, StatesGroup
from aiogram.types import CallbackQuery, Message

from ..db import DB
from ..keyboards import (BLUE, BTN_CLIENTS, BTN_NEW_CLIENT, GREEN, RED, back_btn, btn, cancel_kb, confirm_kb,
                         copy_btn, danger_btn, home_btn, kb, main_btn, pager)
from ..notify import notify_admins, notify_user
from ..utils import (CLIENT_STATUSES, clip, esc, fit, fmt_dt, fmt_money, is_admin, like_escape, now,
                     user_label, user_name)
from .common import show
from .requisites import req_copy_kb, req_for_client, req_short

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
    label = f"{icon} #{c['id']} {clip(c['name'], 28)}"
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

    # активный фильтр подсвечен синим
    flt_row = [btn(v if k == "all" else v.split(" ")[0], f"cl:l:{k}:0", BLUE if k == flt else None)
               for k, v in FILTERS.items()]
    markup = kb(flt_row, *[client_btn(c) for c in rows], pager(f"cl:l:{flt}:", page, pages),
                [btn("🔍 Поиск", "cl:search"), main_btn("➕ Новый клиент", "m:new")], [home_btn()])
    return text, markup


@router.message(F.text == BTN_CLIENTS)
async def clients_menu(message: Message, state: FSMContext, db: DB, user):
    await state.clear()
    text, markup = await list_view(db, user, "all", 0)
    await message.answer(text, reply_markup=markup)


@router.callback_query(F.data == "m:clients")
async def clients_menu_cb(cb: CallbackQuery, state: FSMContext, db: DB, user):
    await state.clear()
    text, markup = await list_view(db, user, "all", 0)
    await cb.answer()
    await show(cb, text, markup)


@router.callback_query(F.data.startswith("cl:l:"))
async def clients_list_cb(cb: CallbackQuery, db: DB, user):
    _, _, flt, page = cb.data.split(":")
    text, markup = await list_view(db, user, flt if flt in FILTERS else "all", int(page))
    await cb.answer()
    await show(cb, text, markup)


@router.callback_query(F.data == "cl:search")
async def search_start(cb: CallbackQuery, state: FSMContext):
    await state.set_state(ClientSearch.query)
    await state.set_data({})
    await cb.answer()
    await cb.message.answer("Введите имя или телефон клиента для поиска:", reply_markup=cancel_kb())


@router.message(ClientSearch.query, F.text)
async def search_do(message: Message, state: FSMContext, db: DB, user):
    q = " ".join(message.text.split())
    if len(q) < 2:
        await message.answer("Введите хотя бы 2 символа:", reply_markup=cancel_kb())
        return
    digits = re.sub(r"\D", "", q)
    if len(digits) < 3:
        digits = ""
    sql = f"SELECT * FROM clients WHERE (ulower(name) LIKE ? ESCAPE '\\' OR (? <> '' AND {PHONE} LIKE ?))"
    params = [f"%{like_escape(q.lower())}%", digits, f"%{digits}%"]
    if not is_admin(user):
        sql += " AND worker_id=?"
        params.append(user["id"])
    rows = await db.all(sql + " ORDER BY id DESC LIMIT 20", *params)
    await state.clear()
    if not rows:
        await message.answer("🔍 Ничего не найдено.", reply_markup=kb(
            [btn("🔍 Искать ещё", "cl:search")], [back_btn("cl:l:all:0", "« К списку"), home_btn()]))
        return
    await message.answer(f"🔍 Найдено: {len(rows)}",
                         reply_markup=kb(*[client_btn(c) for c in rows], [back_btn("cl:l:all:0", "« К списку"), home_btn()]))


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
    total_comments = (await db.one("SELECT COUNT(*) n FROM comments WHERE client_id=?", c["id"]))["n"]

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
        # новые комментарии важнее: при нехватке места отбрасываются самые старые
        items, budget = [], 3800 - sum(len(x) + 1 for x in lines)
        for cm in comments:
            author = await db.get_user(cm["author_id"])
            item = f"• <i>{fmt_dt(cm['created_at'])}, {user_name(author)}:</i> {esc(clip(cm['text'], 300))}"
            if len(item) + 1 > budget:
                break
            items.append(item)
            budget -= len(item) + 1
        if items:
            more = f" (всего {total_comments})" if total_comments > len(items) else ""
            lines.append(f"\n💬 <b>Последние комментарии{more}:</b>")
            lines.extend(reversed(items))

    cid = c["id"]
    # текущий статус подсвечен своим цветом, остальные — обычные
    colors = {"work": BLUE, "paid": GREEN, "lost": RED}
    status_row = [btn(("✔️ " if k == c["status"] else "") + v, f"cl:st:{cid}:{k}",
                      colors[k] if k == c["status"] else None)
                  for k, v in CLIENT_STATUSES.items()]
    rows = [
        status_row,
        [main_btn("🧾 Добавить квитанцию", f"pay:new:{cid}")],
        [btn("💳 Реквизит", f"cl:rq:{cid}"), btn(f"💰 Оплаты ({sums['n']})", f"pay:cl:{cid}")],
        [btn("💬 Комментарий", f"cl:cm:{cid}"), btn("📝 Все комментарии", f"cl:cma:{cid}")],
    ]
    if c["phone"]:
        rows.append([copy_btn("📋 Скопировать телефон", c["phone"])])
    if is_admin(user):
        rows.append([btn("👤 Сменить сотрудника", f"cl:w:{cid}"), danger_btn("🗑 Удалить", f"cl:del:{cid}")])
    rows.append([back_btn("cl:l:all:0", "« К списку"), home_btn()])
    return fit(lines), kb(*rows)


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
    await cb.answer("Статус изменён")
    fresh = await db.one("SELECT * FROM clients WHERE id=?", c["id"])
    text, markup = await card_view(db, user, fresh)
    await show(cb, text, markup)
    await notify_admins(
        bot, db,
        f"🔁 {user_name(user)} сменил статус клиента #{c['id']} {esc(c['name'])}: {old} → <b>{new}</b>",
        exclude_user_id=user["id"],
    )


# --- комментарии ---

@router.callback_query(F.data.startswith("cl:cm:"))
async def comment_start(cb: CallbackQuery, state: FSMContext, db: DB, user):
    c = await get_client_for(db, user, int(cb.data.split(":")[2]))
    if c is None:
        return await cb.answer("Нет доступа", show_alert=True)
    await state.set_state(ClientComment.text)
    await state.set_data({"cid": c["id"]})
    await cb.answer()
    await cb.message.answer(f"💬 Введите комментарий к клиенту #{c['id']} {esc(c['name'])}:",
                            reply_markup=cancel_kb())


@router.message(ClientComment.text, F.text)
async def comment_save(message: Message, state: FSMContext, db: DB, user):
    text = message.text.strip()
    if not text:
        await message.answer("Комментарий пустой. Введите текст:", reply_markup=cancel_kb())
        return
    cid = (await state.get_data()).get("cid")
    await state.clear()
    c = await get_client_for(db, user, cid) if cid else None
    if c is None:
        await message.answer("Клиент не найден.")
        return
    await db.run("INSERT INTO comments(client_id, author_id, text, created_at) VALUES (?, ?, ?, ?)",
                 cid, user["id"], text[:1500], now())
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
        line = f"\n• <i>{fmt_dt(cm['created_at'])}, {user_name(author)}:</i> {esc(clip(cm['text'], 1500))}"
        if len(chunk) + len(line) > 3900:
            await cb.message.answer(chunk)
            chunk = ""
        chunk += line
    await cb.message.answer(chunk, reply_markup=kb([back_btn(f"cl:v:{c['id']}", "« К клиенту")]))


# --- реквизит клиента ---

@router.callback_query(F.data.startswith("cl:rq:"))
async def client_req_pick(cb: CallbackQuery, db: DB, user):
    c = await get_client_for(db, user, int(cb.data.split(":")[2]))
    if c is None:
        return await cb.answer("Нет доступа", show_alert=True)
    reqs = await db.all("SELECT * FROM requisites WHERE is_active=1 ORDER BY id DESC LIMIT 50")
    rows = [[btn(clip(f"🟢 #{r['id']} {r['iban'][-8:]} · {r['holder']}", 60), f"cl:rqs:{c['id']}:{r['id']}")]
            for r in reqs]
    if c["requisite_id"]:
        rows.append([main_btn("📋 Реквизит для отправки клиенту", f"cl:rqshow:{c['id']}")])
        rows.append([danger_btn("✖️ Отвязать реквизит", f"cl:rqs:{c['id']}:0")])
    rows.append([back_btn(f"cl:v:{c['id']}", "« К клиенту")])
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
        await cb.message.answer(req_for_client(r), reply_markup=req_copy_kb(r))


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
    await cb.message.answer(req_for_client(r), reply_markup=req_copy_kb(r))


# --- смена сотрудника / удаление (админ) ---

@router.callback_query(F.data.startswith("cl:w:"))
async def client_worker_pick(cb: CallbackQuery, db: DB, user):
    if not is_admin(user):
        return await cb.answer("Нет доступа", show_alert=True)
    cid = int(cb.data.split(":")[2])
    staff = await db.all("SELECT * FROM users WHERE nick IS NOT NULL AND approved=1 ORDER BY role DESC, nick LIMIT 90")
    rows = [[btn(clip(user_label(u), 60), f"cl:ws:{cid}:{u['id']}")] for u in staff]
    rows.append([back_btn(f"cl:v:{cid}", "« К клиенту")])
    await cb.answer()
    await show(cb, f"👤 Выберите сотрудника для клиента #{cid}:", kb(*rows))


@router.callback_query(F.data.startswith("cl:ws:"))
async def client_worker_set(cb: CallbackQuery, db: DB, user, bot: Bot):
    if not is_admin(user):
        return await cb.answer("Нет доступа", show_alert=True)
    _, _, cid, uid = cb.data.split(":")
    c = await db.one("SELECT * FROM clients WHERE id=?", int(cid))
    worker = await db.one("SELECT * FROM users WHERE id=? AND nick IS NOT NULL AND approved=1", int(uid))
    if c is None or worker is None:
        return await cb.answer("Не найдено", show_alert=True)
    if c["worker_id"] == worker["id"]:
        return await cb.answer("Клиент уже у этого сотрудника")
    # неподтверждённые оплаты переходят вместе с клиентом
    await db.run_many([
        ("UPDATE clients SET worker_id=? WHERE id=?", worker["id"], c["id"]),
        ("UPDATE payments SET worker_id=? WHERE client_id=? AND status='pending'", worker["id"], c["id"]),
    ])
    await db.audit(user["id"], f"Клиент #{c['id']} передан {worker['nick']}")
    if c["worker_id"] and c["worker_id"] not in (user["id"], worker["id"]):
        await notify_user(bot, db, c["worker_id"], f"📤 Клиент #{c['id']} {esc(c['name'])} передан другому сотруднику.")
    if worker["id"] != user["id"]:
        await notify_user(bot, db, worker["id"],
                          f"📥 Вам передан клиент #{c['id']} {esc(c['name'])}.",
                          kb([main_btn("👤 Открыть клиента", f"cl:v:{c['id']}")]))
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
               confirm_kb(f"cl:delok:{cid}", f"cl:v:{cid}"))


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
    await cb.answer("Удалено")
    await notify_admins(bot, db, f"🗑 {user_name(user)} удалил клиента #{cid} {esc(c['name'])}.",
                        exclude_user_id=user["id"])
    text, markup = await list_view(db, user, "all", 0)
    await show(cb, text, markup)


# --- новый клиент ---

@router.callback_query(F.data == "m:new")
async def new_client_start_cb(cb: CallbackQuery, state: FSMContext):
    await cb.answer()
    await new_client_start(cb.message, state)


@router.message(F.text == BTN_NEW_CLIENT)
async def new_client_start(message: Message, state: FSMContext):
    await state.clear()
    await state.set_state(NewClient.name)
    await state.set_data({})
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
async def new_client_phone(message: Message, state: FSMContext, db: DB, user):
    phone = message.contact.phone_number if message.contact else " ".join(message.text.split())
    digits = re.sub(r"\D", "", phone)
    if not re.fullmatch(r"\+?[\d\s\-()]{7,25}", phone) or len(digits) < 7:
        await message.answer("Похоже, это не телефон. Введите ещё раз:", reply_markup=cancel_kb())
        return
    warn = ""
    if len(digits) >= 9:
        dup = await db.one(f"SELECT id, name, worker_id FROM clients WHERE {PHONE} LIKE ? ORDER BY id DESC",
                           f"%{digits[-9:]}")
        if dup and (is_admin(user) or dup["worker_id"] == user["id"]):
            warn = f"⚠️ Клиент с таким номером уже есть: #{dup['id']} {esc(dup['name'])}\n\n"
        elif dup:
            # сотруднику не раскрываем чужих клиентов — только факт
            warn = "⚠️ Клиент с таким номером уже есть в базе у другого сотрудника.\n\n"
    await state.update_data(phone=phone)
    await state.set_state(NewClient.comment)
    await message.answer(warn + "Комментарий к клиенту (или «-» чтобы пропустить):",
                         reply_markup=cancel_kb())


@router.message(NewClient.comment, F.text)
async def new_client_comment(message: Message, state: FSMContext, db: DB, user, bot: Bot):
    comment = None if message.text.strip() in ("-", "") else message.text.strip()[:1500]
    await state.update_data(comment=comment)
    if is_admin(user):
        staff = await db.all(
            "SELECT * FROM users WHERE nick IS NOT NULL AND approved=1 ORDER BY role DESC, nick LIMIT 90")
        rows = [[btn(("🙋 Себе" if u["id"] == user["id"] else clip(user_label(u), 60)), f"nc:w:{u['id']}",
                     BLUE if u["id"] == user["id"] else None)]
                for u in staff]
        rows.append([btn("✖️ Отмена", "cancel")])
        await state.set_state(NewClient.worker)
        await message.answer("Какому сотруднику отдать клиента?", reply_markup=kb(*rows))
        return
    await create_client(message, state, db, user, bot, user["id"])


@router.callback_query(NewClient.worker, F.data.startswith("nc:w:"))
async def new_client_worker(cb: CallbackQuery, state: FSMContext, db: DB, user, bot: Bot):
    if not is_admin(user):
        await state.clear()
        return await cb.answer("Нет доступа", show_alert=True)
    worker = await db.one("SELECT id FROM users WHERE id=? AND nick IS NOT NULL AND approved=1",
                          int(cb.data.split(":")[2]))
    if worker is None:
        return await cb.answer("Сотрудник не найден, выберите другого", show_alert=True)
    await cb.answer()
    try:
        await cb.message.edit_reply_markup(reply_markup=None)
    except Exception:
        pass
    await create_client(cb.message, state, db, user, bot, worker["id"])


async def create_client(message: Message, state: FSMContext, db: DB, user, bot: Bot, worker_id: int):
    data = await state.get_data()
    await state.clear()
    if "name" not in data or "phone" not in data:
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
        reply_markup=kb([main_btn("👤 Открыть клиента", f"cl:v:{cid}")]),
    )
    if worker and worker["id"] != user["id"] and worker["role"] == "worker":
        await notify_user(bot, db, worker["id"], f"📥 Вам назначен новый клиент #{cid} {esc(data['name'])}.",
                          kb([main_btn("👤 Открыть клиента", f"cl:v:{cid}")]))
    await send_card(message, db, user, cid, "✅ Клиент добавлен.\n\n")
