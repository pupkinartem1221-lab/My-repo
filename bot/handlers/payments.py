import asyncio

from aiogram import Bot, F, Router
from aiogram.exceptions import TelegramBadRequest
from aiogram.fsm.context import FSMContext
from aiogram.fsm.state import State, StatesGroup
from aiogram.types import CallbackQuery, Message

from ..db import DB
from ..keyboards import (BTN_RECEIPTS, back_btn, btn, confirm_kb, danger_btn, home_btn, kb, main_btn, ok_btn)
from ..notify import HIDE, notify_admins, notify_user, send_file_safe
from ..ui import extra_file, show
from ..utils import (PAYMENT_STATUSES, clip, deleted_req_label, esc, fit, fmt_money, fmt_short, is_admin, now, parse_money,
                     user_name)
from ..rules import confirm_payment, delete_payment, reject_payment
from .clients import get_client_for, open_card

router = Router(name="payments")

ALLOWED_MIME = {"image/jpeg", "image/png", "image/webp", "image/heic", "image/heif", "application/pdf"}
MAX_FILE = 20 * 1024 * 1024


class Receipt(StatesGroup):
    file = State()
    amount = State()
    requisite = State()


async def payment_caption(db: DB, p, viewer) -> str:
    admin = is_admin(viewer)
    client = await db.one("SELECT * FROM clients WHERE id=?", p["client_id"]) if p["client_id"] else None
    req = await db.one("SELECT * FROM requisites WHERE id=?", p["requisite_id"]) if p["requisite_id"] else None
    worker = await db.get_user(p["worker_id"])
    if client:
        who = f"👤 {esc(clip(client['name'], 50))} · {esc(client['phone'] or '')}"
    else:
        who = f"👤 {esc(clip(p['client_name'] or '—', 50))} (удалён)"
    if req and (admin or req["is_active"]):
        where = f"💳 …{esc(req['iban'][-6:])} {esc(clip(req['holder'], 30))}"
    elif p["requisite_label"] and admin:
        where = f"💳 {esc(deleted_req_label(p['requisite_label']))}"
    else:
        where = "💳 —"
    lines = [
        f"🧾 <b>{fmt_money(p['amount'])}</b> · {PAYMENT_STATUSES[p['status']]}",
        who,
        where,
        f"👷 {user_name(worker)} · {fmt_short(p['submitted_at'])}",
    ]
    if p["status"] != "pending":
        reviewer = await db.get_user(p["reviewed_by"])
        lines.append(f"{'✅' if p['status'] == 'confirmed' else '❌'} {user_name(reviewer)} · {fmt_short(p['reviewed_at'])}")
    # заработок видят только админы и сам сотрудник этой оплаты
    if (p["status"] == "confirmed" and p["worker_share"] is not None
            and (admin or p["worker_id"] == viewer["id"])):
        lines.append(f"💵 Заработок сотрудника: {fmt_money(p['worker_share'])} ({(p['worker_percent'] or 0):g}%)")
    return fit(lines, 1000)


def payment_kb(p, admin: bool, closable: bool = True):
    rows = []
    if admin and p["status"] == "pending":
        rows.append([ok_btn("✅ Подтвердить", f"pay:ok:{p['id']}"), danger_btn("❌ Отклонить", f"pay:no:{p['id']}")])
    bottom = []
    if p["client_id"]:
        bottom.append(btn("👤 Клиент", f"cl:v:{p['client_id']}"))
    if admin and p["status"] != "pending":
        bottom.append(danger_btn("🗑", f"pay:del:{p['id']}"))
    if closable:
        bottom.append(HIDE)
    rows.append(bottom)
    return kb(*rows)


async def can_view(db: DB, user, p) -> bool:
    if is_admin(user) or p["submitted_by"] == user["id"] or p["worker_id"] == user["id"]:
        return True
    if p["client_id"]:
        return await get_client_for(db, user, p["client_id"]) is not None
    return False


# ---------- загрузка квитанции ----------

def step(c_name: str, n: int) -> str:
    return f"🧾 <b>Квитанция</b> · {esc(c_name)} · шаг {n} из 2\n\n"


async def begin_receipt(event, state: FSMContext, c, set_paid: bool = False):
    await state.set_state(Receipt.file)
    await state.set_data({"cid": c["id"], "cname": c["name"], "set_paid": set_paid})
    head = "✅ Чтобы поставить «Оплачено», прикрепите квитанцию\n\n" if set_paid else ""
    await show(event, head + step(c["name"], 1) + "📎 Пришлите фото или файл квитанции:",
               kb([btn("✖️ Отмена", f"cl:v:{c['id']}")]))


@router.callback_query(F.data.startswith("pay:new:"))
async def receipt_start(cb: CallbackQuery, state: FSMContext, db: DB, user):
    c = await get_client_for(db, user, int(cb.data.split(":")[2]))
    if c is None:
        return await cb.answer("Нет доступа", show_alert=True)
    await cb.answer()
    await begin_receipt(cb, state, c)


@router.message(Receipt.file, F.photo | F.document)
async def receipt_file(message: Message, state: FSMContext):
    data = await state.get_data()
    back = kb([btn("✖️ Отмена", f"cl:v:{data.get('cid', 0)}")])
    if message.photo:
        file_id, file_type = message.photo[-1].file_id, "photo"
    else:
        doc = message.document
        name = (doc.file_name or "").lower()
        ok_ext = name.endswith((".jpg", ".jpeg", ".png", ".webp", ".heic", ".heif", ".pdf"))
        if (doc.mime_type or "") not in ALLOWED_MIME or not ok_ext or (doc.file_size or 0) > MAX_FILE:
            await show(message, step(data.get("cname", ""), 1) + "❗ Нужна картинка или PDF до 20 МБ:", back)
            return
        file_id, file_type = doc.file_id, "document"
    await state.update_data(file_id=file_id, file_type=file_type)
    await state.set_state(Receipt.amount)
    await show(message, step(data.get("cname", ""), 2) + "✅ Квитанция получена\n\n💰 Сумма в гривнах:", back)


@router.message(Receipt.file)
async def receipt_file_wrong(message: Message, state: FSMContext):
    data = await state.get_data()
    await show(message, step(data.get("cname", ""), 1) + "📎 Нужно фото или файл квитанции:",
               kb([btn("✖️ Отмена", f"cl:v:{data.get('cid', 0)}")]))


@router.message(Receipt.amount, F.text)
async def receipt_amount(message: Message, state: FSMContext, db: DB, user, bot: Bot):
    data = await state.get_data()
    back = kb([btn("✖️ Отмена", f"cl:v:{data.get('cid', 0)}")])
    amount = parse_money(message.text)
    if amount is None:
        await show(message, step(data.get("cname", ""), 2) + "❗ Введите число, например 3500 или 3500,50:", back)
        return
    await state.update_data(amount=amount)
    data = await state.get_data()
    c = await get_client_for(db, user, data.get("cid") or 0)
    if c is None or "file_id" not in data:
        await state.clear()
        await show(message, "Данные устарели, начните заново.", kb([home_btn()]))
        return
    if c["requisite_id"] and await db.one("SELECT id FROM requisites WHERE id=? AND is_active=1", c["requisite_id"]):
        await finalize(message, state, db, user, bot, c["requisite_id"])
        return
    reqs = await db.all("SELECT * FROM requisites WHERE is_active=1 ORDER BY id DESC LIMIT 50")
    if not reqs:
        await finalize(message, state, db, user, bot, None)
        return
    await state.set_state(Receipt.requisite)
    rows = [[btn(clip(f"…{r['iban'][-6:]} · {r['holder']}", 60), f"pay:rq:{r['id']}")] for r in reqs]
    rows.append([btn("✖️ Отмена", f"cl:v:{c['id']}")])
    await show(message, f"🧾 {fmt_money(amount)} · {esc(c['name'])}\n\n💳 На какой реквизит пришли деньги?", kb(*rows))


@router.message(Receipt.amount)
async def receipt_amount_wrong(message: Message, state: FSMContext):
    data = await state.get_data()
    await show(message, step(data.get("cname", ""), 2) + "💰 Введите сумму числом:",
               kb([btn("✖️ Отмена", f"cl:v:{data.get('cid', 0)}")]))


@router.callback_query(Receipt.requisite, F.data.startswith("pay:rq:"))
async def receipt_requisite(cb: CallbackQuery, state: FSMContext, db: DB, user, bot: Bot):
    r = await db.one("SELECT id FROM requisites WHERE id=? AND is_active=1", int(cb.data.split(":")[2]))
    if r is None:
        return await cb.answer("Реквизит нерабочий — выберите другой", show_alert=True)
    await cb.answer()
    await finalize(cb, state, db, user, bot, r["id"])


async def finalize(event, state: FSMContext, db: DB, user, bot: Bot, requisite_id):
    data = await state.get_data()
    if "file_id" not in data or "amount" not in data:
        return  # уже оформлено параллельным нажатием
    await state.clear()
    c = await get_client_for(db, user, data.get("cid") or 0)
    if c is None:
        await show(event, "Клиент не найден.", kb([home_btn()]))
        return
    req = await db.one("SELECT * FROM requisites WHERE id=?", requisite_id) if requisite_id else None
    label = f"{req['iban']} ({req['holder']})" if req else None
    cur = await db.run(
        "INSERT INTO payments(client_id, client_name, requisite_id, requisite_label, worker_id, amount, "
        "file_id, file_type, status, submitted_by, submitted_at) VALUES (?, ?, ?, ?, ?, ?, ?, ?, 'pending', ?, ?)",
        c["id"], c["name"], req["id"] if req else None, label, c["worker_id"], data["amount"],
        data["file_id"], data["file_type"], user["id"], now())
    pid = cur.lastrowid
    if req and not c["requisite_id"] and req["is_active"]:
        await db.run("UPDATE clients SET requisite_id=? WHERE id=?", req["id"], c["id"])
    await db.audit(user["id"], f"Квитанция #{pid}: клиент #{c['id']}, {fmt_money(data['amount'])}")
    note = (f"✅ Квитанция на {fmt_money(data['amount'])} добавлена — подтвердите её в «🧾 Квитанции»"
            if is_admin(user) else f"✅ Квитанция на {fmt_money(data['amount'])} отправлена на проверку")
    if data.get("set_paid") and c["status"] != "paid":
        await db.run("UPDATE clients SET status='paid' WHERE id=?", c["id"])
        await db.audit(user["id"], f"Клиент #{c['id']}: → ✅ Оплачено (с квитанцией #{pid})")
        note += "\nСтатус: ✅ Оплачено"
    await open_card(event, db, user, c["id"], note)
    p = await db.one("SELECT * FROM payments WHERE id=?", pid)
    for admin in await db.all("SELECT * FROM users WHERE role IN ('owner','admin') AND tg_id IS NOT NULL "
                              "AND approved=1 AND id<>?", user["id"]):
        await send_file_safe(bot, admin["tg_id"], p["file_id"], p["file_type"],
                             "🔔 Новая квитанция\n" + await payment_caption(db, p, admin), payment_kb(p, True))
        await asyncio.sleep(0.05)


# ---------- проверка админом ----------

async def refresh_card(cb: CallbackQuery, caption: str, markup):
    msg = cb.message
    try:
        if isinstance(msg, Message) and (msg.photo or msg.document):
            await msg.edit_caption(caption=caption, reply_markup=markup)
        else:
            await show(cb, caption, markup)
    except TelegramBadRequest:
        pass


@router.callback_query(F.data.startswith("pay:ok:") | F.data.startswith("pay:no:"))
async def receipt_review(cb: CallbackQuery, db: DB, user, bot: Bot):
    if not is_admin(user):
        return await cb.answer("Нет доступа", show_alert=True)
    _, action, pid = cb.data.split(":")
    pid = int(pid)
    reverted = False
    if action == "ok":
        changed = await confirm_payment(db, pid, user["id"], now())
    else:
        changed, reverted = await reject_payment(db, pid, user["id"], now())
    p = await db.one("SELECT * FROM payments WHERE id=?", pid)
    if p is None:
        return await cb.answer("Квитанция удалена", show_alert=True)
    if not changed:
        await cb.answer("Уже проверена", show_alert=True)
        await refresh_card(cb, await payment_caption(db, p, user), payment_kb(p, True))
        return

    name, amount = esc(p["client_name"]), fmt_money(p["amount"])
    if action == "ok":
        await db.audit(user["id"], f"Подтвердил квитанцию #{pid} ({amount})")
        worker_text = f"✅ Оплата подтверждена: {name} · {amount}\n💵 Ваш заработок: <b>{fmt_money(p['worker_share'])}</b>"
        submitter_text = f"✅ Оплата подтверждена: {name} · {amount}"
        other_text = f"✅ {user_name(user)} подтвердил: {name} · {amount}"
        await cb.answer("✅ Подтверждено")
    else:
        await db.audit(user["id"], f"Отклонил квитанцию #{pid} ({amount})")
        worker_text = submitter_text = f"❌ Квитанция отклонена: {name} · {amount}"
        if reverted:
            worker_text = submitter_text = worker_text + "\nСтатус клиента вернулся в 🔄 В работе"
        other_text = f"❌ {user_name(user)} отклонил: {name} · {amount}"
        await cb.answer("❌ Отклонено")

    await refresh_card(cb, await payment_caption(db, p, user), payment_kb(p, True))
    open_kb = kb([main_btn("👤 Открыть клиента", f"cl:v:{p['client_id']}")]) if p["client_id"] else None
    notified = {user["id"]}
    for uid, text in ((p["worker_id"], worker_text), (p["submitted_by"], submitter_text)):
        if uid and uid not in notified:
            target = await db.get_user(uid)
            if target and not is_admin(target):
                await notify_user(bot, db, uid, text, open_kb)
            notified.add(uid)
    await notify_admins(bot, db, other_text, exclude_user_id=user["id"])


async def pending_view(event, db: DB, user, bot: Bot):
    rows = await db.all("SELECT * FROM payments WHERE status='pending' ORDER BY id")
    if not rows:
        await show(event, "🧾 <b>Квитанции</b>\n\nВсё проверено ✨", kb([home_btn()]))
        return
    total = sum(r["amount"] for r in rows)
    more = f"\nПоказаны первые 10 из {len(rows)}." if len(rows) > 10 else ""
    await show(event, f"🧾 <b>На проверке: {len(rows)}</b> · {fmt_money(total)}{more}\n\n👇 Квитанции ниже",
               kb([main_btn("🔄 Обновить", "m:receipts"), home_btn()]))
    for p in rows[:10]:
        await extra_file(bot, event.from_user.id, p["file_id"], p["file_type"],
                         await payment_caption(db, p, user), payment_kb(p, True, closable=False))
        await asyncio.sleep(0.3)


@router.message(F.text == BTN_RECEIPTS)
async def pending_list(message: Message, state: FSMContext, db: DB, user, bot: Bot):
    await state.clear()
    if not is_admin(user):
        return
    await pending_view(message, db, user, bot)


@router.callback_query(F.data == "m:receipts")
async def pending_list_cb(cb: CallbackQuery, state: FSMContext, db: DB, user, bot: Bot):
    await state.clear()
    if not is_admin(user):
        return await cb.answer("Нет доступа", show_alert=True)
    await cb.answer()
    await pending_view(cb, db, user, bot)


# ---------- оплаты клиента ----------

@router.callback_query(F.data.startswith("pay:cl:"))
async def client_payments(cb: CallbackQuery, db: DB, user):
    c = await get_client_for(db, user, int(cb.data.split(":")[2]))
    if c is None:
        return await cb.answer("Нет доступа", show_alert=True)
    rows = await db.all("SELECT * FROM payments WHERE client_id=? ORDER BY id DESC LIMIT 30", c["id"])
    await cb.answer()
    nav = [back_btn(f"cl:v:{c['id']}", "« К клиенту"), home_btn()]
    if not rows:
        await show(cb, f"💰 <b>{esc(c['name'])}</b>\n\nОплат пока нет.",
                   kb([main_btn("🧾 Добавить квитанцию", f"pay:new:{c['id']}")], nav))
        return
    paid = sum(r["amount"] for r in rows if r["status"] == "confirmed")
    buttons = [[btn(f"{PAYMENT_STATUSES[p['status']][:1]} {fmt_money(p['amount'])} · {fmt_short(p['submitted_at'])}",
                    f"pay:v:{p['id']}")] for p in rows]
    await show(cb, f"💰 <b>{esc(c['name'])}</b> · оплачено {fmt_money(paid)}\n\nНажмите, чтобы открыть квитанцию:",
               kb(*buttons, [main_btn("🧾 Добавить квитанцию", f"pay:new:{c['id']}")], nav))


@router.callback_query(F.data.startswith("pay:v:"))
async def payment_view(cb: CallbackQuery, db: DB, user, bot: Bot):
    p = await db.one("SELECT * FROM payments WHERE id=?", int(cb.data.split(":")[2]))
    if p is None or not await can_view(db, user, p):
        return await cb.answer("Не найдено", show_alert=True)
    await cb.answer()
    await extra_file(bot, cb.from_user.id, p["file_id"], p["file_type"],
                     await payment_caption(db, p, user), payment_kb(p, is_admin(user)), replace=True)


@router.callback_query(F.data.startswith("pay:del:"))
async def payment_delete_ask(cb: CallbackQuery, db: DB, user):
    if not is_admin(user):
        return await cb.answer("Нет доступа", show_alert=True)
    pid = int(cb.data.split(":")[2])
    p = await db.one("SELECT * FROM payments WHERE id=?", pid)
    if p is None:
        return await cb.answer("Уже удалена", show_alert=True)
    await cb.answer()
    warn = "\nОна пропадёт из отчётов, заработок сотрудника уменьшится." if p["status"] == "confirmed" else ""
    await refresh_card(cb, f"🗑 Удалить квитанцию {fmt_money(p['amount'])} · {esc(p['client_name'])}?{warn}",
                       confirm_kb(f"pay:delok:{pid}", f"pay:back:{pid}"))


@router.callback_query(F.data.startswith("pay:back:"))
async def payment_delete_cancel(cb: CallbackQuery, db: DB, user):
    p = await db.one("SELECT * FROM payments WHERE id=?", int(cb.data.split(":")[2]))
    await cb.answer()
    if p:
        await refresh_card(cb, await payment_caption(db, p, user), payment_kb(p, is_admin(user)))


@router.callback_query(F.data.startswith("pay:delok:"))
async def payment_delete(cb: CallbackQuery, db: DB, user, bot: Bot):
    if not is_admin(user):
        return await cb.answer("Нет доступа", show_alert=True)
    pid = int(cb.data.split(":")[2])
    p = await db.one("SELECT * FROM payments WHERE id=?", pid)
    if p is None or not await delete_payment(db, pid, p["client_id"]):
        return await cb.answer("Уже удалена", show_alert=True)
    await db.audit(user["id"], f"Удалил квитанцию #{pid} ({fmt_money(p['amount'])}, {p['status']})")
    await cb.answer("🗑 Удалено")
    try:
        await cb.message.delete()
    except Exception:
        pass
    if p["status"] == "confirmed" and p["worker_id"] and p["worker_id"] != user["id"]:
        await notify_user(bot, db, p["worker_id"],
                          f"⚠️ Удалена квитанция: {esc(p['client_name'])} · {fmt_money(p['amount'])}\n"
                          f"Ваш заработок уменьшился на {fmt_money(p['worker_share'])}")
    await notify_admins(bot, db, f"🗑 {user_name(user)} удалил квитанцию {esc(p['client_name'])} · "
                                 f"{fmt_money(p['amount'])}", exclude_user_id=user["id"])
