from aiogram import Bot, F, Router
from aiogram.exceptions import TelegramBadRequest
from aiogram.fsm.context import FSMContext
from aiogram.fsm.state import State, StatesGroup
from aiogram.types import CallbackQuery, Message

from ..db import DB
from ..keyboards import BTN_RECEIPTS, btn, cancel_kb, kb
from ..notify import admin_chat_ids, notify_admins, notify_user, send_file_safe
from ..utils import PAYMENT_STATUSES, esc, fmt_dt, fmt_money, is_admin, now, parse_money, user_name
from .clients import get_client_for
from .common import show
from .requisites import req_short

router = Router(name="payments")


class Receipt(StatesGroup):
    file = State()
    amount = State()
    requisite = State()


async def payment_caption(db: DB, p) -> str:
    client = await db.one("SELECT * FROM clients WHERE id=?", p["client_id"]) if p["client_id"] else None
    req = await db.one("SELECT * FROM requisites WHERE id=?", p["requisite_id"]) if p["requisite_id"] else None
    worker = await db.get_user(p["worker_id"])
    submitter = await db.get_user(p["submitted_by"])
    if client:
        client_line = f"#{client['id']} {esc(client['name'])} · <code>{esc(client['phone'] or '')}</code>"
    else:
        client_line = f"{esc(p['client_name'] or '—')} (удалён)"
    lines = [
        f"🧾 <b>Квитанция #{p['id']}</b> — {PAYMENT_STATUSES[p['status']]}",
        f"Клиент: {client_line}",
        f"Сумма: <b>{fmt_money(p['amount'])}</b>",
        f"Реквизит: {req_short(req)}",
        f"Сотрудник: {user_name(worker)}",
        f"Загрузил: {user_name(submitter)}, {fmt_dt(p['submitted_at'])}",
    ]
    if p["status"] != "pending":
        reviewer = await db.get_user(p["reviewed_by"])
        lines.append(f"Проверил: {user_name(reviewer)}, {fmt_dt(p['reviewed_at'])}")
    if p["status"] == "confirmed" and p["worker_percent"] is not None:
        share = p["amount"] * p["worker_percent"] / 100
        lines.append(f"Заработок сотрудника: {fmt_money(share)} ({p['worker_percent']:g}%)")
    return "\n".join(lines)


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


# --- загрузка квитанции ---

@router.callback_query(F.data.startswith("pay:new:"))
async def receipt_start(cb: CallbackQuery, state: FSMContext, db: DB, user):
    c = await get_client_for(db, user, int(cb.data.split(":")[2]))
    if c is None:
        return await cb.answer("Нет доступа", show_alert=True)
    await state.set_state(Receipt.file)
    await state.update_data(cid=c["id"])
    await cb.answer()
    await cb.message.answer(
        f"🧾 Клиент #{c['id']} {esc(c['name'])}\n\nОтправьте <b>скриншот квитанции</b> (фото или файл):",
        reply_markup=cancel_kb())


@router.message(Receipt.file, F.photo | F.document)
async def receipt_file(message: Message, state: FSMContext):
    if message.photo:
        file_id, file_type = message.photo[-1].file_id, "photo"
    else:
        mime = message.document.mime_type or ""
        if not (mime.startswith("image/") or mime == "application/pdf"):
            await message.answer("Нужна картинка или PDF. Отправьте ещё раз:", reply_markup=cancel_kb())
            return
        file_id, file_type = message.document.file_id, "document"
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
        await message.answer("Не понял сумму. Введите число, например 3500:", reply_markup=cancel_kb())
        return
    await state.update_data(amount=amount)
    data = await state.get_data()
    c = await get_client_for(db, user, data["cid"])
    if c is None:
        await state.clear()
        await message.answer("Клиент не найден.")
        return
    if c["requisite_id"]:
        await finalize(message, state, db, user, bot, c["requisite_id"])
        return
    reqs = await db.all("SELECT * FROM requisites WHERE is_active=1 ORDER BY id DESC")
    if not reqs:
        await finalize(message, state, db, user, bot, None)
        return
    await state.set_state(Receipt.requisite)
    rows = [[btn(f"#{r['id']} {r['iban'][-8:]} · {r['holder'][:22]}", f"pay:rq:{r['id']}")] for r in reqs]
    rows.append([btn("✖️ Отмена", "cancel")])
    await message.answer("На какой реквизит пришла оплата?", reply_markup=kb(*rows))


@router.callback_query(Receipt.requisite, F.data.startswith("pay:rq:"))
async def receipt_requisite(cb: CallbackQuery, state: FSMContext, db: DB, user, bot: Bot):
    await cb.answer()
    await finalize(cb.message, state, db, user, bot, int(cb.data.split(":")[2]))


async def finalize(message: Message, state: FSMContext, db: DB, user, bot: Bot, requisite_id):
    data = await state.get_data()
    await state.clear()
    c = await get_client_for(db, user, data.get("cid", 0))
    if c is None or "file_id" not in data:
        await message.answer("Данные устарели, начните заново.")
        return
    cur = await db.run(
        "INSERT INTO payments(client_id, client_name, requisite_id, worker_id, amount, file_id, file_type, "
        "status, submitted_by, submitted_at) VALUES (?, ?, ?, ?, ?, ?, ?, 'pending', ?, ?)",
        c["id"], c["name"], requisite_id, c["worker_id"], data["amount"], data["file_id"],
        data["file_type"], user["id"], now(),
    )
    pid = cur.lastrowid
    if requisite_id and not c["requisite_id"]:
        await db.run("UPDATE clients SET requisite_id=? WHERE id=?", requisite_id, c["id"])
    await db.audit(user["id"], f"Квитанция #{pid}: клиент #{c['id']}, {fmt_money(data['amount'])}")
    p = await db.one("SELECT * FROM payments WHERE id=?", pid)
    caption = await payment_caption(db, p)
    for chat_id in await admin_chat_ids(db):
        await send_file_safe(bot, chat_id, p["file_id"], p["file_type"], caption, payment_kb(p, True))
    if not is_admin(user):
        await message.answer(f"✅ Квитанция #{pid} на {fmt_money(data['amount'])} отправлена админам на проверку.",
                             reply_markup=kb([btn("« К клиенту", f"cl:v:{c['id']}")]))


# --- проверка админом ---

async def update_card_message(cb: CallbackQuery, caption: str, markup):
    try:
        if cb.message and (cb.message.photo or cb.message.document):
            await cb.message.edit_caption(caption=caption, reply_markup=markup)
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
    else:
        cur = await db.run(
            "UPDATE payments SET status='rejected', reviewed_by=?, reviewed_at=? "
            "WHERE id=? AND status='pending'", user["id"], now(), pid)
    p = await db.one("SELECT * FROM payments WHERE id=?", pid)
    if p is None:
        return await cb.answer("Квитанция удалена", show_alert=True)
    if cur.rowcount == 0:
        await cb.answer("Квитанция уже обработана", show_alert=True)
        await update_card_message(cb, await payment_caption(db, p), payment_kb(p, True))
        return

    if action == "ok":
        if p["client_id"]:
            await db.run("UPDATE clients SET status='paid' WHERE id=?", p["client_id"])
        await db.audit(user["id"], f"Подтвердил квитанцию #{pid} ({fmt_money(p['amount'])})")
        share = p["amount"] * (p["worker_percent"] or 0) / 100
        worker_text = (f"✅ Оплата подтверждена!\nКлиент: {esc(p['client_name'])}\n"
                       f"Сумма: {fmt_money(p['amount'])}\nВаш заработок: <b>{fmt_money(share)}</b>")
        other_text = f"✅ {user_name(user)} подтвердил квитанцию #{pid} на {fmt_money(p['amount'])}."
        await cb.answer("Оплата подтверждена")
    else:
        await db.audit(user["id"], f"Отклонил квитанцию #{pid} ({fmt_money(p['amount'])})")
        worker_text = (f"❌ Квитанция #{pid} отклонена админом.\nКлиент: {esc(p['client_name'])}\n"
                       f"Сумма: {fmt_money(p['amount'])}")
        other_text = f"❌ {user_name(user)} отклонил квитанцию #{pid} на {fmt_money(p['amount'])}."
        await cb.answer("Квитанция отклонена")

    await update_card_message(cb, await payment_caption(db, p), payment_kb(p, True))
    open_kb = kb([btn("Открыть клиента", f"cl:v:{p['client_id']}")]) if p["client_id"] else None
    notified = {user["id"]}
    for uid in (p["worker_id"], p["submitted_by"]):
        if uid and uid not in notified:
            target = await db.get_user(uid)
            if target and not is_admin(target):
                await notify_user(bot, db, uid, worker_text, open_kb)
            notified.add(uid)
    await notify_admins(bot, db, other_text, exclude_user_id=user["id"])


@router.message(F.text == BTN_RECEIPTS)
async def pending_list(message: Message, state: FSMContext, db: DB, user, bot: Bot):
    await state.clear()
    if not is_admin(user):
        return
    rows = await db.all("SELECT * FROM payments WHERE status='pending' ORDER BY id")
    if not rows:
        await message.answer("🧾 Нет квитанций, ожидающих подтверждения.")
        return
    total = sum(r["amount"] for r in rows)
    await message.answer(f"🧾 Ожидают подтверждения: <b>{len(rows)}</b> на {fmt_money(total)}")
    for p in rows[:10]:
        await send_file_safe(bot, message.chat.id, p["file_id"], p["file_type"],
                             await payment_caption(db, p), payment_kb(p, True))
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
    lines = [f"💰 <b>Оплаты — клиент #{c['id']} {esc(c['name'])}</b>\n"]
    buttons = []
    for p in rows:
        icon = PAYMENT_STATUSES[p["status"]].split(" ")[0]
        lines.append(f"{icon} #{p['id']} · {fmt_money(p['amount'])} · {fmt_dt(p['submitted_at'])}")
        buttons.append([btn(f"{icon} #{p['id']} {fmt_money(p['amount'])}", f"pay:v:{p['id']}")])
    buttons.append([btn("« К клиенту", f"cl:v:{c['id']}")])
    await show(cb, "\n".join(lines), kb(*buttons))


@router.callback_query(F.data.startswith("pay:v:"))
async def payment_view(cb: CallbackQuery, db: DB, user, bot: Bot):
    p = await db.one("SELECT * FROM payments WHERE id=?", int(cb.data.split(":")[2]))
    if p is None or not await can_view(db, user, p):
        return await cb.answer("Не найдено", show_alert=True)
    await cb.answer()
    await send_file_safe(bot, cb.from_user.id, p["file_id"], p["file_type"],
                         await payment_caption(db, p), payment_kb(p, is_admin(user)))


@router.callback_query(F.data.startswith("pay:del:"))
async def payment_delete_ask(cb: CallbackQuery, user):
    if not is_admin(user):
        return await cb.answer("Нет доступа", show_alert=True)
    pid = int(cb.data.split(":")[2])
    await cb.answer()
    await cb.message.answer(f"🗑 Удалить квитанцию #{pid}? Она пропадёт из отчётов.",
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
    await db.run("DELETE FROM payments WHERE id=?", pid)
    await db.audit(user["id"], f"Удалил квитанцию #{pid} ({fmt_money(p['amount'])})")
    await notify_admins(bot, db, f"🗑 {user_name(user)} удалил квитанцию #{pid} на {fmt_money(p['amount'])}.",
                        exclude_user_id=user["id"])
    await cb.answer("Удалено")
    await show(cb, f"🗑 Квитанция #{pid} удалена.")
