from aiogram import F, Router
from aiogram.fsm.context import FSMContext
from aiogram.types import CallbackQuery, Message

from ..db import DB
from ..keyboards import BTN_LOG, BTN_MY_STATS, BTN_REPORTS, btn, kb
from ..reports import PERIODS, admin_report, period, worker_report
from ..utils import esc, fmt_dt, is_admin, user_name
from .common import show

router = Router(name="reports")


def periods_kb():
    items = list(PERIODS.items())
    return kb(*[[btn(v, f"rep:{k}") for k, v in items[i:i + 2]] for i in range(0, len(items), 2)])


@router.message(F.text == BTN_REPORTS)
async def reports_menu(message: Message, state: FSMContext, db: DB, user):
    await state.clear()
    if not is_admin(user):
        return
    s, e, title = period("today")
    await message.answer(await admin_report(db, s, e, f"Отчёт: {title}"), reply_markup=periods_kb())


@router.callback_query(F.data.startswith("rep:"))
async def report_period(cb: CallbackQuery, db: DB, user):
    if not is_admin(user):
        return await cb.answer("Нет доступа", show_alert=True)
    kind = cb.data.split(":")[1]
    s, e, title = period(kind if kind in PERIODS else "today")
    await cb.answer()
    await show(cb, await admin_report(db, s, e, f"Отчёт: {title}"), periods_kb())


@router.message(F.text == BTN_MY_STATS)
async def my_stats(message: Message, state: FSMContext, db: DB, user):
    await state.clear()
    parts = []
    for kind, label in (("today", "Сегодня"), ("month", "Этот месяц"), ("all", "За всё время")):
        s, e, _ = period(kind)
        parts.append(await worker_report(db, user, s, e, label))
    clients = await db.one(
        "SELECT COUNT(*) n, SUM(status='work') w, SUM(status='paid') p, SUM(status='lost') l "
        "FROM clients WHERE worker_id=?", user["id"])
    header = (f"👷 <b>{esc(user['nick'])}</b> · ваш процент: {user['percent']:g}%\n"
              f"Клиентов: {clients['n']} (в работе {clients['w'] or 0}, оплачено {clients['p'] or 0}, "
              f"слив {clients['l'] or 0})")
    await message.answer(header + "\n\n" + "\n\n".join(parts))


@router.message(F.text == BTN_LOG)
async def audit_log(message: Message, state: FSMContext, db: DB, user):
    await state.clear()
    if not is_admin(user):
        return
    rows = await db.all("SELECT * FROM audit ORDER BY id DESC LIMIT 40")
    if not rows:
        await message.answer("📜 Журнал пуст.")
        return
    lines = ["📜 <b>Последние действия</b>\n"]
    for r in rows:
        u = await db.get_user(r["user_id"])
        lines.append(f"<i>{fmt_dt(r['created_at'])}</i> {user_name(u)}: {esc(r['text'])}")
    text = "\n".join(lines)
    while text:
        cut = text[:4000].rfind("\n") if len(text) > 4000 else len(text)
        await message.answer(text[:cut])
        text = text[cut:].lstrip("\n")
