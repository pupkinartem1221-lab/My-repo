import asyncio

from aiogram import Bot, F, Router
from aiogram.exceptions import TelegramBadRequest
from aiogram.fsm.context import FSMContext
from aiogram.fsm.state import State, StatesGroup
from aiogram.types import CallbackQuery, Message

from ..db import DB
from ..keyboards import BTN_RECEIPTS, btn, cancel_kb, kb, main_kb
from ..notify import notify_admins, notify_user, send_file_safe
from ..utils import (PAYMENT_STATUSES, clip, esc, fit, fmt_dt, fmt_money, is_admin, now, parse_money,
                     user_name)
from .clients import get_client_for
from .common import show
from .requisites import req_short

router = Router(name="payments")

ALLOWED_MIME = {"image/jpeg", "image/png", "image/webp", "image/heic", "image/heif", "application/pdf"}
MAX_FILE = 20 * 1024 * 1024
SHARE_SQL = "CAST(amount * COALESCE(worker_percent, 0) / 100.0 + 0.5 AS INTEGER)"


class Receipt(StatesGroup):
    file = State()
    amount = State()
    requisite = State()


async def payment_caption(db: DB, p, viewer) -> str:
    admin = is_admin(viewer)
    client = await db.one("SELECT * FROM clients WHERE id=?", p["client_id"]) if p["client_id"] else None
    req = await db.one("SELECT * FROM requisites WHERE id=?", p["requisite_id"]) if p["requisite_id"] else None
    worker = await db.get_user(p["worker_id"])
    submitter = await db.get_user(p["submitted_by"])
    if client:
        client_line = f"#{client['id']} {esc(clip(client['name'], 60))} · <code>{esc(client['phone'] or '')}</code>"
    else:
        client_line = f"{esc(clip(p['client_name'] or '—', 60))} (удалён)"
    if req and (admin or req["is_active"]):
        req_line = req_short(req)
    elif p["requisite_label"] and admin:
        req_line = f"{esc(p['requisite_label'])} (удалён)"
    else:
        req_line = "—"
    lines = [
        f"🧾 <b>Квитанция #{p['id']}</b> — {PAYMENT_STATUSES[p['status']]}",
        f"Клиент: {client_line}",
        f"Сумма: <b>{fmt_money(p['amount'])}</b>",
        f"Реквизит: {req_line}",
        f"Сотрудник: {user_name(worker)}",
        f"Загрузил: {user_name(submitter)}, {fmt_dt(p['submitted_at'])}",
    ]
    if p["status"] != "pending":
        reviewer = await db.get_user(p["reviewed_by"])
        lines.append(f"Проверил: {user_name(reviewer)}, {fmt_dt(p['reviewed_at'])}")
    # заработок и процент видят только админы и сам сотрудник этой оплаты
    if (p["status"] == "confirmed" and p["worker_share"] is not None
            and (admin or p["worker_id"] == viewer["id"])):
        lines.append(f"Заработок сотрудника: {fmt_money(p['worker_share'])} ({(p['worker_percent'] or 0):g}%)")
    return fit(lines, 1000)


def payment_kb(p, admin: bool):
    if not admin:
        return None
    if p["status"] == "pending":
        return kb([btn("✅ Подтвердить", f"pay:ok:{p['id']}"), btn("❌ Отклонить", f"pay:no:{p['id']}")])
    return kb([btn("🗑 Удалить", f"pay:del:{p['id']}")])


async def can_view(db: DB, user, p) -> bool:
    if is_admin(user) or p["submitted_by"] == user["id"] or p["worker_id"] == user["id"]:
        return True
    if p["client_id"]:
        return await get_client_for(db, user, p["client_id"]) is not None
    return False


async def send_to_admins(bot: Bot, db: DB, p) -> None:
    for admin in await db.all("SELECT * FROM users WHERE role IN ('owner','admin') AND tg_id IS NOT NULL "
                              "AND approved=1"):
        await send_file_safe(bot, admin["tg_id"], p["file_id"], p["file_type"],
                             await payment_caption(db, p, admin), payment_kb(p, True))
        await asyncio.sleep(0.05)


# --- загрузка квитанции ---

@router.callback_query(F.data.startswith("pay:new:"))
async def receipt_start(cb: CallbackQuery, state: FSMContext, db: DB, user):
    c = await get_client_for(db, user, int(cb.data.split(":")[2]))
    if c is None:
        return await cb.answer("Нет доступа", show_alert=True)
    await state.set_state(Receipt.file)
    await state.set_data({"cid": c["id"]})
    await cb.answer()
    await cb.message.answer(
        f"🧾 Клиент #{c['id']} {esc(c['name'])}\n\nОтправьте <b>скриншот квитанции</b> (фото или файл):",
        reply_markup=cancel_kb())


@router.message(Receipt.file, F.photo | F.document)
async def receipt_file(message: Message, state: FSMContext):
    if message.photo:
        file_id, file_type = message.photo[-1].file_id, "photo"
    else:
        doc = message.document
        name = (doc.file_name or "").lower()
        ok_ext = name.endswith((".jpg", ".jpeg", ".png", ".webp", ".heic", ".heif", ".pdf"))
        if (doc.mime_type or "") not in ALLOWED_MIME or not ok_ext or (doc.file_size or 0) > MAX_FILE:
            await message.answer("Нужна картинка (JPG, PNG, WEBP, HEIC) или PDF до 20 МБ. Отправьте ещё раз:",
                                 reply_markup=cancel_kb())
            return
        file_id, file_type = doc.file_id, "document"
    await state.update_data(file_id=file_id, file_type=file_type)
    await state.set_state(Receipt.amount)
    await message.answer("Введите <b>сумму оплаты</b> в гривнах (например 3500):", reply_markup=cancel_kb())


@router.message(Receipt.file)
async def receipt_file_wrong(message: Message):
    await message.answer("Отправьте скриншот квитанции фотографией или файлом:", reply_markup=cancel_kb())


@router.message(Receipt.amount, F.text)
async def receipt_amount(message: Message, state: FSMContext, db: DB, user, bot: Bot):
    amount = parse_money(message.text)
    if amount is None:
        await message.answer("Не понял сумму. Введите число, например 3500 или 3500,50:", reply_markup=cancel_kb())
        return
    await state.update_data(amount=amount)
    data = await state.get_data()
    c = await get_client_for(db, user, data.get("cid") or 0)
    if c is None or "file_id" not in data:
        await state.clear()
        await message.answer("Данные устарели, начните заново.")
        return
    if c["requisite_id"]:
        r = await db.one("SELECT id FROM requisites WHERE id=?", c["requisite_id"])
        if r:
            await finalize(message, state, db, user, bot, r["id"])
            return
    reqs = await db.all("SELECT * FROM requisites WHERE is_active=1 ORDER BY id DESC LIMIT 50")
    if not reqs:
        await finalize(message, state, db, user, bot, None)
        return
    await state.set_state(Receipt.requisite)
    rows = [[btn(clip(f"#{r['id']} {r['iban'][-8:]} · {r['holder']}", 60), f"pay:rq:{r['id']}")] for r in reqs]
    rows.append([btn("✖️ Отмена", "cancel")])
    await message.answer("На какой реквизит пришла оплата?", reply_markup=kb(*rows))


@router.message(Receipt.amount)
async def receipt_amount_wrong(message: Message):
    await message.answer("Введите сумму числом, например 3500:", reply_markup=cancel_kb())


@router.callback_query(Receipt.requisite, F.data.startswith("pay:rq:"))
async def receipt_requisite(cb: CallbackQuery, state: FSMContext, db: DB, user, bot: Bot):
    r = await db.one("SELECT id FROM requisites WHERE id=? AND is_active=1", int(cb.data.split(":")[2]))
    if r is None:
        return await cb.answer("Реквизит не рабочий или удалён — выберите другой", show_alert=True)
    await cb.answer()
    try:
        await cb.message.edit_reply_markup(reply_markup=None)
    except TelegramBadRequest:
        pass
    await finalize(cb.message, state, db, user, bot, r["id"])


async def finalize(message: Message, state: FSMContext, db: DB, user, bot: Bot, requisite_id):
    data = await state.get_data()
    if "file_id" not in data or "amount" not in data:
        return  # уже оформлено параллельным нажатием
    await state.clear()
    c = await get_client_for(db, user, data.get("cid") or 0)
    if c is None:
        await message.answer("Клиент не найден.")
        return
    req = await db.one("SELECT * FROM requisites WHERE id=?", requisite_id) if requisite_id else None
    label = f"{req['iban']} ({req['holder']})" if req else None
    cur = await db.run(
        "INSERT INTO payments(client_id, client_name, requisite_id, requisite_label, worker_id, amount, "
        "file_id, file_type, status, submitted_by, submitted_at) VALUES (?, ?, ?, ?, ?, ?, ?, ?, 'pending', ?, ?)",
        c["id"], c["name"], req["id"] if req else None, label, c["worker_id"], data["amount"],
        data["file_id"], data["file_type"], user["id"], now(),
    )
    pid = cur.lastrowid
    if req and not c["requisite_id"] and req["is_active"]:
        await db.run("UPDATE clients SET requisite_id=? WHERE id=?", req["id"], c["id"])
    await db.audit(user["id"], f"Квитанция #{pid}: клиент #{c['id']}, {fmt_money(data['amount'])}")
    tail = "создана и ждёт подтверждения." if is_admin(user) else "отправлена админам на проверку."
    await message.answer(f"✅ Квитанция #{pid} на {fmt_money(data['amount'])} {tail}",
                         reply_markup=kb([btn("« К клиенту", f"cl:v:{c['id']}")]))
    p = await db.one("SELECT * FROM payments WHERE id=?", pid)
    await send_to_admins(bot, db, p)


# --- проверка админом ---

async def update_card_message(cb: CallbackQuery, caption: str, markup):
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
    if action == "ok":
        cur = await db.run(
            "UPDATE payments SET status='confirmed', reviewed_by=?, reviewed_at=?, "
            "worker_percent=(SELECT percent FROM users WHERE users.id=payments.worker_id) "
            "WHERE id=? AND status='pending'", user["id"], now(), pid)
        if cur.rowcount:
            await db.run(f"UPDATE payments SET worker_share={SHARE_SQL} WHERE id=?", pid)
    else:
        cur = await db.run(
            "UPDATE payments SET status='rejected', reviewed_by=?, reviewed_at=? "
            "WHERE id=? AND status='pending'", user["id"], now(), pid)
    p = await db.one("SELECT * FROM payments WHERE id=?", pid)
    if p is None:
        return await cb.answer("Квитанция удалена", show_alert=True)
    if cur.rowcount == 0:
        await cb.answer("Квитанция уже обработана", show_alert=True)
        await update_card_message(cb, await payment_caption(db, p, user), payment_kb(p, True))
        return

    if action == "ok":
        if p["client_id"]:
            await db.run("UPDATE clients SET status='paid' WHERE id=?", p["client_id"])
        await db.audit(user["id"], f"Подтвердил квитанцию #{pid} ({fmt_money(p['amount'])})")
        worker_text = (f"✅ Оплата подтверждена!\nКлиент: {esc(p['client_name'])}\n"
                       f"Сумма: {fmt_money(p['amount'])}\nВаш заработок: <b>{fmt_money(p['worker_share'])}</b>")
        submitter_text = (f"✅ Квитанция #{pid} подтверждена.\nКлиент: {esc(p['client_name'])}\n"
                          f"Сумма: {fmt_money(p['amount'])}")
        other_text = f"✅ {user_name(user)} подтвердил квитанцию #{pid} на {fmt_money(p['amount'])}."
        await cb.answer("Оплата подтверждена")
    else:
        await db.audit(user["id"], f"Отклонил квитанцию #{pid} ({fmt_money(p['amount'])})")
        worker_text = submitter_text = (f"❌ Квитанция #{pid} отклонена админом.\nКлиент: {esc(p['client_name'])}\n"
                                        f"Сумма: {fmt_money(p['amount'])}")
        other_text = f"❌ {user_name(user)} отклонил квитанцию #{pid} на {fmt_money(p['amount'])}."
        await cb.answer("Квитанция отклонена")

    await update_card_message(cb, await payment_caption(db, p, user), payment_kb(p, True))
    open_kb = kb([btn("Открыть клиента", f"cl:v:{p['client_id']}")]) if p["client_id"] else None
    notified = {user["id"]}
    for uid, text in ((p["worker_id"], worker_text), (p["submitted_by"], submitter_text)):
        if uid and uid not in notified:
            target = await db.get_user(uid)
            if target and not is_admin(target):
                await notify_user(bot, db, uid, text, open_kb)
            notified.add(uid)
    await notify_admins(bot, db, other_text, exclude_user_id=user["id"])


@router.message(F.text == BTN_RECEIPTS)
async def pending_list(message: Message, state: FSMContext, db: DB, user, bot: Bot):
    await state.clear()
    if not is_admin(user):
        await message.answer("Нет доступа.", reply_markup=main_kb(user))
        return
    rows = await db.all("SELECT * FROM payments WHERE status='pending' ORDER BY id")
    if not rows:
        await message.answer("🧾 Нет квитанций, ожидающих подтверждения.")
        return
    total = sum(r["amount"] for r in rows)
    await message.answer(f"🧾 Ожидают подтверждения: <b>{len(rows)}</b> на {fmt_money(total)}")
    for p in rows[:10]:
        await send_file_safe(bot, message.chat.id, p["file_id"], p["file_type"],
                             await payment_caption(db, p, user), payment_kb(p, True))
        await asyncio.sleep(0.4)
    if len(rows) > 10:
        await message.answer(f"…и ещё {len(rows) - 10}. Обработайте эти и нажмите «{BTN_RECEIPTS}» снова.")


# --- просмотр оплат клиента ---

@router.callback_query(F.data.startswith("pay:cl:"))
async def client_payments(cb: CallbackQuery, db: DB, user):
    c = await get_client_for(db, user, int(cb.data.split(":")[2]))
    if c is None:
        return await cb.answer("Нет доступа", show_alert=True)
    rows = await db.all("SELECT * FROM payments WHERE client_id=? ORDER BY id DESC LIMIT 30", c["id"])
    await cb.answer()
    if not rows:
        await show(cb, f"💰 У клиента #{c['id']} пока нет оплат.",
                   kb([btn("🧾 Добавить квитанцию", f"pay:new:{c['id']}")],
                      [btn("« К клиенту", f"cl:v:{c['id']}")]))
        return
    lines = [f"💰 <b>Оплаты — клиент #{c['id']} {esc(clip(c['name'], 60))}</b>\n"]
    buttons = []
    for p in rows:
        icon = PAYMENT_STATUSES[p["status"]].split(" ")[0]
        lines.append(f"{icon} #{p['id']} · {fmt_money(p['amount'])} · {fmt_dt(p['submitted_at'])}")
        buttons.append([btn(f"{icon} #{p['id']} {fmt_money(p['amount'])}", f"pay:v:{p['id']}")])
    buttons.append([btn("« К клиенту", f"cl:v:{c['id']}")])
    await show(cb, fit(lines), kb(*buttons))


@router.callback_query(F.data.startswith("pay:v:"))
async def payment_view(cb: CallbackQuery, db: DB, user, bot: Bot):
    p = await db.one("SELECT * FROM payments WHERE id=?", int(cb.data.split(":")[2]))
    if p is None or not await can_view(db, user, p):
        return await cb.answer("Не найдено", show_alert=True)
    await cb.answer()
    await send_file_safe(bot, cb.from_user.id, p["file_id"], p["file_type"],
                         await payment_caption(db, p, user), payment_kb(p, is_admin(user)))


@router.callback_query(F.data.startswith("pay:del:"))
async def payment_delete_ask(cb: CallbackQuery, user):
    if not is_admin(user):
        return await cb.answer("Нет доступа", show_alert=True)
    pid = int(cb.data.split(":")[2])
    await cb.answer()
    await cb.message.answer(f"🗑 Удалить квитанцию #{pid}? Если она подтверждена, она пропадёт из отчётов "
                            "и заработок сотрудника уменьшится.",
                            reply_markup=kb([btn("✅ Да, удалить", f"pay:delok:{pid}"),
                                             btn("« Нет", "cancel")]))


@router.callback_query(F.data.startswith("pay:delok:"))
async def payment_delete(cb: CallbackQuery, db: DB, user, bot: Bot):
    if not is_admin(user):
        return await cb.answer("Нет доступа", show_alert=True)
    pid = int(cb.data.split(":")[2])
    p = await db.one("SELECT * FROM payments WHERE id=?", pid)
    if p is None:
        return await cb.answer("Уже удалена", show_alert=True)
    cur = await db.run("DELETE FROM payments WHERE id=?", pid)
    if cur.rowcount == 0:
        return await cb.answer("Уже удалена", show_alert=True)
    if p["status"] == "confirmed" and p["client_id"]:
        # если подтверждённых оплат не осталось — клиент снова «в работе»
        await db.run("UPDATE clients SET status='work' WHERE id=? AND status='paid' AND NOT EXISTS "
                     "(SELECT 1 FROM payments WHERE client_id=? AND status='confirmed')",
                     p["client_id"], p["client_id"])
    await db.audit(user["id"], f"Удалил квитанцию #{pid} ({fmt_money(p['amount'])}, {p['status']})")
    await cb.answer("Удалено")
    await show(cb, f"🗑 Квитанция #{pid} удалена.")
    if p["status"] == "confirmed" and p["worker_id"] and p["worker_id"] != user["id"]:
        await notify_user(bot, db, p["worker_id"],
                          f"⚠️ Подтверждённая оплата #{pid} на {fmt_money(p['amount'])} удалена админом. "
                          f"Ваш заработок уменьшен на {fmt_money(p['worker_share'])}.")
    await notify_admins(bot, db, f"🗑 {user_name(user)} удалил квитанцию #{pid} на {fmt_money(p['amount'])}.",
                        exclude_user_id=user["id"])
