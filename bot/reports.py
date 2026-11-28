from datetime import date, timedelta

from .db import DB
from .utils import day_range, deleted_req_label, esc, fit, fmt_money, today

PERIODS = {
    "today": "Сегодня",
    "yesterday": "Вчера",
    "week": "7 дней",
    "month": "Месяц",
    "prevmonth": "Прошлый месяц",
    "all": "Всё время",
}


def period(kind: str) -> tuple[int, int, str]:
    t = today()
    if kind == "yesterday":
        d = t - timedelta(days=1)
        s, e = day_range(d)
        return s, e, d.strftime("%d.%m.%Y")
    if kind == "week":
        start = t - timedelta(days=6)
        return day_range(start)[0], day_range(t)[1], f"{start:%d.%m} – {t:%d.%m.%Y}"
    if kind == "month":
        start = t.replace(day=1)
        return day_range(start)[0], day_range(t)[1], f"{start:%d.%m} – {t:%d.%m.%Y}"
    if kind == "prevmonth":
        end = t.replace(day=1) - timedelta(days=1)
        start = end.replace(day=1)
        return day_range(start)[0], day_range(end)[1], f"{start:%d.%m} – {end:%d.%m.%Y}"
    if kind == "all":
        return 0, day_range(t)[1], "всё время"
    s, e = day_range(t)
    return s, e, t.strftime("%d.%m.%Y")


SHARE = "COALESCE(SUM(p.worker_share), 0)"


async def admin_report(db: DB, start: int, end: int, title: str) -> str:
    tot = await db.one(
        f"SELECT COUNT(*) n, COALESCE(SUM(p.amount),0) s, {SHARE} sh FROM payments p "
        "WHERE p.status='confirmed' AND p.reviewed_at>=? AND p.reviewed_at<?", start, end)
    pend = await db.one("SELECT COUNT(*) n, COALESCE(SUM(amount),0) s FROM payments WHERE status='pending'")
    new_clients = await db.one("SELECT COUNT(*) n FROM clients WHERE created_at>=? AND created_at<?", start, end)
    by_worker = await db.all(
        f"SELECT p.worker_id wid, u.nick, u.username, COUNT(*) n, SUM(p.amount) s, {SHARE} sh "
        "FROM payments p LEFT JOIN users u ON u.id=p.worker_id "
        "WHERE p.status='confirmed' AND p.reviewed_at>=? AND p.reviewed_at<? "
        "GROUP BY p.worker_id ORDER BY s DESC", start, end)
    by_req = await db.all(
        "SELECT r.id, r.iban, r.holder, p.requisite_label label, COUNT(*) n, SUM(p.amount) s "
        "FROM payments p LEFT JOIN requisites r ON r.id=p.requisite_id "
        "WHERE p.status='confirmed' AND p.reviewed_at>=? AND p.reviewed_at<? "
        "GROUP BY COALESCE(CAST(p.requisite_id AS TEXT), p.requisite_label) ORDER BY s DESC", start, end)

    lines = [
        f"📊 <b>{esc(title)}</b>\n",
        f"💰 Оплачено: <b>{fmt_money(tot['s'])}</b> · {tot['n']} опл.",
        f"👷 Сотрудникам: {fmt_money(tot['sh'])}",
        f"🏦 Остаток: <b>{fmt_money(tot['s'] - tot['sh'])}</b>",
        f"🆕 Новых клиентов: {new_clients['n']}",
    ]
    if pend["n"]:
        lines.append(f"⏳ Сейчас на проверке: {pend['n']} · {fmt_money(pend['s'])}")
    if by_worker:
        lines.append("\n<b>Сотрудники</b>")
        for r in by_worker:
            name = esc(r["nick"] or r["username"] or (f"id{r['wid']}" if r["wid"] else "удалён"))
            lines.append(f"• {name}: {fmt_money(r['s'])} → 💵 {fmt_money(r['sh'])}")
    if by_req:
        lines.append("\n<b>Поступления по реквизитам</b>")
        for r in by_req:
            if r["id"]:
                name = f"…{esc(r['iban'][-6:])} {esc(r['holder'])}"
            else:
                name = esc(deleted_req_label(r["label"]))
            lines.append(f"• {name}: {fmt_money(r['s'])}")
    if not tot["n"]:
        lines.append("\n<i>Подтверждённых оплат за период нет.</i>")
    return fit(lines)


async def worker_totals(db: DB, user, start: int, end: int):
    return await db.one(
        f"SELECT COUNT(*) n, COALESCE(SUM(p.amount),0) s, {SHARE} sh FROM payments p "
        "WHERE p.worker_id=? AND p.status='confirmed' AND p.reviewed_at>=? AND p.reviewed_at<?",
        user["id"], start, end)


async def worker_report(db: DB, user, start: int, end: int, title: str) -> str:
    tot = await worker_totals(db, user, start, end)
    new_clients = await db.one(
        "SELECT COUNT(*) n FROM clients WHERE worker_id=? AND created_at>=? AND created_at<?",
        user["id"], start, end)
    return (
        f"📊 <b>{esc(title)}</b>\n\n"
        f"💵 Ваш заработок: <b>{fmt_money(tot['sh'])}</b>\n"
        f"💰 Оплатили клиенты: {fmt_money(tot['s'])} · {tot['n']} опл.\n"
        f"🆕 Новых клиентов: {new_clients['n']}"
    )


def day_title(d: date) -> str:
    return d.strftime("%d.%m.%Y")
