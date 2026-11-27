import re

from aiogram import Bot, F, Router
from aiogram.fsm.context import FSMContext
from aiogram.fsm.state import State, StatesGroup
from aiogram.types import CallbackQuery, Message

from ..db import DB
from ..keyboards import BTN_REQS, btn, cancel_kb, kb
from ..notify import notify_admins, notify_all
from ..utils import clip, day_range, esc, fmt_dt, fmt_money, iban_ok, ipn_checksum_ok, is_admin, now, today, user_name
from .common import show

router = Router(name="requisites")
PAGE = 10


class NewReq(StatesGroup):
    iban = State()
    holder = State()
    ipn = State()
    comment = State()


class EditReqComment(StatesGroup):
    text = State()


def req_icon(r) -> str:
    return "🟢" if r["is_active"] else "🔴"


def req_short(r) -> str:
    if r is None:
        return "—"
    return f"{req_icon(r)} #{r['id']} {esc(r['iban'])} ({esc(r['holder'])})"


def req_for_client(r) -> str:
    """Текст, который удобно скопировать и отправить клиенту."""
    return (
        "💳 <b>Реквизиты для оплаты</b>\n\n"
        f"IBAN: <code>{esc(r['iban'])}</code>\n"
        f"Получатель: <code>{esc(r['holder'])}</code>\n"
        f"ІПН: <code>{esc(r['ipn'])}</code>"
    )


async def list_view(db: DB, user, page: int = 0):
    admin = is_admin(user)
    where = "" if admin else "WHERE is_active=1 "
    total = (await db.one("SELECT COUNT(*) n FROM requisites " + where))["n"]
    active = (await db.one("SELECT COUNT(*) n FROM requisites WHERE is_active=1"))["n"]
    pages = max(1, (total + PAGE - 1) // PAGE)
    page = min(max(page, 0), pages - 1)
    rows = await db.all("SELECT * FROM requisites " + where + "ORDER BY is_active DESC, id DESC LIMIT ? OFFSET ?",
                        PAGE, page * PAGE)
    if total:
        text = f"💳 <b>Реквизиты</b>\nРабочих: {active}" + (f", нерабочих: {total - active}" if admin else "")
        if pages > 1:
            text += f" · стр. {page + 1}/{pages}"
    else:
        text = "💳 <b>Реквизиты</b>\n\nРеквизитов пока нет."
    buttons = [[btn(clip(f"{req_icon(r)} #{r['id']} {r['iban'][-8:]} · {r['holder']}", 60), f"rq:v:{r['id']}")]
               for r in rows]
    nav = []
    if page > 0:
        nav.append(btn("◀️", f"rq:list:{page - 1}"))
    if page < pages - 1:
        nav.append(btn("▶️", f"rq:list:{page + 1}"))
    buttons.append(nav)
    if admin:
        buttons.append([btn("➕ Добавить реквизит", "rq:add")])
    return text, kb(*buttons)


@router.message(F.text == BTN_REQS)
async def reqs_menu(message: Message, state: FSMContext, db: DB, user):
    await state.clear()
    text, markup = await list_view(db, user)
    await message.answer(text, reply_markup=markup)


@router.callback_query(F.data.startswith("rq:list"))
async def reqs_list_cb(cb: CallbackQuery, db: DB, user):
    parts = cb.data.split(":")
    text, markup = await list_view(db, user, int(parts[2]) if len(parts) > 2 else 0)
    await cb.answer()
    await show(cb, text, markup)


async def card_view(db: DB, user, rid: int):
    r = await db.one("SELECT * FROM requisites WHERE id=?", rid)
    if r is None or (not is_admin(user) and not r["is_active"]):
        return None, None
    text = (
        f"💳 <b>Реквизит #{r['id']}</b> — {'🟢 рабочий' if r['is_active'] else '🔴 не рабочий'}\n\n"
        f"IBAN: <code>{esc(r['iban'])}</code>\n"
        f"Получатель: <code>{esc(r['holder'])}</code>\n"
        f"ІПН: <code>{esc(r['ipn'])}</code>\n"
    )
    if r["comment"]:
        text += f"Комментарий: {esc(r['comment'])}\n"
    if is_admin(user):
        s, e = day_range(today())
        total = await db.one(
            "SELECT COUNT(*) n, COALESCE(SUM(amount),0) s FROM payments "
            "WHERE requisite_id=? AND status='confirmed'", rid)
        day = await db.one(
            "SELECT COALESCE(SUM(amount),0) s FROM payments "
            "WHERE requisite_id=? AND status='confirmed' AND reviewed_at>=? AND reviewed_at<?",
            rid, s, e)
        clients = await db.one("SELECT COUNT(*) n FROM clients WHERE requisite_id=?", rid)
        author = await db.get_user(r["created_by"])
        text += (
            f"\nКлиентов привязано: {clients['n']}\n"
            f"Поступило сегодня: {fmt_money(day['s'])}\n"
            f"Поступило всего: {fmt_money(total['s'])} ({total['n']} опл.)\n"
            f"\nДобавил: {user_name(author)}, {fmt_dt(r['created_at'])}"
        )
        markup = kb(
            [btn("🔴 Сделать нерабочим" if r["is_active"] else "🟢 Сделать рабочим", f"rq:t:{rid}")],
            [btn("✏️ Комментарий", f"rq:c:{rid}"), btn("🗑 Удалить", f"rq:del:{rid}")],
            [btn("« К списку", "rq:list:0")],
        )
    else:
        markup = kb([btn("« К списку", "rq:list:0")])
    return text, markup


@router.callback_query(F.data.startswith("rq:v:"))
async def req_card(cb: CallbackQuery, db: DB, user):
    text, markup = await card_view(db, user, int(cb.data.split(":")[2]))
    if text is None:
        await cb.answer("Реквизит не найден", show_alert=True)
        return
    await cb.answer()
    await show(cb, text, markup)


@router.callback_query(F.data.startswith("rq:t:"))
async def req_toggle(cb: CallbackQuery, db: DB, user, bot: Bot):
    if not is_admin(user):
        return await cb.answer("Нет доступа", show_alert=True)
    rid = int(cb.data.split(":")[2])
    r = await db.one("SELECT * FROM requisites WHERE id=?", rid)
    if r is None:
        return await cb.answer("Реквизит не найден", show_alert=True)
    new = 0 if r["is_active"] else 1
    await db.run("UPDATE requisites SET is_active=? WHERE id=?", new, rid)
    status = "🟢 рабочий" if new else "🔴 не рабочий"
    await db.audit(user["id"], f"Реквизит #{rid} → {status}")
    await cb.answer(f"Теперь {status}")
    await notify_all(
        bot, db,
        f"💳 Реквизит #{rid} {esc(r['iban'])} ({esc(r['holder'])}) теперь <b>{status}</b>.\n"
        f"Изменил: {user_name(user)}",
        exclude_user_id=user["id"],
    )
    text, markup = await card_view(db, user, rid)
    await show(cb, text, markup)


@router.callback_query(F.data.startswith("rq:del:"))
async def req_delete_ask(cb: CallbackQuery, user):
    if not is_admin(user):
        return await cb.answer("Нет доступа", show_alert=True)
    rid = int(cb.data.split(":")[2])
    await cb.answer()
    await show(cb, f"🗑 Удалить реквизит #{rid}? Клиенты будут отвязаны от него.",
               kb([btn("✅ Да, удалить", f"rq:delok:{rid}"), btn("« Нет", f"rq:v:{rid}")]))


@router.callback_query(F.data.startswith("rq:delok:"))
async def req_delete(cb: CallbackQuery, db: DB, user, bot: Bot):
    if not is_admin(user):
        return await cb.answer("Нет доступа", show_alert=True)
    rid = int(cb.data.split(":")[2])
    r = await db.one("SELECT * FROM requisites WHERE id=?", rid)
    if r is None:
        return await cb.answer("Уже удалён", show_alert=True)
    await db.run("DELETE FROM requisites WHERE id=?", rid)
    await db.audit(user["id"], f"Удалил реквизит #{rid} {r['iban']}")
    await cb.answer("Удалено")
    await notify_admins(bot, db, f"🗑 {user_name(user)} удалил реквизит #{rid} {esc(r['iban'])}.",
                        exclude_user_id=user["id"])
    text, markup = await list_view(db, user)
    await show(cb, text, markup)


@router.callback_query(F.data.startswith("rq:c:"))
async def req_comment_start(cb: CallbackQuery, state: FSMContext, user):
    if not is_admin(user):
        return await cb.answer("Нет доступа", show_alert=True)
    await state.set_state(EditReqComment.text)
    await state.set_data({"rid": int(cb.data.split(":")[2])})
    await cb.answer()
    await cb.message.answer("Введите новый комментарий к реквизиту (или «-» чтобы очистить):",
                            reply_markup=cancel_kb())


@router.message(EditReqComment.text, F.text)
async def req_comment_save(message: Message, state: FSMContext, db: DB, user):
    rid = (await state.get_data()).get("rid")
    await state.clear()
    if not is_admin(user):
        return
    if rid is None or await db.one("SELECT id FROM requisites WHERE id=?", rid) is None:
        await message.answer("Реквизит не найден.")
        return
    value = None if message.text.strip() == "-" else message.text.strip()[:500]
    await db.run("UPDATE requisites SET comment=? WHERE id=?", value, rid)
    await db.audit(user["id"], f"Изменил комментарий реквизита #{rid}")
    text, markup = await card_view(db, user, rid)
    await message.answer(text or "Реквизит не найден", reply_markup=markup)


# --- добавление ---

@router.callback_query(F.data == "rq:add")
async def req_add_start(cb: CallbackQuery, state: FSMContext, user):
    if not is_admin(user):
        return await cb.answer("Нет доступа", show_alert=True)
    await state.set_state(NewReq.iban)
    await state.set_data({})
    await cb.answer()
    await cb.message.answer("Введите <b>IBAN</b> (например UA213223130000026007233566001):",
                            reply_markup=cancel_kb())


@router.message(NewReq.iban, F.text)
async def req_add_iban(message: Message, state: FSMContext, db: DB, user):
    if not is_admin(user):
        return await state.clear()
    iban = re.sub(r"\s+", "", message.text).upper()
    if not iban_ok(iban):
        await message.answer("❌ IBAN неверный (не сходится контрольная сумма или длина — проверьте опечатки). "
                             "Введите ещё раз:", reply_markup=cancel_kb())
        return
    dup = await db.one("SELECT id FROM requisites WHERE iban=?", iban)
    await state.update_data(iban=iban)
    await state.set_state(NewReq.holder)
    warn = f"⚠️ Такой IBAN уже есть: реквизит #{dup['id']}.\n\n" if dup else ""
    await message.answer(warn + "Введите <b>ФИО получателя</b>:", reply_markup=cancel_kb())


@router.message(NewReq.holder, F.text)
async def req_add_holder(message: Message, state: FSMContext, user):
    if not is_admin(user):
        return await state.clear()
    holder = " ".join(message.text.split())
    if not 3 <= len(holder) <= 120:
        await message.answer("Введите ФИО полностью:", reply_markup=cancel_kb())
        return
    await state.update_data(holder=holder)
    await state.set_state(NewReq.ipn)
    await message.answer("Введите <b>ІПН</b> получателя (10 цифр):", reply_markup=cancel_kb())


@router.message(NewReq.ipn, F.text)
async def req_add_ipn(message: Message, state: FSMContext, user):
    if not is_admin(user):
        return await state.clear()
    ipn = re.sub(r"\s+", "", message.text)
    if not re.fullmatch(r"\d{10}", ipn):
        await message.answer("ІПН должен состоять из 10 цифр. Введите ещё раз:", reply_markup=cancel_kb())
        return
    await state.update_data(ipn=ipn)
    await state.set_state(NewReq.comment)
    warn = "" if ipn_checksum_ok(ipn) else "⚠️ Контрольная цифра ІПН не сходится — проверьте, нет ли опечатки.\n\n"
    await message.answer(warn + "Комментарий к реквизиту (например, банк) или «-» чтобы пропустить:",
                         reply_markup=cancel_kb())


@router.message(NewReq.comment, F.text)
async def req_add_finish(message: Message, state: FSMContext, db: DB, user, bot: Bot):
    data = await state.get_data()
    await state.clear()
    if not is_admin(user):
        return
    if not all(k in data for k in ("iban", "holder", "ipn")):
        await message.answer("Данные устарели, начните заново.")
        return
    comment = None if message.text.strip() == "-" else message.text.strip()[:500]
    cur = await db.run(
        "INSERT INTO requisites(iban, holder, ipn, comment, is_active, created_by, created_at) "
        "VALUES (?, ?, ?, ?, 1, ?, ?)",
        data["iban"], data["holder"], data["ipn"], comment, user["id"], now(),
    )
    rid = cur.lastrowid
    await db.audit(user["id"], f"Добавил реквизит #{rid} {data['iban']}")
    r = await db.one("SELECT * FROM requisites WHERE id=?", rid)
    await notify_admins(bot, db, f"➕ {user_name(user)} добавил реквизит {req_short(r)}.",
                        exclude_user_id=user["id"])
    text, markup = await card_view(db, user, rid)
    await message.answer("✅ Реквизит добавлен.\n\n" + text, reply_markup=markup)
