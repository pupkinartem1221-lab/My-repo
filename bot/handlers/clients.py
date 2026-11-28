import re

from aiogram import Bot, F, Router
from aiogram.fsm.context import FSMContext
from aiogram.fsm.state import State, StatesGroup
from aiogram.types import CallbackQuery, Message

from ..db import DB
from ..keyboards import (BLUE, BTN_CLIENTS, BTN_NEW_CLIENT, GREEN, RED, back_btn, btn, cancel_kb, confirm_kb,
                         copy_btn, danger_btn, home_btn, kb, main_btn, pager, url_btn)
from ..notify import notify_admins, notify_user
from ..ui import show
from ..utils import (CLIENT_STATUSES, clip, esc, fit, fmt_money, fmt_short, is_admin, like_escape, messenger_links,
                     now, user_label, user_name)
from ..rules import RECEIPT_REQUIRED, set_status
from .requisites import req_copy_kb, req_for_client

router = Router(name="clients")
PAGE = 8
PHONE = "replace(replace(replace(replace(replace(phone,'+',''),' ',''),'-',''),'(',''),')','')"
FILTERS = {"all": "Все", **CLIENT_STATUSES}
STATUS_COLOR = {"work": BLUE, "paid": GREEN, "lost": RED}


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
    icon = CLIENT_STATUSES.get(c["status"], " ")[:1]
    label = f"{icon} {clip(c['name'], 26)}"
    if c["phone"]:
        label += f" · {c['phone'][-10:]}"
    return [btn(label, f"cl:v:{c['id']}")]


def req_line(r) -> str:
    if r is None:
        return "💳 Реквизит не выбран"
    mark = "" if r["is_active"] else " · 🔴 нерабочий!"
    return f"💳 …{esc(r['iban'][-6:])} {esc(clip(r['holder'], 30))}{mark}"


# ---------- список ----------

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
    rows = await db.all(f"SELECT * FROM clients {w} ORDER BY id DESC LIMIT ? OFFSET ?",
                        *params, PAGE, page * PAGE)
    title = "👥 <b>Клиенты</b>" if is_admin(user) else "👥 <b>Мои клиенты</b>"
    if total:
        text = f"{title} · {total}"
    elif flt == "all":
        text = f"{title}\n\nПока пусто. Нажмите «➕ Новый»."
    else:
        text = f"{title}\n\nС таким статусом никого нет."
    f = list(FILTERS.items())
    flt_rows = [[btn(v, f"cl:l:{k}:0", BLUE if k == flt else None) for k, v in f[i:i + 2]]
                for i in range(0, len(f), 2)]
    markup = kb(*flt_rows, *[client_btn(c) for c in rows], pager(f"cl:l:{flt}:", page, pages),
                [btn("🔍 Поиск", "cl:search"), main_btn("➕ Новый", "m:new")], [home_btn()])
    return text, markup


async def open_list(event, db: DB, user, flt="all", page=0):
    text, markup = await list_view(db, user, flt, page)
    await show(event, text, markup)


@router.message(F.text == BTN_CLIENTS)
async def clients_menu(message: Message, state: FSMContext, db: DB, user):
    await state.clear()
    await open_list(message, db, user)


@router.callback_query(F.data == "m:clients")
async def clients_menu_cb(cb: CallbackQuery, state: FSMContext, db: DB, user):
    await state.clear()
    await cb.answer()
    await open_list(cb, db, user)


@router.callback_query(F.data.startswith("cl:l:"))
async def clients_list_cb(cb: CallbackQuery, db: DB, user):
    _, _, flt, page = cb.data.split(":")
    await cb.answer()
    await open_list(cb, db, user, flt if flt in FILTERS else "all", int(page))


@router.callback_query(F.data == "cl:search")
async def search_start(cb: CallbackQuery, state: FSMContext):
    await state.set_state(ClientSearch.query)
    await state.set_data({})
    await cb.answer()
    await show(cb, "🔍 Введите имя или телефон:", cancel_kb())


@router.message(ClientSearch.query, F.text)
async def search_do(message: Message, state: FSMContext, db: DB, user):
    q = " ".join(message.text.split())
    if len(q) < 2:
        await show(message, "🔍 Нужно хотя бы 2 символа. Введите ещё раз:", cancel_kb())
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
    nav = [back_btn("cl:l:all:0", "« Клиенты"), home_btn()]
    if not rows:
        await show(message, f"🔍 «{esc(q)}» — ничего не найдено.", kb([btn("🔍 Искать ещё", "cl:search")], nav))
        return
    await show(message, f"🔍 «{esc(q)}» — найдено {len(rows)}:", kb(*[client_btn(c) for c in rows], nav))


# ---------- карточка ----------

async def card_view(db: DB, user, c, note: str = ""):
    worker = await db.get_user(c["worker_id"])
    req = await db.one("SELECT * FROM requisites WHERE id=?", c["requisite_id"]) if c["requisite_id"] else None
    sums = await db.one(
        "SELECT COUNT(*) n, COALESCE(SUM(CASE WHEN status='confirmed' THEN amount END),0) paid, "
        "COALESCE(SUM(CASE WHEN status='pending' THEN amount END),0) pend FROM payments WHERE client_id=?",
        c["id"])
    comments = await db.all("SELECT * FROM comments WHERE client_id=? ORDER BY id DESC LIMIT 5", c["id"])
    total_comments = (await db.one("SELECT COUNT(*) n FROM comments WHERE client_id=?", c["id"]))["n"]

    money = f"💰 Оплачено: <b>{fmt_money(sums['paid'])}</b>"
    if sums["pend"]:
        money += f" · ⏳ на проверке {fmt_money(sums['pend'])}"
    lines = [note, ""] if note else []
    lines += [
        f"👤 <b>{esc(c['name'])}</b>",
        f"📞 <code>{esc(c['phone'] or '—')}</code>",
        f"{CLIENT_STATUSES.get(c['status'], '')} · 👷 {user_name(worker)}",
        req_line(req),
        money,
    ]
    if comments:
        items, budget = [], 3700 - sum(len(x) + 1 for x in lines)
        for cm in comments:
            author = await db.get_user(cm["author_id"])
            item = f"• <i>{fmt_short(cm['created_at'])} {user_name(author)}:</i> {esc(clip(cm['text'], 300))}"
            if len(item) + 1 > budget:
                break
            items.append(item)
            budget -= len(item) + 1
        if items:
            lines.append("\n💬 <b>Комментарии</b>")
            lines.extend(reversed(items))

    cid = c["id"]
    status_row = [btn(v, f"cl:st:{cid}:{k}", STATUS_COLOR[k] if k == c["status"] else None)
                  for k, v in CLIENT_STATUSES.items()]
    comments_btn = (btn(f"💬 Все · {total_comments}", f"cl:cma:{cid}") if total_comments > len(comments)
                    else None)
    rows = [
        status_row,
        [main_btn("🧾 Квитанция", f"pay:new:{cid}"), btn("💳 Реквизит", f"cl:rq:{cid}")],
        [b for b in (btn("💬 Комментарий", f"cl:cm:{cid}"), comments_btn) if b],
        [btn(f"💰 Оплаты · {sums['n']}", f"pay:cl:{cid}")]
        + ([btn("✉️ Написать", f"cl:msg:{cid}")] if c["phone"] else []),
    ]
    if is_admin(user):
        rows.append([btn("👷 Передать", f"cl:w:{cid}"), danger_btn("🗑 Удалить", f"cl:del:{cid}")])
    rows.append([back_btn("cl:l:all:0", "« Клиенты"), home_btn()])
    return fit(lines), kb(*rows)


async def open_card(event, db: DB, user, cid: int, note: str = "") -> bool:
    c = await get_client_for(db, user, cid)
    if c is None:
        return False
    text, markup = await card_view(db, user, c, note)
    await show(event, text, markup)
    return True


@router.callback_query(F.data.startswith("cl:v:"))
async def client_card(cb: CallbackQuery, state: FSMContext, db: DB, user):
    await state.clear()
    if await get_client_for(db, user, int(cb.data.split(":")[2])) is None:
        return await cb.answer("Клиент не найден", show_alert=True)
    await cb.answer()
    await open_card(cb, db, user, int(cb.data.split(":")[2]))


@router.callback_query(F.data.startswith("cl:st:"))
async def client_status(cb: CallbackQuery, state: FSMContext, db: DB, user, bot: Bot):
    _, _, cid, st = cb.data.split(":")
    c = await get_client_for(db, user, int(cid))
    if c is None:
        return await cb.answer("Нет доступа", show_alert=True)
    if st not in CLIENT_STATUSES:
        return await cb.answer()
    if c["status"] == st:
        return await cb.answer("Статус уже такой")
    if not await set_status(db, c["id"], st):
        # «Оплачено» только с квитанцией: сразу просим её прикрепить
        from .payments import begin_receipt
        await cb.answer(RECEIPT_REQUIRED, show_alert=True)
        await begin_receipt(cb, state, c, set_paid=True)
        return
    old, new = CLIENT_STATUSES.get(c["status"], c["status"]), CLIENT_STATUSES[st]
    await db.audit(user["id"], f"Клиент #{c['id']}: {old} → {new}")
    await cb.answer(new)
    await open_card(cb, db, user, c["id"])
    await notify_admins(bot, db, f"🔁 {user_name(user)}: {esc(c['name'])} → <b>{new}</b>",
                        exclude_user_id=user["id"], reply_markup=kb([main_btn("👤 Открыть", f"cl:v:{c['id']}")]))


# ---------- связаться ----------

@router.callback_query(F.data.startswith("cl:msg:"))
async def client_contact(cb: CallbackQuery, db: DB, user):
    c = await get_client_for(db, user, int(cb.data.split(":")[2]))
    if c is None:
        return await cb.answer("Нет доступа", show_alert=True)
    links = messenger_links(c["phone"])
    await cb.answer()
    rows = []
    if links:
        rows.append([url_btn("🟢 WhatsApp", links["whatsapp"]), url_btn("✈️ Telegram", links["telegram"])])
        rows.append([copy_btn("📋 Скопировать номер", c["phone"])])
    else:
        rows.append([copy_btn("📋 Скопировать номер", c["phone"] or "")])
    rows.append([back_btn(f"cl:v:{c['id']}", "« К клиенту")])
    note = "" if links else "\n\n⚠️ Номер в неполном формате — ссылки на мессенджеры недоступны."
    await show(cb, f"💬 <b>{esc(c['name'])}</b>\n📞 <code>{esc(c['phone'] or '—')}</code>\n\n"
                   f"Где написать клиенту?{note}", kb(*rows))


# ---------- комментарии ----------

@router.callback_query(F.data.startswith("cl:cm:"))
async def comment_start(cb: CallbackQuery, state: FSMContext, db: DB, user):
    c = await get_client_for(db, user, int(cb.data.split(":")[2]))
    if c is None:
        return await cb.answer("Нет доступа", show_alert=True)
    await state.set_state(ClientComment.text)
    await state.set_data({"cid": c["id"]})
    await cb.answer()
    await show(cb, f"💬 Комментарий к <b>{esc(c['name'])}</b>:", kb([btn("✖️ Отмена", f"cl:v:{c['id']}")]))


@router.message(ClientComment.text, F.text)
async def comment_save(message: Message, state: FSMContext, db: DB, user):
    text = message.text.strip()
    cid = (await state.get_data()).get("cid")
    await state.clear()
    c = await get_client_for(db, user, cid) if cid else None
    if c is None:
        await show(message, "Клиент не найден.", kb([home_btn()]))
        return
    await db.run("INSERT INTO comments(client_id, author_id, text, created_at) VALUES (?, ?, ?, ?)",
                 cid, user["id"], text[:1500], now())
    await db.audit(user["id"], f"Комментарий к клиенту #{cid}")
    await open_card(message, db, user, cid, "✅ Комментарий сохранён")


@router.callback_query(F.data.startswith("cl:cma:"))
async def comments_all(cb: CallbackQuery, db: DB, user):
    c = await get_client_for(db, user, int(cb.data.split(":")[2]))
    if c is None:
        return await cb.answer("Нет доступа", show_alert=True)
    rows = await db.all("SELECT * FROM comments WHERE client_id=? ORDER BY id DESC LIMIT 40", c["id"])
    lines = [f"💬 <b>{esc(c['name'])}</b> · все комментарии\n"]
    for cm in reversed(rows):
        author = await db.get_user(cm["author_id"])
        lines.append(f"• <i>{fmt_short(cm['created_at'])} {user_name(author)}:</i> {esc(clip(cm['text'], 600))}")
    await cb.answer()
    await show(cb, fit(lines), kb([btn("💬 Добавить", f"cl:cm:{c['id']}")],
                                  [back_btn(f"cl:v:{c['id']}", "« К клиенту"), home_btn()]))


# ---------- реквизит клиента ----------

@router.callback_query(F.data.startswith("cl:rq:"))
async def client_req_pick(cb: CallbackQuery, db: DB, user):
    c = await get_client_for(db, user, int(cb.data.split(":")[2]))
    if c is None:
        return await cb.answer("Нет доступа", show_alert=True)
    reqs = await db.all("SELECT * FROM requisites WHERE is_active=1 ORDER BY id DESC LIMIT 50")
    rows = [[btn(clip(f"🟢 …{r['iban'][-6:]} · {r['holder']}", 60), f"cl:rqs:{c['id']}:{r['id']}",
                 BLUE if r["id"] == c["requisite_id"] else None)] for r in reqs]
    if c["requisite_id"]:
        rows.insert(0, [main_btn("📋 Показать текущий", f"cl:rqshow:{c['id']}")])
        rows.append([danger_btn("✖️ Отвязать", f"cl:rqs:{c['id']}:0")])
    rows.append([back_btn(f"cl:v:{c['id']}", "« К клиенту")])
    text = (f"💳 Реквизит для <b>{esc(c['name'])}</b>:" if reqs
            else "💳 Нет рабочих реквизитов. Попросите админа добавить.")
    await cb.answer()
    await show(cb, text, kb(*rows))


async def show_client_req(event, c, r, note: str = ""):
    head = f"{note}\n\n" if note else ""
    await show(event, f"{head}{req_for_client(r)}\n\n<i>Для клиента {esc(c['name'])}. Нажмите, чтобы скопировать:</i>",
               req_copy_kb(r, [back_btn(f"cl:v:{c['id']}", "« К клиенту"), home_btn()]))


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
            return await cb.answer("Реквизит нерабочий или удалён", show_alert=True)
    await db.run("UPDATE clients SET requisite_id=? WHERE id=?", rid or None, c["id"])
    await db.audit(user["id"], f"Клиент #{c['id']}: реквизит → {('#' + str(rid)) if rid else 'отвязан'}")
    await cb.answer("Сохранено")
    if r is None:
        await open_card(cb, db, user, c["id"], "✅ Реквизит отвязан")
    else:
        await show_client_req(cb, c, r, "✅ Реквизит выбран")


@router.callback_query(F.data.startswith("cl:rqshow:"))
async def client_req_show(cb: CallbackQuery, db: DB, user):
    c = await get_client_for(db, user, int(cb.data.split(":")[2]))
    if c is None or not c["requisite_id"]:
        return await cb.answer("Реквизит не выбран", show_alert=True)
    r = await db.one("SELECT * FROM requisites WHERE id=?", c["requisite_id"])
    if not r["is_active"]:
        return await cb.answer("⚠️ Этот реквизит нерабочий — выберите другой", show_alert=True)
    await cb.answer()
    await show_client_req(cb, c, r)


# ---------- передача / удаление (админ) ----------

@router.callback_query(F.data.startswith("cl:w:"))
async def client_worker_pick(cb: CallbackQuery, db: DB, user):
    if not is_admin(user):
        return await cb.answer("Нет доступа", show_alert=True)
    cid = int(cb.data.split(":")[2])
    c = await db.one("SELECT * FROM clients WHERE id=?", cid)
    if c is None:
        return await cb.answer("Клиент не найден", show_alert=True)
    staff = await db.all("SELECT * FROM users WHERE nick IS NOT NULL AND approved=1 ORDER BY role DESC, nick LIMIT 90")
    rows = [[btn(clip(user_label(u), 60), f"cl:ws:{cid}:{u['id']}", BLUE if u["id"] == c["worker_id"] else None)]
            for u in staff]
    rows.append([back_btn(f"cl:v:{cid}", "« К клиенту")])
    await cb.answer()
    await show(cb, f"👷 Кому передать <b>{esc(c['name'])}</b>?", kb(*rows))


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
    await cb.answer("Передано")
    await open_card(cb, db, user, c["id"], f"✅ Клиент передан: {user_name(worker)}")
    if c["worker_id"] and c["worker_id"] not in (user["id"], worker["id"]):
        await notify_user(bot, db, c["worker_id"], f"📤 Клиент {esc(c['name'])} передан другому сотруднику.")
    if worker["id"] != user["id"]:
        await notify_user(bot, db, worker["id"], f"📥 Вам передан клиент <b>{esc(c['name'])}</b>",
                          kb([main_btn("👤 Открыть", f"cl:v:{c['id']}")]))


@router.callback_query(F.data.startswith("cl:del:"))
async def client_delete_ask(cb: CallbackQuery, db: DB, user):
    if not is_admin(user):
        return await cb.answer("Нет доступа", show_alert=True)
    cid = int(cb.data.split(":")[2])
    c = await db.one("SELECT * FROM clients WHERE id=?", cid)
    if c is None:
        return await cb.answer("Уже удалён", show_alert=True)
    await cb.answer()
    await show(cb, f"🗑 Удалить <b>{esc(c['name'])}</b>?\n\nКомментарии удалятся, оплаты останутся в отчётах.",
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
    await open_list(cb, db, user)
    await notify_admins(bot, db, f"🗑 {user_name(user)} удалил клиента {esc(c['name'])}",
                        exclude_user_id=user["id"])


# ---------- новый клиент ----------

def skip_kb(skip_data: str):
    return kb([btn("⏭ Пропустить", skip_data), btn("✖️ Отмена", "cancel")])


async def new_client_begin(event, state: FSMContext):
    await state.clear()
    await state.set_state(NewClient.name)
    await state.set_data({})
    await show(event, "➕ <b>Новый клиент</b> · шаг 1 из 3\n\nИмя клиента:", cancel_kb())


@router.callback_query(F.data == "m:new")
async def new_client_start_cb(cb: CallbackQuery, state: FSMContext):
    await cb.answer()
    await new_client_begin(cb, state)


@router.message(F.text == BTN_NEW_CLIENT)
async def new_client_start(message: Message, state: FSMContext):
    await new_client_begin(message, state)


@router.message(NewClient.name, F.text)
async def new_client_name(message: Message, state: FSMContext):
    name = " ".join(message.text.split())
    if not 1 <= len(name) <= 100:
        await show(message, "➕ <b>Новый клиент</b> · шаг 1 из 3\n\nИмя до 100 символов:", cancel_kb())
        return
    await state.update_data(name=name)
    await state.set_state(NewClient.phone)
    await show(message, f"➕ <b>{esc(name)}</b> · шаг 2 из 3\n\nТелефон:", cancel_kb())


@router.message(NewClient.phone, F.text | F.contact)
async def new_client_phone(message: Message, state: FSMContext, db: DB, user):
    data = await state.get_data()
    name = esc(data.get("name", ""))
    phone = message.contact.phone_number if message.contact else " ".join(message.text.split())
    digits = re.sub(r"\D", "", phone)
    if not re.fullmatch(r"\+?[\d\s\-()]{7,25}", phone) or len(digits) < 7:
        await show(message, f"➕ <b>{name}</b> · шаг 2 из 3\n\n❗ Это не похоже на телефон. Ещё раз:", cancel_kb())
        return
    warn = ""
    if len(digits) >= 9:
        dup = await db.one(f"SELECT id, name, worker_id FROM clients WHERE {PHONE} LIKE ? ORDER BY id DESC",
                           f"%{digits[-9:]}")
        if dup and (is_admin(user) or dup["worker_id"] == user["id"]):
            warn = f"\n\n⚠️ Этот номер уже есть: {esc(dup['name'])}"
        elif dup:
            # сотруднику не раскрываем чужих клиентов — только факт
            warn = "\n\n⚠️ Этот номер уже есть у другого сотрудника"
    await state.update_data(phone=phone)
    await state.set_state(NewClient.comment)
    await show(message, f"➕ <b>{name}</b> · шаг 3 из 3{warn}\n\n"
                        "Комментарий: маршрут, дата поездки, детали.", skip_kb("nc:skip"))


@router.message(NewClient.comment, F.text)
async def new_client_comment(message: Message, state: FSMContext, db: DB, user, bot: Bot):
    await state.update_data(comment=message.text.strip()[:1500] or None)
    await after_comment(message, state, db, user, bot)


@router.callback_query(NewClient.comment, F.data == "nc:skip")
async def new_client_skip(cb: CallbackQuery, state: FSMContext, db: DB, user, bot: Bot):
    await cb.answer()
    await state.update_data(comment=None)
    await after_comment(cb, state, db, user, bot)


async def after_comment(event, state: FSMContext, db: DB, user, bot: Bot):
    if is_admin(user):
        staff = await db.all(
            "SELECT * FROM users WHERE nick IS NOT NULL AND approved=1 ORDER BY role DESC, nick LIMIT 90")
        rows = [[btn("🙋 Себе" if u["id"] == user["id"] else clip(user_label(u), 60), f"nc:w:{u['id']}",
                     BLUE if u["id"] == user["id"] else None)] for u in staff]
        rows.append([btn("✖️ Отмена", "cancel")])
        await state.set_state(NewClient.worker)
        await show(event, "👷 Кому отдать клиента?", kb(*rows))
        return
    await create_client(event, state, db, user, bot, user["id"])


@router.callback_query(NewClient.worker, F.data.startswith("nc:w:"))
async def new_client_worker(cb: CallbackQuery, state: FSMContext, db: DB, user, bot: Bot):
    if not is_admin(user):
        await state.clear()
        return await cb.answer("Нет доступа", show_alert=True)
    worker = await db.one("SELECT id FROM users WHERE id=? AND nick IS NOT NULL AND approved=1",
                          int(cb.data.split(":")[2]))
    if worker is None:
        return await cb.answer("Сотрудник не найден", show_alert=True)
    await cb.answer()
    await create_client(cb, state, db, user, bot, worker["id"])


async def create_client(event, state: FSMContext, db: DB, user, bot: Bot, worker_id: int):
    data = await state.get_data()
    await state.clear()
    if "name" not in data or "phone" not in data:
        await show(event, "Данные устарели, начните заново.", kb([home_btn()]))
        return
    cur = await db.run(
        "INSERT INTO clients(name, phone, worker_id, status, created_by, created_at) VALUES (?, ?, ?, 'work', ?, ?)",
        data["name"], data["phone"], worker_id, user["id"], now())
    cid = cur.lastrowid
    if data.get("comment"):
        await db.run("INSERT INTO comments(client_id, author_id, text, created_at) VALUES (?, ?, ?, ?)",
                     cid, user["id"], data["comment"], now())
    worker = await db.get_user(worker_id)
    await db.audit(user["id"], f"Добавил клиента #{cid} {data['name']} (сотрудник {worker['nick'] if worker else '—'})")
    await open_card(event, db, user, cid, "✅ Клиент добавлен")
    open_kb = kb([main_btn("👤 Открыть", f"cl:v:{cid}")])
    await notify_admins(bot, db, f"🆕 <b>{esc(data['name'])}</b> · {esc(data['phone'])}\n"
                                 f"👷 {user_name(worker)}", exclude_user_id=user["id"], reply_markup=open_kb)
    if worker and worker["id"] != user["id"] and worker["role"] == "worker":
        await notify_user(bot, db, worker["id"], f"📥 Новый клиент: <b>{esc(data['name'])}</b>", open_kb)
