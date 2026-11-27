from datetime import date, timedelta

from .db import DB
from .utils import day_range, esc, fmt_money, today

PERIODS = {
    "today": "Сегодня",
    "yesterday": "Вчера",
    "week": "7 дней",
    "month": "Этот месяц",
    "prevmonth": "Прошлый месяц",
    "all": "За всё время",
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


SHARE = "COALESCE(SUM(p.amount * COALESCE(p.worker_percent, 0) / 100.0), 0)"


async def admin_report(db: DB, start: int, end: int, title: str) -> str:
    tot = await db.one(
        f"SELECT COUNT(*) n, COALESCE(SUM(p.amount),0) s, {SHARE} sh FROM payments p "
        "WHERE p.status='confirmed' AND p.reviewed_at>=? AND p.reviewed_at<?", start, end)
    pend = await db.one("SELECT COUNT(*) n, COALESCE(SUM(amount),0) s FROM payments WHERE status='pending'")
    new_clients = await db.one(
        "SELECT COUNT(*) n FROM clients WHERE created_at>=? AND created_at<?", start, end)
    statuses = await db.one(
        "SELECT SUM(status='work') w, SUM(status='paid') p, SUM(status='lost') l FROM clients")
    by_worker = await db.all(
        f"SELECT u.nick, u.username, COUNT(*) n, SUM(p.amount) s, {SHARE} sh "
        "FROM payments p LEFT JOIN users u ON u.id=p.worker_id "
        "WHERE p.status='confirmed' AND p.reviewed_at>=? AND p.reviewed_at<? "
        "GROUP BY p.worker_id ORDER BY s DESC", start, end)
    by_req = await db.all(
        "SELECT r.id, r.iban, r.holder, COUNT(*) n, SUM(p.amount) s "
        "FROM payments p LEFT JOIN requisites r ON r.id=p.requisite_id "
        "WHERE p.status='confirmed' AND p.reviewed_at>=? AND p.reviewed_at<? "
        "GROUP BY p.requisite_id ORDER BY s DESC", start, end)

    lines = [
        f"📊 <b>{esc(title)}</b>\n",
        f"💰 Оплачено клиентами: <b>{fmt_money(tot['s'])}</b> ({tot['n']} опл.)",
        f"👷 Доля сотрудников: {fmt_money(tot['sh'])}",
        f"🏦 Остаток: <b>{fmt_money(tot['s'] - round(tot['sh']))}</b>",
        f"⏳ Ждут подтверждения (сейчас): {pend['n']} на {fmt_money(pend['s'])}",
        f"🆕 Новых клиентов: {new_clients['n']}",
        f"👥 Клиенты сейчас: в работе {statuses['w'] or 0} · оплачено {statuses['p'] or 0} · "
        f"слив {statuses['l'] or 0}",
    ]
    if by_worker:
        lines.append("\n<b>По сотрудникам:</b>")
        for r in by_worker:
            name = esc(r["nick"] or r["username"] or "удалён")
            lines.append(f"• {name}: {fmt_money(r['s'])} ({r['n']}) → заработок {fmt_money(r['sh'])}")
    if by_req:
        lines.append("\n<b>По реквизитам:</b>")
        for r in by_req:
            name = f"#{r['id']} …{esc(r['iban'][-8:])} ({esc(r['holder'])})" if r["id"] else "без реквизита"
            lines.append(f"• {name}: {fmt_money(r['s'])} ({r['n']})")
    return "\n".join(lines)[:4000]


async def worker_report(db: DB, user, start: int, end: int, title: str) -> str:
    tot = await db.one(
        f"SELECT COUNT(*) n, COALESCE(SUM(p.amount),0) s, {SHARE} sh FROM payments p "
        "WHERE p.worker_id=? AND p.status='confirmed' AND p.reviewed_at>=? AND p.reviewed_at<?",
        user["id"], start, end)
    pend = await db.one(
        "SELECT COUNT(*) n, COALESCE(SUM(amount),0) s FROM payments WHERE worker_id=? AND status='pending'",
        user["id"])
    new_clients = await db.one(
        "SELECT COUNT(*) n FROM clients WHERE worker_id=? AND created_at>=? AND created_at<?",
        user["id"], start, end)
    return (
        f"📊 <b>{esc(title)}</b>\n"
        f"💰 Оплачено вашими клиентами: {fmt_money(tot['s'])} ({tot['n']} опл.)\n"
        f"💵 Ваш заработок: <b>{fmt_money(tot['sh'])}</b>\n"
        f"🆕 Новых клиентов: {new_clients['n']}\n"
        f"⏳ Ждут подтверждения: {pend['n']} на {fmt_money(pend['s'])}"
    )


def day_title(d: date) -> str:
    return d.strftime("%d.%m.%Y")
