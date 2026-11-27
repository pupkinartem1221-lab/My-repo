from aiogram import F, Router
from aiogram.fsm.context import FSMContext
from aiogram.types import CallbackQuery, Message

from ..db import DB
from ..keyboards import BLUE, BTN_LOG, BTN_MY_STATS, BTN_REPORTS, btn, home_btn, kb
from ..reports import PERIODS, admin_report, period, worker_totals
from ..ui import show
from ..utils import clip, esc, fit, fmt_money, fmt_short, is_admin, user_name

router = Router(name="reports")


def periods_kb(active: str = "today"):
    """Выбранный период подсвечен синим."""
    items = list(PERIODS.items())
    return kb(*[[btn(v, f"rep:{k}", BLUE if k == active else None) for k, v in items[i:i + 3]]
                for i in range(0, len(items), 3)], [home_btn()])


async def open_report(event, db: DB, kind: str = "today"):
    s, e, title = period(kind)
    await show(event, await admin_report(db, s, e, f"{PERIODS[kind]} · {title}"), periods_kb(kind))


@router.message(F.text == BTN_REPORTS)
async def reports_menu(message: Message, state: FSMContext, db: DB, user):
    await state.clear()
    if is_admin(user):
        await open_report(message, db)


@router.callback_query(F.data == "m:reports")
async def reports_menu_cb(cb: CallbackQuery, state: FSMContext, db: DB, user):
    await state.clear()
    if not is_admin(user):
        return await cb.answer("Нет доступа", show_alert=True)
    await cb.answer()
    await open_report(cb, db)


@router.callback_query(F.data.startswith("rep:"))
async def report_period(cb: CallbackQuery, db: DB, user):
    if not is_admin(user):
        return await cb.answer("Нет доступа", show_alert=True)
    kind = cb.data.split(":")[1]
    await cb.answer()
    await open_report(cb, db, kind if kind in PERIODS else "today")


async def stats_view(db: DB, user) -> str:
    rows = []
    for kind, label in (("today", "Сегодня"), ("week", "7 дней"), ("month", "Месяц"), ("all", "Всё время")):
        s, e, _ = period(kind)
        t = await worker_totals(db, user, s, e)
        rows.append(f"{label}: <b>{fmt_money(t['sh'])}</b> · {t['n']} опл.")
    c = await db.one("SELECT SUM(status='work') w, SUM(status='paid') p, SUM(status='lost') l "
                     "FROM clients WHERE worker_id=?", user["id"])
    pend = await db.one("SELECT COUNT(*) n, COALESCE(SUM(amount),0) s FROM payments "
                        "WHERE worker_id=? AND status='pending'", user["id"])
    text = (f"📊 <b>Моя статистика</b> · {user['percent']:g}%\n\n"
            "💵 <b>Заработок</b>\n" + "\n".join(rows) +
            f"\n\n👥 Клиенты: 🔄 {c['w'] or 0} · ✅ {c['p'] or 0} · ❌ {c['l'] or 0}")
    if pend["n"]:
        text += f"\n⏳ На проверке: {pend['n']} · {fmt_money(pend['s'])}"
    return text


@router.message(F.text == BTN_MY_STATS)
async def my_stats(message: Message, state: FSMContext, db: DB, user):
    await state.clear()
    await show(message, await stats_view(db, user), kb([home_btn()]))


@router.callback_query(F.data == "m:stats")
async def my_stats_cb(cb: CallbackQuery, state: FSMContext, db: DB, user):
    await state.clear()
    await cb.answer()
    await show(cb, await stats_view(db, user), kb([btn("🔄 Обновить", "m:stats"), home_btn()]))


async def log_view(db: DB) -> str:
    rows = await db.all("SELECT * FROM audit ORDER BY id DESC LIMIT 40")
    if not rows:
        return "📜 <b>Журнал</b>\n\nПока пусто."
    lines = ["📜 <b>Журнал</b> · последние действия\n"]
    for r in rows:
        u = await db.get_user(r["user_id"])
        lines.append(f"<i>{fmt_short(r['created_at'])}</i> {user_name(u)}: {esc(clip(r['text'], 120))}")
    return fit(lines)


@router.message(F.text == BTN_LOG)
async def audit_log(message: Message, state: FSMContext, db: DB, user):
    await state.clear()
    if is_admin(user):
        await show(message, await log_view(db), kb([home_btn()]))


@router.callback_query(F.data == "m:log")
async def audit_log_cb(cb: CallbackQuery, state: FSMContext, db: DB, user):
    await state.clear()
    if not is_admin(user):
        return await cb.answer("Нет доступа", show_alert=True)
    await cb.answer()
    await show(cb, await log_view(db), kb([btn("🔄 Обновить", "m:log"), home_btn()]))
