import re

from aiogram import Bot, F, Router
from aiogram.fsm.context import FSMContext
from aiogram.fsm.state import State, StatesGroup
from aiogram.types import CallbackQuery, Message

from ..db import DB
from ..keyboards import (BTN_REQS, back_btn, btn, cancel_kb, confirm_kb, copy_btn, danger_btn, home_btn, kb,
                         ok_btn, pager)
from ..notify import notify_admins, notify_all
from ..ui import show
from ..utils import (clip, day_range, esc, fmt_money, fmt_short, iban_ok, ipn_checksum_ok, is_admin, now, today,
                     user_name)

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
    return f"{req_icon(r)} …{esc(r['iban'][-6:])} {esc(r['holder'])}"


def req_copy_kb(r, *extra_rows):
    """Кнопки «скопировать» для каждого поля и для всего текста сразу."""
    full = f"IBAN: {r['iban']}\nОтримувач: {r['holder']}\nІПН: {r['ipn']}"
    return kb(
        [copy_btn("📋 IBAN", r["iban"]), copy_btn("📋 ІПН", r["ipn"])],
        [copy_btn("📋 ФИО", r["holder"]), copy_btn("📋 Всё сразу", full)],
        *extra_rows,
    )


def req_for_client(r) -> str:
    return (
        "💳 <b>Реквизиты для оплаты</b>\n\n"
        f"IBAN: <code>{esc(r['iban'])}</code>\n"
        f"Получатель: <code>{esc(r['holder'])}</code>\n"
        f"ІПН: <code>{esc(r['ipn'])}</code>"
    )


# ---------- список ----------

async def list_view(db: DB, user, page: int = 0):
    admin = is_admin(user)
    where = "" if admin else "WHERE is_active=1 "
    total = (await db.one("SELECT COUNT(*) n FROM requisites " + where))["n"]
    active = (await db.one("SELECT COUNT(*) n FROM requisites WHERE is_active=1"))["n"]
    pages = max(1, (total + PAGE - 1) // PAGE)
    page = min(max(page, 0), pages - 1)
    rows = await db.all("SELECT * FROM requisites " + where + "ORDER BY is_active DESC, id DESC LIMIT ? OFFSET ?",
                        PAGE, page * PAGE)
    if not total:
        text = "💳 <b>Реквизиты</b>\n\nПока пусто." + (" Добавьте первый 👇" if admin else "")
    elif admin:
        text = f"💳 <b>Реквизиты</b> · 🟢 {active} · 🔴 {total - active}"
    else:
        text = f"💳 <b>Рабочие реквизиты</b> · {total}"
    buttons = [[btn(clip(f"{req_icon(r)} …{r['iban'][-6:]} · {r['holder']}", 60), f"rq:v:{r['id']}")]
               for r in rows]
    buttons.append(pager("rq:list:", page, pages))
    if admin:
        buttons.append([ok_btn("➕ Добавить", "rq:add")])
    buttons.append([home_btn()])
    return text, kb(*buttons)


async def open_list(event, db: DB, user, page: int = 0):
    text, markup = await list_view(db, user, page)
    await show(event, text, markup)


@router.message(F.text == BTN_REQS)
async def reqs_menu(message: Message, state: FSMContext, db: DB, user):
    await state.clear()
    await open_list(message, db, user)


@router.callback_query(F.data == "m:reqs")
async def reqs_menu_cb(cb: CallbackQuery, state: FSMContext, db: DB, user):
    await state.clear()
    await cb.answer()
    await open_list(cb, db, user)


@router.callback_query(F.data.startswith("rq:list"))
async def reqs_list_cb(cb: CallbackQuery, db: DB, user):
    parts = cb.data.split(":")
    await cb.answer()
    await open_list(cb, db, user, int(parts[2]) if len(parts) > 2 else 0)


# ---------- карточка ----------

async def card_view(db: DB, user, rid: int, note: str = ""):
    r = await db.one("SELECT * FROM requisites WHERE id=?", rid)
    if r is None or (not is_admin(user) and not r["is_active"]):
        return None, None
    lines = [note, ""] if note else []
    lines += [
        f"💳 <b>Реквизит</b> · {'🟢 рабочий' if r['is_active'] else '🔴 не рабочий'}\n",
        f"IBAN: <code>{esc(r['iban'])}</code>",
        f"Получатель: <code>{esc(r['holder'])}</code>",
        f"ІПН: <code>{esc(r['ipn'])}</code>",
    ]
    if r["comment"]:
        lines.append(f"📝 {esc(r['comment'])}")
    back = [back_btn("rq:list:0", "« Реквизиты"), home_btn()]
    if not is_admin(user):
        return "\n".join(lines), req_copy_kb(r, back)
    s, e = day_range(today())
    total = await db.one("SELECT COUNT(*) n, COALESCE(SUM(amount),0) s FROM payments "
                         "WHERE requisite_id=? AND status='confirmed'", rid)
    day = await db.one("SELECT COALESCE(SUM(amount),0) s FROM payments WHERE requisite_id=? "
                       "AND status='confirmed' AND reviewed_at>=? AND reviewed_at<?", rid, s, e)
    clients = await db.one("SELECT COUNT(*) n FROM clients WHERE requisite_id=?", rid)
    author = await db.get_user(r["created_by"])
    lines += [
        f"\n💰 Сегодня {fmt_money(day['s'])} · всего {fmt_money(total['s'])} ({total['n']})",
        f"👥 Клиентов: {clients['n']}",
        f"<i>Добавил {user_name(author)}, {fmt_short(r['created_at'])}</i>",
    ]
    toggle = (danger_btn("🔴 Сделать нерабочим", f"rq:t:{rid}") if r["is_active"]
              else ok_btn("🟢 Сделать рабочим", f"rq:t:{rid}"))
    markup = req_copy_kb(r, [toggle],
                         [btn("📝 Комментарий", f"rq:c:{rid}"), danger_btn("🗑 Удалить", f"rq:del:{rid}")],
                         back)
    return "\n".join(lines), markup


async def open_card(event, db: DB, user, rid: int, note: str = "") -> bool:
    text, markup = await card_view(db, user, rid, note)
    if text is None:
        return False
    await show(event, text, markup)
    return True


@router.callback_query(F.data.startswith("rq:v:"))
async def req_card(cb: CallbackQuery, state: FSMContext, db: DB, user):
    await state.clear()
    text, markup = await card_view(db, user, int(cb.data.split(":")[2]))
    if text is None:
        return await cb.answer("Реквизит не найден", show_alert=True)
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
    await open_card(cb, db, user, rid)
    await notify_all(bot, db, f"💳 …{esc(r['iban'][-6:])} {esc(r['holder'])} — теперь <b>{status}</b>",
                     exclude_user_id=user["id"])


@router.callback_query(F.data.startswith("rq:del:"))
async def req_delete_ask(cb: CallbackQuery, db: DB, user):
    if not is_admin(user):
        return await cb.answer("Нет доступа", show_alert=True)
    rid = int(cb.data.split(":")[2])
    r = await db.one("SELECT * FROM requisites WHERE id=?", rid)
    if r is None:
        return await cb.answer("Уже удалён", show_alert=True)
    await cb.answer()
    await show(cb, f"🗑 Удалить реквизит …{esc(r['iban'][-6:])} {esc(r['holder'])}?\n\n"
                   "Клиенты будут отвязаны. В отчётах он останется.",
               confirm_kb(f"rq:delok:{rid}", f"rq:v:{rid}"))


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
    await open_list(cb, db, user)
    await notify_admins(bot, db, f"🗑 {user_name(user)} удалил реквизит …{esc(r['iban'][-6:])}",
                        exclude_user_id=user["id"])


@router.callback_query(F.data.startswith("rq:c:"))
async def req_comment_start(cb: CallbackQuery, state: FSMContext, user):
    if not is_admin(user):
        return await cb.answer("Нет доступа", show_alert=True)
    rid = int(cb.data.split(":")[2])
    await state.set_state(EditReqComment.text)
    await state.set_data({"rid": rid})
    await cb.answer()
    await show(cb, "📝 Новый комментарий к реквизиту:",
               kb([btn("🧹 Очистить", "rq:cclear"), btn("✖️ Отмена", f"rq:v:{rid}")]))


async def save_req_comment(event, state: FSMContext, db: DB, user, value):
    rid = (await state.get_data()).get("rid")
    await state.clear()
    if not is_admin(user):
        return
    if rid is None or await db.one("SELECT id FROM requisites WHERE id=?", rid) is None:
        await show(event, "Реквизит не найден.", kb([home_btn()]))
        return
    await db.run("UPDATE requisites SET comment=? WHERE id=?", value, rid)
    await db.audit(user["id"], f"Изменил комментарий реквизита #{rid}")
    await open_card(event, db, user, rid, "✅ Сохранено")


@router.message(EditReqComment.text, F.text)
async def req_comment_save(message: Message, state: FSMContext, db: DB, user):
    await save_req_comment(message, state, db, user, message.text.strip()[:500])


@router.callback_query(EditReqComment.text, F.data == "rq:cclear")
async def req_comment_clear(cb: CallbackQuery, state: FSMContext, db: DB, user):
    await cb.answer()
    await save_req_comment(cb, state, db, user, None)


# ---------- добавление ----------

STEP = "➕ <b>Новый реквизит</b> · шаг {} из 4\n\n"


@router.callback_query(F.data == "rq:add")
async def req_add_start(cb: CallbackQuery, state: FSMContext, user):
    if not is_admin(user):
        return await cb.answer("Нет доступа", show_alert=True)
    await state.set_state(NewReq.iban)
    await state.set_data({})
    await cb.answer()
    await show(cb, STEP.format(1) + "IBAN (начинается с UA):", cancel_kb())


@router.message(NewReq.iban, F.text)
async def req_add_iban(message: Message, state: FSMContext, db: DB, user):
    if not is_admin(user):
        return await state.clear()
    iban = re.sub(r"\s+", "", message.text).upper()
    if not iban_ok(iban):
        await show(message, STEP.format(1) + "❗ IBAN с ошибкой — проверьте цифры. Ещё раз:", cancel_kb())
        return
    dup = await db.one("SELECT id FROM requisites WHERE iban=?", iban)
    await state.update_data(iban=iban)
    await state.set_state(NewReq.holder)
    warn = "⚠️ Такой IBAN уже есть в списке.\n\n" if dup else ""
    await show(message, STEP.format(2) + warn + "ФИО получателя:", cancel_kb())


@router.message(NewReq.holder, F.text)
async def req_add_holder(message: Message, state: FSMContext, user):
    if not is_admin(user):
        return await state.clear()
    holder = " ".join(message.text.split())
    if not 3 <= len(holder) <= 120:
        await show(message, STEP.format(2) + "Введите ФИО полностью:", cancel_kb())
        return
    await state.update_data(holder=holder)
    await state.set_state(NewReq.ipn)
    await show(message, STEP.format(3) + "ІПН получателя (10 цифр):", cancel_kb())


@router.message(NewReq.ipn, F.text)
async def req_add_ipn(message: Message, state: FSMContext, user):
    if not is_admin(user):
        return await state.clear()
    ipn = re.sub(r"\s+", "", message.text)
    if not re.fullmatch(r"\d{10}", ipn):
        await show(message, STEP.format(3) + "❗ ІПН — это 10 цифр. Ещё раз:", cancel_kb())
        return
    await state.update_data(ipn=ipn)
    await state.set_state(NewReq.comment)
    warn = "" if ipn_checksum_ok(ipn) else "⚠️ Похоже, в ІПН опечатка — проверьте.\n\n"
    await show(message, STEP.format(4) + warn + "Комментарий (например, банк):",
               kb([btn("⏭ Пропустить", "rq:skip"), btn("✖️ Отмена", "cancel")]))


@router.message(NewReq.comment, F.text)
async def req_add_comment(message: Message, state: FSMContext, db: DB, user, bot: Bot):
    await req_add_finish(message, state, db, user, bot, message.text.strip()[:500])


@router.callback_query(NewReq.comment, F.data == "rq:skip")
async def req_add_skip(cb: CallbackQuery, state: FSMContext, db: DB, user, bot: Bot):
    await cb.answer()
    await req_add_finish(cb, state, db, user, bot, None)


async def req_add_finish(event, state: FSMContext, db: DB, user, bot: Bot, comment):
    data = await state.get_data()
    await state.clear()
    if not is_admin(user):
        return
    if not all(k in data for k in ("iban", "holder", "ipn")):
        await show(event, "Данные устарели, начните заново.", kb([home_btn()]))
        return
    cur = await db.run(
        "INSERT INTO requisites(iban, holder, ipn, comment, is_active, created_by, created_at) "
        "VALUES (?, ?, ?, ?, 1, ?, ?)",
        data["iban"], data["holder"], data["ipn"], comment, user["id"], now())
    rid = cur.lastrowid
    await db.audit(user["id"], f"Добавил реквизит #{rid} {data['iban']}")
    await open_card(event, db, user, rid, "✅ Реквизит добавлен")
    await notify_admins(bot, db, f"➕ {user_name(user)} добавил реквизит …{esc(data['iban'][-6:])} "
                                 f"{esc(data['holder'])}", exclude_user_id=user["id"])
