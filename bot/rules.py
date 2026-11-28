"""Общие правила для бота и мини-приложения (одна реализация для обоих)."""
from .db import DB

RECEIPT_REQUIRED = "Чтобы поставить «Оплачено», прикрепите квитанцию"

# Доля сотрудника в копейках: целочисленно (проценты в сотых долях), округление половины вверх.
def share_sql(pct: str) -> str:
    return f"(amount * CAST(ROUND(COALESCE({pct}, 0) * 100) AS INTEGER) + 5000) / 10000"


WORKER_PCT = "(SELECT percent FROM users WHERE users.id=payments.worker_id)"
HAS_RECEIPT = "EXISTS (SELECT 1 FROM payments WHERE client_id={cid} AND status IN ('pending','confirmed'))"
REVERT_PAID = ("UPDATE clients SET status='work' WHERE id=? AND status='paid' AND NOT EXISTS "
               "(SELECT 1 FROM payments WHERE client_id=? AND status IN ('pending','confirmed'))")


async def has_receipt(db: DB, client_id: int) -> bool:
    """Есть ли у клиента квитанция на проверке или подтверждённая."""
    return await db.one("SELECT 1 FROM payments WHERE client_id=? AND status IN ('pending','confirmed') LIMIT 1",
                        client_id) is not None


async def set_status(db: DB, client_id: int, status: str) -> bool:
    """Сменить статус клиента. «Оплачено» ставится только при наличии квитанции — проверка и запись атомарны.
    False — «Оплачено» без квитанции (нужно прикрепить)."""
    cur = await db.run(
        "UPDATE clients SET status=? WHERE id=? AND (?<>'paid' OR " + HAS_RECEIPT.format(cid="?") + ")",
        status, client_id, status, client_id)
    return cur.rowcount > 0


async def revert_paid_if_no_receipt(db: DB, client_id: int | None) -> bool:
    """«Оплачено» без квитанции не остаётся: вернуть клиента в работу. True — статус изменён."""
    if not client_id:
        return False
    return (await db.run(REVERT_PAID, client_id, client_id)).rowcount > 0


async def confirm_payment(db: DB, pid: int, reviewer_id: int, ts: int) -> bool:
    """Подтвердить квитанцию: статус, процент и заработок сотрудника, «Оплачено» у клиента — одной транзакцией."""
    curs = await db.run_many([
        ("UPDATE payments SET status='confirmed', reviewed_by=?, reviewed_at=?, "
         f"worker_percent={WORKER_PCT}, worker_share={share_sql(WORKER_PCT)} "
         "WHERE id=? AND status='pending'", reviewer_id, ts, pid),
        ("UPDATE clients SET status='paid' WHERE id=(SELECT client_id FROM payments "
         "WHERE id=? AND status='confirmed' AND reviewed_at=? AND reviewed_by=?)", pid, ts, reviewer_id),
    ])
    return curs[0].rowcount > 0


async def reject_payment(db: DB, pid: int, reviewer_id: int, ts: int) -> tuple[bool, bool]:
    """Отклонить квитанцию (+ вернуть клиента в работу, если квитанций не осталось). (отклонена, статус возвращён)."""
    row = await db.one("SELECT client_id FROM payments WHERE id=?", pid)
    cid = row["client_id"] if row else None
    curs = await db.run_many([
        ("UPDATE payments SET status='rejected', reviewed_by=?, reviewed_at=? WHERE id=? AND status='pending'",
         reviewer_id, ts, pid),
        (REVERT_PAID, cid, cid),
    ])
    return curs[0].rowcount > 0, curs[1].rowcount > 0


async def delete_payment(db: DB, pid: int, client_id: int | None) -> bool:
    curs = await db.run_many([("DELETE FROM payments WHERE id=?", pid), (REVERT_PAID, client_id, client_id)])
    return curs[0].rowcount > 0


async def set_percent(db: DB, user_id: int, value: float) -> int:
    """Новый процент сотрудника + пересчёт ВСЕГО его заработка по подтверждённым оплатам — одной транзакцией.
    Возвращает количество пересчитанных оплат."""
    curs = await db.run_many([
        ("UPDATE users SET percent=? WHERE id=?", value, user_id),
        (f"UPDATE payments SET worker_percent=?, worker_share={share_sql('?')} WHERE worker_id=? AND status='confirmed'",
         value, value, user_id),
    ])
    return curs[1].rowcount


async def worker_total(db: DB, user_id: int) -> int:
    row = await db.one("SELECT COALESCE(SUM(worker_share),0) s FROM payments WHERE worker_id=? AND status='confirmed'",
                       user_id)
    return row["s"]


async def blocks_delete(db: DB, user_id: int) -> str | None:
    """Нельзя удалять сотрудника, пока у него есть клиенты или квитанции на проверке (иначе заработок «потеряется»)."""
    c = (await db.one("SELECT COUNT(*) n FROM clients WHERE worker_id=?", user_id))["n"]
    p = (await db.one("SELECT COUNT(*) n FROM payments WHERE worker_id=? AND status='pending'", user_id))["n"]
    if c or p:
        return (f"Сначала передайте его клиентов ({c}) другому сотруднику"
                + (f" и проверьте квитанции ({p})" if p else ""))
    return None


def payments_scope(alias: str = "p") -> str:
    """Какие квитанции видит сотрудник: свои (по клиенту) или загруженные им по клиенту, который всё ещё его."""
    return (f"({alias}.worker_id=? OR ({alias}.submitted_by=? AND EXISTS "
            f"(SELECT 1 FROM clients c2 WHERE c2.id={alias}.client_id AND c2.worker_id=?)))")
